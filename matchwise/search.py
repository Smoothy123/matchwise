"""Semantic search: the active postings closest in meaning to a query vector."""

import numpy as np
import psycopg

SEARCH_SQL = """
SELECT id, title, company, location, remote, seniority, skills,
       left(description, 240) AS snippet,
       1 - (embedding <=> %(query)s) AS similarity      -- <=> is cosine distance
FROM jobs
WHERE is_active AND embedding IS NOT NULL
ORDER BY embedding <=> %(query)s
LIMIT %(limit)s
"""


def tune_hnsw(conn: psycopg.Connection, limit: int) -> None:
    """HNSW settings for the current transaction (call inside `with conn.transaction()`)."""
    # ef_search = how many candidates the HNSW walk keeps. It must be at least
    # `limit` or the index can return fewer rows than asked for. evals/hnsw_recall.py
    # measured recall@10 = 0.985 at the default of 40 and 0.996 at 100, for +0.1 ms.
    conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(max(100, 2 * limit)),))
    # If WHERE clauses drop some index results, keep walking the graph rather
    # than returning fewer than `limit` rows (pgvector 0.8+).
    conn.execute("SELECT set_config('hnsw.iterative_scan', 'strict_order', true)")


def search_jobs(conn: psycopg.Connection, query_vector: np.ndarray, limit: int = 10) -> list[dict]:
    """The `limit` active jobs nearest to `query_vector`, most similar first."""
    with conn.transaction():  # the settings in tune_hnsw last only for this transaction
        tune_hnsw(conn, limit)
        return conn.execute(SEARCH_SQL, {"query": query_vector, "limit": limit}).fetchall()
