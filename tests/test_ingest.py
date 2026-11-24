from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone

import pytest

from conftest import raw_posting
from matchwise import ingest
from matchwise.ingest import HASHED_FIELDS, compute_content_hash, normalise, reservoir_sample


def _hash_with(**changes) -> str:
    job = normalise(raw_posting(), ingest.Lookups({}, {}, {}))
    fields = {name: getattr(job, name) for name in HASHED_FIELDS}
    return compute_content_hash({**fields, **changes})


def test_normalise_maps_the_raw_fields(no_lookups):
    job = normalise(raw_posting(), no_lookups)
    assert job.source_id == "1001"
    assert job.company == "Acme Corp"
    assert job.remote is True
    assert job.seniority == "mid_senior"
    assert (job.salary_min, job.salary_max, job.salary_currency) == (120000, 150000, "USD")
    assert job.posted_at == datetime.fromtimestamp(1713397508, tz=timezone.utc)


def test_hourly_pay_is_annualised(no_lookups):
    job = normalise(raw_posting(min_salary="40", max_salary="50", pay_period="HOURLY"), no_lookups)
    assert (job.salary_min, job.salary_max) == (40 * 2080, 50 * 2080)


def test_median_only_salary_becomes_min_and_max(no_lookups):
    job = normalise(raw_posting(min_salary="", max_salary="", med_salary="5000", pay_period="MONTHLY"), no_lookups)
    assert (job.salary_min, job.salary_max) == (60000, 60000)


@pytest.mark.parametrize(
    "pay",
    [
        {"min_salary": "18", "max_salary": "21", "pay_period": "YEARLY"},     # really hourly
        {"min_salary": "900", "max_salary": "950", "pay_period": "HOURLY"},   # really yearly-ish
        {"min_salary": "0", "max_salary": "", "med_salary": "0", "pay_period": "YEARLY"},
        {"min_salary": "90000", "max_salary": "80000", "pay_period": "YEARLY"},  # max below min
    ],
)
def test_implausible_salaries_are_dropped(no_lookups, pay):
    job = normalise(raw_posting(**pay), no_lookups)
    assert (job.salary_min, job.salary_max, job.salary_currency) == (None, None, None)


def test_missing_values_become_none_or_unknown(no_lookups):
    job = normalise(
        raw_posting(remote_allowed="", formatted_experience_level="", min_salary="", max_salary="", pay_period=""),
        no_lookups,
    )
    assert job.remote is False
    assert job.seniority == "unknown"
    assert (job.salary_min, job.salary_max, job.salary_currency) == (None, None, None)


@pytest.mark.parametrize("override", [{"title": "  "}, {"description": "Too short."}])
def test_unusable_rows_are_dropped(no_lookups, override):
    assert normalise(raw_posting(**override), no_lookups) is None


def test_content_hash_ignores_whitespace_but_not_content():
    original = _hash_with()
    assert _hash_with(title="Backend   Engineer ") == original
    assert _hash_with(title="Frontend Engineer") != original
    assert _hash_with(salary_max=160000) != original


def test_reservoir_sample_is_deterministic_and_exact_size():
    first = reservoir_sample(range(10_000), k=50, seed=7)
    assert first == reservoir_sample(range(10_000), k=50, seed=7)
    assert len(first) == len(set(first)) == 50
    assert first != reservoir_sample(range(10_000), k=50, seed=8)


def test_reservoir_sample_is_roughly_uniform():
    # Each of 20 items should be picked about k/n = 25% of the time.
    picks = Counter(x for seed in range(2000) for x in reservoir_sample(range(20), k=5, seed=seed))
    assert all(400 < picks[x] < 600 for x in range(20))


def test_fixture_dataset_end_to_end(raw_dir):
    lookups = ingest.load_lookups(raw_dir)
    stats = Counter()
    jobs = list(ingest.unique_jobs(ingest.read_postings(raw_dir / "postings.csv"), lookups, stats))
    assert stats == Counter(read=6, unusable=2, duplicates=1)
    by_id = {j.source_id: ingest.with_skills(j) for j in jobs}
    assert set(by_id) == {"1001", "1002", "1005"}
    assert by_id["1001"].functions == ("Engineering", "Information Technology")
    assert by_id["1001"].industries == ("Software Development",)
    assert by_id["1001"].skills == ("docker", "postgresql", "python", "rest api")
    assert by_id["1002"].company == "Mercy Health"  # resolved through companies.csv
    assert by_id["1002"].skills == ("acls", "basic life support", "icu", "patient care", "registered nurse")


def test_unexpected_csv_layout_fails_with_a_clear_message(tmp_path):
    path = tmp_path / "postings.csv"
    path.write_text("id,name\n1,x\n")
    with pytest.raises(ValueError, match="unexpected layout"):
        next(ingest.read_postings(path))


# ---------- database ----------

def _sample_jobs(raw_dir):
    lookups = ingest.load_lookups(raw_dir)
    rows = ingest.read_postings(raw_dir / "postings.csv")
    return [ingest.with_skills(j) for j in ingest.unique_jobs(rows, lookups, Counter())]


def test_upsert_inserts_then_skips_unchanged_then_updates_changed(conn, raw_dir):
    jobs = _sample_jobs(raw_dir)
    assert ingest.upsert_jobs(conn, jobs) == {"inserted": 3, "updated": 0, "unchanged": 0}
    assert ingest.upsert_jobs(conn, jobs) == {"inserted": 0, "updated": 0, "unchanged": 3}

    edited = ingest.with_skills(normalise(raw_posting(title="Senior Backend Engineer"), ingest.load_lookups(raw_dir)))
    assert ingest.upsert_jobs(conn, [edited]) == {"inserted": 0, "updated": 1, "unchanged": 0}
    row = conn.execute("SELECT title, content_hash FROM jobs WHERE source_id = '1001'").fetchone()
    assert row == {"title": "Senior Backend Engineer", "content_hash": edited.content_hash}


def test_retagged_skills_count_as_a_change(conn, raw_dir):
    job = _sample_jobs(raw_dir)[0]
    ingest.upsert_jobs(conn, [job])
    retagged = replace(job, skills=job.skills + ("kubernetes",))  # same content_hash
    assert ingest.upsert_jobs(conn, [retagged]) == {"inserted": 0, "updated": 1, "unchanged": 0}


def test_stored_row_round_trips(conn, raw_dir):
    job = next(j for j in _sample_jobs(raw_dir) if j.source_id == "1002")
    ingest.upsert_jobs(conn, [job])
    row = conn.execute("SELECT * FROM jobs WHERE source_id = '1002'").fetchone()
    expected = asdict(job)
    for name in ("functions", "industries", "skills"):
        expected[name] = list(expected[name])
    assert {k: row[k] for k in expected} == expected
    assert row["is_active"] is True and row["embedding"] is None


def test_ingest_run_loads_a_sample(db_url, conn, raw_dir):
    result = ingest.run(raw_dir, limit=2, seed=1, database_url=db_url)
    assert result["sampled"] == 2 and result["inserted"] == 2
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 2
