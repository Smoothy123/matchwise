# Evals

Everything here is plain files, so every number can be traced back:

| File | What it is | Who makes it |
|---|---|---|
| `profiles.toml` | 15 personas, in their own words | written by hand |
| `profiles_extracted.json` | their preferences as the extractor understood them, frozen | `python -m evals.extract` |
| `pool.json` | which postings to label for each persona | `python -m evals.label pool` |
| `labels.jsonl` | a grade for every pooled posting; each line names its `labeller` | a person with `python -m evals.label`, or an independent model |
| `reference_scores.jsonl` | scores for a sample of reasons, to check the judge; each line names its `scorer` | a person with `python -m evals.judge score`, or an independent model |
| `results/` | tables for the README, judge scores, the extraction review | the scripts below |

Run every command inside the app container, in your own terminal (labelling is interactive):

```bash
docker compose run --rm app python -m evals.label status
```

## 1. Label the pool (about an hour, in as many sittings as you like)

```bash
docker compose run --rm app python -m evals.label
```

For each persona you first see what they said. Then postings come one at a time, shuffled,
with no hint of which system found them. Type a grade and press Enter:

| Type | Means | Example (ICU nurse who wants Texas, no night shifts) |
|---|---|---|
| `2` | **Good match**: you'd want them to see this | RN, ICU, Houston TX, day shift |
| `1` | **Okay**: partly fits; worth a look, not a great fit | RN, step-down unit, Dallas TX |
| `0` | **Not a fit** | Pharmacy tech in Texas; ICU RN in Ohio |
| add `x` | **Breaks something they ruled out** (e.g. `0x`) | ICU RN in Texas, *nights only* |

Other keys: `d` full description, `b` go back and re-grade, `s` skip (counts as unlabelled), `q` quit.
Progress is saved after every answer; run the command again to continue.

Judge against **what the persona said**, not against the extracted preferences: if the
extractor misunderstood someone, that should show up as a ranking failure, not get baked into
the answer key. Don't overthink it: a few seconds each. Consistency matters more than precision.

Only one persona: `--profile icu-nurse`.

## 2. Score 20 reasons yourself (about 10 minutes)

```bash
docker compose run --rm app python -m evals.judge score
```

You'll see the persona, the posting and the reason; give each of three scores from 1 to 5.
You never see the judge's scores, so yours are independent.

| | 5 | 3 | 1 |
|---|---|---|---|
| **specific** | names concrete details of this posting | partly | could describe any job |
| **grounded** | every claim, and every "matched" preference, is true of this posting | one doubtful or overstated claim | invents facts or claims matches that aren't there |
| **honest** | caveats cover every real mismatch or unknown | misses one important issue | hides obvious problems |

## 3. Produce the tables

```bash
docker compose run --rm app python -m evals.run_ranking       # ranking table -> results/ranking.md
docker compose run --rm app python -m evals.judge agree       # judge vs you -> results/judge_agreement.md
```

`evals.judge run` (already done) wrote `results/reasons.md`. Set `JUDGE_MODEL` in `.env` to
judge with a different model than the one that writes the reasons.

## How to read the numbers

- **P@5**: of the first 5 results, how many you graded 2.
- **R@20**: of all the postings you graded 2 for that persona, how many appear in the top 20.
- **nDCG@10**: are better matches higher up? Uses all three grades.
- **violations@10**: share of the top 10 you flagged with `x`. Must be 0 for any version with filters.
  Your flags check the filters independently: a filter that misses something shows up here.
- **judged@10**: share of the top 10 you labelled. Unlabelled postings count as "not a match",
  so if this drops (say, after a ranking change), label the new postings before trusting the numbers.
- Brackets are 95% bootstrap intervals over personas. With 15 personas they are wide, and
  differences smaller than about 0.05 are noise.
