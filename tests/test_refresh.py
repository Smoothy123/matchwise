from dataclasses import replace

import pytest

from conftest import fake_embed, raw_posting
from matchwise import embeddings, ingest
from matchwise.refresh import (
    ChurnPlan, SuspiciousSnapshot, apply_snapshot, current_jobs, edit, read_snapshot, rehash, run_refresh,
    simulate, write_snapshot,
)

LOOKUPS = ingest.Lookups({}, {}, {})


def make_jobs(n: int) -> list[ingest.Job]:
    return [ingest.with_skills(ingest.normalise(raw_posting(job_id=str(i), title=f"Python Developer {i}"), LOOKUPS))
            for i in range(n)]


@pytest.fixture
def loaded(conn):
    """20 active, embedded jobs."""
    jobs = make_jobs(20)
    ingest.upsert_jobs(conn, jobs)
    embeddings.embed_pending(conn, embed=fake_embed)
    return conn, jobs


def counts(conn) -> dict:
    return conn.execute(
        "SELECT count(*) FILTER (WHERE is_active) AS active, count(*) FILTER (WHERE NOT is_active) AS removed FROM jobs"
    ).fetchone()


# ---------- applying snapshots ----------

def test_applying_todays_snapshot_again_changes_nothing(loaded):
    conn, jobs = loaded
    assert apply_snapshot(conn, jobs) == {
        "snapshot_size": 20, "added": 0, "updated": 0, "reactivated": 0, "removed": 0, "unchanged": 20}


def test_add_update_remove_in_one_snapshot(loaded):
    conn, jobs = loaded
    snapshot = jobs[2:]                                        # 0 and 1 disappear
    snapshot[0] = edit(snapshot[0], "title")                   # job 2 changes
    snapshot.append(make_jobs(21)[20])                         # job 20 is new
    result = apply_snapshot(conn, snapshot)
    assert result == {"snapshot_size": 19, "added": 1, "updated": 1, "reactivated": 0, "removed": 2, "unchanged": 17}
    assert counts(conn) == {"active": 19, "removed": 2}
    gone = conn.execute("SELECT removed_at FROM jobs WHERE source_id = '0'").fetchone()
    assert gone["removed_at"] is not None                      # soft delete: the row is still there
    title = conn.execute("SELECT title FROM jobs WHERE source_id = '2'").fetchone()["title"]
    assert title == "Senior Python Developer 2"


def test_a_removed_job_that_returns_is_reactivated(loaded):
    conn, jobs = loaded
    apply_snapshot(conn, jobs[1:])
    result = apply_snapshot(conn, jobs)
    assert (result["reactivated"], result["unchanged"], result["removed"]) == (1, 19, 0)
    assert conn.execute("SELECT is_active, removed_at FROM jobs WHERE source_id = '0'").fetchone() == {
        "is_active": True, "removed_at": None}


def test_a_snapshot_that_would_wipe_the_catalogue_is_refused(loaded):
    conn, jobs = loaded
    with pytest.raises(SuspiciousSnapshot, match="would remove 15 of 20"):
        apply_snapshot(conn, jobs[:5])
    assert counts(conn) == {"active": 20, "removed": 0}        # nothing changed
    assert apply_snapshot(conn, jobs[:5], max_removed_fraction=1.0)["removed"] == 15  # --force


# ---------- only changed text is re-embedded ----------

@pytest.mark.parametrize("kind, re_embedded", [
    ("title", 1),             # in the embedded card
    ("remote", 1),            # in the card ("Remote")
    ("salary", 0),            # not in the card
    ("description_tail", 0),  # past the part of the description we embed
])
def test_only_edits_to_the_embedded_text_trigger_re_embedding(loaded, kind, re_embedded):
    conn, jobs = loaded
    # Give every job a description longer than the part we embed, so a tail edit lands past the cut.
    long_jobs = [rehash(replace(j, description=j.description + " filler" * 200)) for j in jobs]
    apply_snapshot(conn, long_jobs)
    embeddings.embed_pending(conn, embed=fake_embed)

    snapshot = list(long_jobs)
    snapshot[0] = edit(snapshot[0], kind)
    result = run_refresh(conn, snapshot, "test", embed=fake_embed)
    assert result["updated"] == 1                      # the content changed either way
    assert result["embedded"] == re_embedded


def test_new_jobs_are_embedded_and_runs_are_logged(loaded):
    conn, jobs = loaded
    result = run_refresh(conn, jobs[1:] + make_jobs(22)[20:], "day-x.jsonl", embed=fake_embed)
    assert (result["added"], result["removed"], result["embedded"]) == (2, 1, 2)
    run = conn.execute("SELECT * FROM refresh_runs WHERE id = %s", (result["run_id"],)).fetchone()
    assert (run["snapshot"], run["status"], run["added"], run["embedded"]) == ("day-x.jsonl", "ok", 2, 2)
    assert run["total_ms"] >= run["apply_ms"] and run["finished_at"] is not None


def test_a_failed_run_is_logged_as_failed(loaded):
    conn, jobs = loaded
    with pytest.raises(SuspiciousSnapshot):
        run_refresh(conn, jobs[:1], "broken.jsonl", embed=fake_embed)
    run = conn.execute("SELECT status, error FROM refresh_runs").fetchone()
    assert run["status"] == "failed" and "SuspiciousSnapshot" in run["error"]


def test_stale_cached_reasons_are_pruned(loaded):
    conn, jobs = loaded
    conn.execute("""INSERT INTO reasons_cache (cache_key, content_hash, prefs_hash, prompt_version, model, reason)
                    VALUES ('k0', %s, 'p', 'v', 'm', '{}'), ('k1', %s, 'p', 'v', 'm', '{}')""",
                 (jobs[0].content_hash, jobs[1].content_hash))
    result = run_refresh(conn, jobs[1:], "day", embed=fake_embed)   # job 0 removed
    assert result["reasons_pruned"] == 1
    assert [r["cache_key"] for r in conn.execute("SELECT cache_key FROM reasons_cache")] == ["k1"]


# ---------- simulating churn ----------

def test_simulation_is_deterministic_and_does_what_the_plan_says(loaded, raw_dir):
    conn, _ = loaded
    plan = ChurnPlan(seed=3, add=2, edit_fraction=0.25, remove_fraction=0.1)
    snapshot, summary = simulate(conn, raw_dir, plan)
    again, _ = simulate(conn, raw_dir, plan)
    assert snapshot == again
    assert (summary["removed"], summary["kept"], summary["added"]) == (2, 18, 2)
    assert sum(summary["edited"].values()) == round(18 * 0.25)

    today = {j.source_id: j for j in current_jobs(conn)}
    new = [j for j in snapshot if j.source_id not in today]
    assert {j.source_id for j in new} <= {"1002", "1005"}       # unseen postings from the raw CSV
    assert all(j.posted_at > max(t.posted_at for t in today.values()) for j in new)
    changed = [j for j in snapshot if j.source_id in today and j != today[j.source_id]]
    assert len(changed) == sum(summary["edited"].values())
    assert all(j.content_hash != today[j.source_id].content_hash for j in changed)


def test_snapshot_files_round_trip(tmp_path):
    jobs = make_jobs(3)
    path = tmp_path / "day.jsonl"
    assert write_snapshot(path, jobs) == 3
    assert list(read_snapshot(path)) == jobs


@pytest.mark.parametrize("kind", ["title", "salary", "remote", "description_tail"])
def test_every_edit_changes_the_content_hash(kind):
    job = make_jobs(1)[0]
    assert edit(job, kind).content_hash != job.content_hash


def test_title_edit_toggles_senior():
    job = make_jobs(1)[0]
    assert edit(edit(job, "title"), "title").title == job.title
