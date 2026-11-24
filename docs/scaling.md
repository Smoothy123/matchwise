# Scaling the daily refresh to millions of postings

## What we measured at 5,000 postings

One CPU container (Docker on an Apple Silicon laptop), three simulated days, each
removing 3%, editing 5% and adding 150 postings:

| Step | Time | Notes |
|---|---|---|
| Apply the snapshot (diff + writes, one transaction) | 0.86–0.99 s | 5,000 rows compared by `source_id` + `content_hash` |
| Re-embed what changed | 12.5–13.5 s | 266–271 postings (150 new + ~120 whose embedded text changed) |
| Whole run | 13.4–14.4 s | versus 204 s to re-embed everything (~15× less work) |
| Re-apply the same snapshot | 1.9 s, 0 embeddings | the run is idempotent |

242 postings changed each day, but only about half of them needed a new vector:
salary edits and edits past the first 800 characters of the description change
`content_hash` (so cached reasons are refreshed) without changing the embedded
text (`embedded_hash`). Two hashes, two different questions.

## What changes at 1–10 million postings

**1. Diff in the database, not in Python.** Today the refresh loads every
`(source_id, content_hash)` into a Python dict and writes row by row. At millions
of rows: stream the feed into a staging table with `COPY` (no Python objects),
then run three set-based statements: `INSERT ... SELECT` for new ids,
`UPDATE ... FROM staging WHERE content_hash <> ...` for changed rows, and an
anti-join (`NOT EXISTS`) for removals. `source_id` is already unique-indexed, so
each is one pass. The truncated-feed guard becomes a count on the staging table,
checked before anything is applied.

**2. Embedding becomes a queue.** The apply step marks what needs embedding;
workers pull batches (`SELECT ... FOR UPDATE SKIP LOCKED` on a Postgres table, or
SQS/Kafka), embed 256–1,024 texts per batch, and write vectors back. Because "needs
embedding" is defined by a hash comparison, retries and duplicate deliveries are
harmless. At a typical 3–5% daily churn, 1M postings means roughly 30–55k
embeddings a day. Our measured CPU rate (~21/s per container) gives ~40 minutes on
one container; a single GPU does thousands per second, so a few minutes.

One bottleneck we can already see: `embed_pending` recomputes the job card hash for
every active posting to find the changed ones (1.1 s at 5,000, so roughly 4 minutes
at 1M). Storing `card_hash` when a row is written turns that into an indexed
`WHERE embedded_hash IS DISTINCT FROM card_hash`.

**3. The HNSW index is updated in place.** HNSW takes inserts without a rebuild
(IVFFlat would drift as its clusters went stale). Updates and soft deletes leave
dead entries, which vacuum cleans up. Run `evals/hnsw_recall.py` on a schedule
and `REINDEX CONCURRENTLY` if recall drops. Memory: 1M × 384 float32 is ~1.5 GB
of vectors plus the graph; `halfvec` (16-bit) halves it with little recall loss.
Keep removed postings out of the graph with a partial index (`WHERE is_active`)
or an archive partition.

**4. Filters need help when they are very selective.** pgvector's iterative scan
stops after `hnsw.max_scan_tuples` (default 20,000) rows, so a narrow filter
(one small town, one rare skill) over millions of rows can return too few
results. Options: partition by country or region, index the filter columns so the
planner can run an exact search over a small filtered subset, or move to an
engine built for filtered vector search (pgvectorscale, a dedicated vector DB)
past tens of millions.

**5. Reasons stay cheap.** The reasons cache is keyed by content hash, so
unchanged postings keep their reasons across days, and edited ones regenerate
lazily the next time someone views them. Never pre-generate reasons for every
(person, posting) pair: that grows as people × postings. The daily prune
(`prune_reasons`) needs an index on `jobs(content_hash)` at that size, or a TTL.

**6. Operating it.** `refresh_runs` already records every run's counts, timings,
status and error. Alert on: a failed run, a run that didn't happen, counts far from
normal (0 new postings, or 40% removed), and duration creeping up. Runs are
idempotent, so the fix for a failed run is usually to run it again.
