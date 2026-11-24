from fastapi.testclient import TestClient

from conftest import raw_posting
from matchwise import db, ingest
from matchwise.api import app


def test_migrate_is_idempotent(db_url):
    assert db.migrate(db_url) == []  # the session fixture already applied everything
    with db.connect(db_url) as conn:
        names = [r["name"] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names == ["001_init.sql", "002_hnsw_index.sql", "003_update_vector_extension.sql", "004_profiles.sql",
                     "005_reasons_cache.sql", "006_refresh_runs.sql", "007_chat_messages.sql",
                     "008_limit_checks.sql"]


def test_health_reports_job_counts(db_url, conn, monkeypatch, no_lookups):
    ingest.upsert_jobs(conn, [ingest.normalise(raw_posting(), no_lookups)])
    monkeypatch.setenv("DATABASE_URL", db_url)
    with TestClient(app) as client:  # `with` runs the startup (migrate + pool)
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ("status", "jobs", "active_jobs", "embedded_jobs")} == {
        "status": "ok", "jobs": 1, "active_jobs": 1, "embedded_jobs": 0}
