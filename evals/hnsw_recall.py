"""How much accuracy does the HNSW index give up for speed? Compare it with an exact scan.

    python -m evals.hnsw_recall --queries 200 --k 10

Queries are the titles of randomly chosen postings (short, realistic search
text). Each query runs once as an exact sequential scan and once through the
HNSW index at several ef_search values. recall@k = the share of the exact top-k
that the index also returned. Prints a markdown table.
"""

import argparse
import statistics
import time

import psycopg

from matchwise import db, embeddings
from matchwise.config import get_settings, setup_logging

NEIGHBOURS_SQL = "SELECT id FROM jobs WHERE embedding IS NOT NULL ORDER BY embedding <=> %s LIMIT %s"


def nearest_ids(conn: psycopg.Connection, vector, k: int, ef_search: int | None) -> tuple[list[int], float]:
    """Top-k ids and the query time in ms. ef_search=None means an exact scan."""
    with conn.transaction():
        if ef_search is None:
            conn.execute("SET LOCAL enable_indexscan = off")  # full scan + sort: the exact answer
        else:
            conn.execute("SET LOCAL enable_seqscan = off")    # make the planner use the HNSW index
            conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),))
        started = time.perf_counter()
        ids = [row["id"] for row in conn.execute(NEIGHBOURS_SQL, (vector, k))]
        return ids, (time.perf_counter() - started) * 1000


def percentile(values: list[float], p: float) -> float:
    return statistics.quantiles(values, n=100)[int(p) - 1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = get_settings()
    setup_logging("WARNING")
    with db.connect(settings.database_url) as conn:
        conn.execute("SELECT setseed(%s)", (args.seed / 1000,))  # same random titles every run
        titles = [r["title"] for r in conn.execute(
            "SELECT title FROM jobs WHERE embedding IS NOT NULL ORDER BY random() LIMIT %s", (args.queries,)
        )]
        vectors = embeddings.embed_texts(titles)
        corpus = conn.execute("SELECT count(*) AS n FROM jobs WHERE embedding IS NOT NULL").fetchone()["n"]

        for vector in vectors[:10]:  # warm the caches so the first timings aren't outliers
            nearest_ids(conn, vector, args.k, None)
            nearest_ids(conn, vector, args.k, 40)

        exact = [nearest_ids(conn, v, args.k, None) for v in vectors]
        print(f"{len(titles)} queries over {corpus} vectors, k = {args.k}\n")
        print(f"| Method | recall@{args.k} | p50 ms | p95 ms |")
        print("|---|---|---|---|")
        exact_ms = [ms for _, ms in exact]
        print(f"| Exact scan | 1.000 | {percentile(exact_ms, 50):.2f} | {percentile(exact_ms, 95):.2f} |")
        for ef in (10, 40, 100):
            if ef < args.k:
                continue
            runs = [nearest_ids(conn, v, args.k, ef) for v in vectors]
            recalls = [len(set(ids) & set(true_ids)) / args.k for (ids, _), (true_ids, _) in zip(runs, exact)]
            ms = [m for _, m in runs]
            print(f"| HNSW, ef_search={ef} | {statistics.mean(recalls):.3f} | "
                  f"{percentile(ms, 50):.2f} | {percentile(ms, 95):.2f} |")


if __name__ == "__main__":
    main()
