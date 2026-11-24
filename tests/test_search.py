import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import fake_embed, raw_posting, unit_vector
from matchwise import ingest
from matchwise.api import app, get_embedder
from matchwise.search import search_jobs


@pytest.fixture
def three_jobs(conn):
    """Jobs pointing along dimension 0, halfway between 0 and 1, and along 1."""
    jobs = [ingest.normalise(raw_posting(job_id=i, title=t), ingest.Lookups({}, {}, {}))
            for i, t in [("a", "Along 0"), ("b", "Between"), ("c", "Along 1")]]
    ingest.upsert_jobs(conn, jobs)
    for source_id, vector in [("a", unit_vector(0)), ("b", unit_vector(0, 1)), ("c", unit_vector(1))]:
        conn.execute("UPDATE jobs SET embedding = %s WHERE source_id = %s", (vector, source_id))
    return conn


def test_results_come_back_nearest_first(three_jobs):
    results = search_jobs(three_jobs, unit_vector(0), limit=3)
    assert [r["title"] for r in results] == ["Along 0", "Between", "Along 1"]
    assert [round(r["similarity"], 3) for r in results] == [1.0, 0.707, 0.0]


def test_limit_and_inactive_jobs(three_jobs):
    three_jobs.execute("UPDATE jobs SET is_active = false WHERE source_id = 'a'")
    results = search_jobs(three_jobs, unit_vector(0), limit=1)
    assert [r["title"] for r in results] == ["Between"]


def test_snippet_of_long_non_ascii_description(conn):
    """Regression test. PostgreSQL 16.12 raised 'invalid byte sequence for encoding UTF8'
    from left() on some compressed non-ASCII text (fixed in 16.13). This synthetic text
    copies the layout of a real posting that triggered it: two curly quotes in filler."""
    filler = "lorem ipsum dolor sit amet consectetur adipiscing elit "
    chars = [filler[i % len(filler)] for i in range(4855)]
    chars[828] = chars[960] = "’"
    job = ingest.normalise(raw_posting(job_id="utf8", description="".join(chars)), ingest.Lookups({}, {}, {}))
    ingest.upsert_jobs(conn, [job])
    conn.execute("UPDATE jobs SET embedding = %s", (unit_vector(0),))
    [result] = search_jobs(conn, unit_vector(0), limit=1)
    assert len(result["snippet"]) == 240


def test_jobs_without_embeddings_are_skipped(three_jobs):
    three_jobs.execute("UPDATE jobs SET embedding = NULL WHERE source_id = 'b'")
    assert [r["title"] for r in search_jobs(three_jobs, unit_vector(0), limit=3)] == ["Along 0", "Along 1"]


@pytest.fixture
def client(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    app.dependency_overrides[get_embedder] = lambda: lambda texts: np.stack([unit_vector(0)] * len(texts))
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_search_endpoint(three_jobs, client):
    response = client.get("/search", params={"q": "anything", "limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert [r["title"] for r in body] == ["Along 0", "Between"]
    assert set(body[0]) == {"id", "title", "company", "location", "remote", "seniority", "skills", "snippet", "similarity"}


@pytest.mark.parametrize("params", [{"q": "x"}, {"q": "python", "limit": 0}, {"q": "python", "limit": 51}, {}])
def test_search_rejects_bad_input(client, params):
    assert client.get("/search", params=params).status_code == 422


def test_fake_embedder_is_deterministic():
    np.testing.assert_array_equal(fake_embed(["a", "b"]), fake_embed(["a", "b"]))
