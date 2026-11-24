"""Load LinkedIn job postings (Kaggle: arshkon/linkedin-job-postings) into the jobs table.

    python -m matchwise.ingest --raw-dir data/raw --limit 5000 --seed 42

Pipeline: read postings.csv row by row -> normalise each row -> drop unusable
rows and exact duplicates -> sample `limit` rows with a fixed seed -> tag
skills -> insert new rows and update changed ones, keyed by source_id.
"""

import argparse
import csv
import hashlib
import json
import logging
import math
import random
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

import psycopg

from matchwise import db
from matchwise.skills import extract_skills

log = logging.getLogger(__name__)

csv.field_size_limit(10_000_000)  # some descriptions exceed the 128 KB default

MIN_DESCRIPTION_CHARS = 200  # shorter postings carry too little to match on

SENIORITY = {
    "Internship": "intern",
    "Entry level": "entry",
    "Associate": "associate",
    "Mid-Senior level": "mid_senior",
    "Director": "director",
    "Executive": "executive",
}

# Multiply a pay rate by this to get a yearly amount (2080 = 40 hours x 52 weeks).
PER_YEAR = {"HOURLY": 2080, "WEEKLY": 52, "BIWEEKLY": 26, "MONTHLY": 12, "YEARLY": 1}

# Yearly pay outside this range is almost always a mislabelled pay period
# ($18 "per year" that is really per hour). We drop it rather than guess.
PLAUSIBLE_YEARLY_SALARY = (10_000, 1_000_000)

REQUIRED_COLUMNS = {
    "job_id", "title", "description", "location", "remote_allowed",
    "formatted_experience_level", "formatted_work_type",
    "min_salary", "med_salary", "max_salary", "pay_period", "currency", "listed_time",
}

# Fields that make up a posting's content. Skills are left out because they are
# derived from the description; source_id is left out so reposts hash the same.
HASHED_FIELDS = (
    "title", "company", "location", "remote", "seniority", "employment_type",
    "functions", "industries", "description",
    "salary_min", "salary_max", "salary_currency", "posted_at",
)


@dataclass(frozen=True)
class Job:
    source_id: str
    title: str
    company: str | None
    location: str | None
    remote: bool
    seniority: str
    employment_type: str | None
    functions: tuple[str, ...]
    industries: tuple[str, ...]
    description: str
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    posted_at: datetime | None
    content_hash: str
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class Lookups:
    """Side tables from the dataset, keyed by LinkedIn ids."""
    functions: dict[str, tuple[str, ...]]   # job_id -> job function names
    industries: dict[str, tuple[str, ...]]  # job_id -> industry names
    companies: dict[str, str]               # company_id -> company name


# ---------- reading ----------

def read_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def read_postings(path: Path) -> Iterator[dict[str, str]]:
    """Rows of postings.csv. Fails early, with the columns found, if the layout is unexpected."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        found = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - found
        if missing or not found & {"company_name", "company_id"}:
            raise ValueError(
                f"{path} has an unexpected layout. Missing: {sorted(missing) or 'company_name/company_id'}. "
                f"Found: {sorted(found)}"
            )
        yield from reader


def load_lookups(raw_dir: Path) -> Lookups:
    skill_names = {r["skill_abr"]: r["skill_name"] for r in read_csv(raw_dir / "mappings/skills.csv")}
    industry_names = {
        clean_id(r["industry_id"]): r["industry_name"] for r in read_csv(raw_dir / "mappings/industries.csv")
    }
    companies_csv = raw_dir / "companies/companies.csv"
    companies = (
        {clean_id(r["company_id"]): r["name"].strip() for r in read_csv(companies_csv) if r["name"].strip()}
        if companies_csv.exists()
        else {}
    )
    return Lookups(
        functions=_group_names(read_csv(raw_dir / "jobs/job_skills.csv"), "skill_abr", skill_names),
        industries=_group_names(read_csv(raw_dir / "jobs/job_industries.csv"), "industry_id", industry_names),
        companies=companies,
    )


def _group_names(rows: Iterable[dict[str, str]], key: str, names: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """Turn (job_id, code) rows into job_id -> sorted names."""
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        name = names.get(clean_id(row[key]))
        if name:
            grouped[clean_id(row["job_id"])].add(name)
    return {job_id: tuple(sorted(found)) for job_id, found in grouped.items()}


# ---------- normalising ----------

def normalise(row: dict[str, str], lookups: Lookups) -> Job | None:
    """Turn one raw CSV row into a Job, or None if the row is unusable."""
    title = row["title"].strip()
    description = row["description"].strip()
    if not title or len(description) < MIN_DESCRIPTION_CHARS:
        return None

    job_id = clean_id(row["job_id"])
    salary_min, salary_max = annual_salary(row)
    company = (row.get("company_name") or "").strip() or lookups.companies.get(clean_id(row.get("company_id") or ""))
    fields = {
        "title": title,
        "company": company,
        "location": row["location"].strip() or None,
        "remote": _float(row["remote_allowed"]) == 1.0,
        "seniority": SENIORITY.get(row["formatted_experience_level"].strip(), "unknown"),
        "employment_type": row["formatted_work_type"].strip() or None,
        "functions": lookups.functions.get(job_id, ()),
        "industries": lookups.industries.get(job_id, ()),
        "description": description,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": (row["currency"].strip() or None) if salary_min is not None else None,
        "posted_at": _from_epoch_ms(row["listed_time"]),
    }
    return Job(source_id=job_id, content_hash=compute_content_hash(fields), **fields)


def annual_salary(row: dict[str, str]) -> tuple[int | None, int | None]:
    """(min, max) per year in whole units, or (None, None) if missing or implausible.

    A posting with only a median gets min = max = median.
    """
    per_year = PER_YEAR.get(row["pay_period"].strip().upper())
    median = _float(row["med_salary"])
    low = _float(row["min_salary"]) or median
    high = _float(row["max_salary"]) or median or low
    if per_year is None or low is None:
        return None, None
    yearly_low, yearly_high = round(low * per_year), round(high * per_year)
    floor, ceiling = PLAUSIBLE_YEARLY_SALARY
    if not floor <= yearly_low <= yearly_high <= ceiling:
        return None, None
    return yearly_low, yearly_high


def compute_content_hash(fields: dict) -> str:
    """sha256 of the hashed fields. Whitespace is collapsed first, so re-flowed
    text with the same words does not count as a change."""
    canonical = {}
    for name in HASHED_FIELDS:
        value = fields[name]
        if isinstance(value, str):
            value = " ".join(value.split())
        elif isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, tuple):
            value = list(value)
        canonical[name] = value
    payload = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def with_skills(job: Job) -> Job:
    return replace(job, skills=tuple(extract_skills(f"{job.title}\n{job.description}")))


def clean_id(value: str) -> str:
    """LinkedIn ids sometimes arrive as floats ('2774458.0'); keep them as plain strings."""
    return value.strip().removesuffix(".0")


def _float(value: str | None) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _from_epoch_ms(value: str) -> datetime | None:
    ms = _float(value)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else None


# ---------- selecting ----------

def unique_jobs(rows: Iterable[dict[str, str]], lookups: Lookups, stats: Counter) -> Iterator[Job]:
    """Normalised jobs, skipping unusable rows and exact duplicates (same content_hash)."""
    seen: set[str] = set()
    for row in rows:
        stats["read"] += 1
        job = normalise(row, lookups)
        if job is None:
            stats["unusable"] += 1
        elif job.content_hash in seen:
            stats["duplicates"] += 1
        else:
            seen.add(job.content_hash)
            yield job


T = TypeVar("T")


def reservoir_sample(items: Iterable[T], k: int, seed: int) -> list[T]:
    """k items chosen uniformly at random in one pass, holding only k in memory.

    The same seed over the same input always gives the same sample.
    """
    rng = random.Random(seed)
    sample: list[T] = []
    for i, item in enumerate(items):
        if i < k:
            sample.append(item)
        else:
            j = rng.randint(0, i)  # item i survives with probability k / (i + 1)
            if j < k:
                sample[j] = item
    return sample


# ---------- writing ----------

INSERT_SQL = """
INSERT INTO jobs (
    source_id, title, company, location, remote, seniority, employment_type,
    functions, industries, skills, description,
    salary_min, salary_max, salary_currency, posted_at, content_hash
) VALUES (
    %(source_id)s, %(title)s, %(company)s, %(location)s, %(remote)s, %(seniority)s, %(employment_type)s,
    %(functions)s, %(industries)s, %(skills)s, %(description)s,
    %(salary_min)s, %(salary_max)s, %(salary_currency)s, %(posted_at)s, %(content_hash)s
)
"""

UPDATE_SQL = """
UPDATE jobs SET
    title = %(title)s, company = %(company)s, location = %(location)s, remote = %(remote)s,
    seniority = %(seniority)s, employment_type = %(employment_type)s,
    functions = %(functions)s, industries = %(industries)s, skills = %(skills)s,
    description = %(description)s, salary_min = %(salary_min)s, salary_max = %(salary_max)s,
    salary_currency = %(salary_currency)s, posted_at = %(posted_at)s, content_hash = %(content_hash)s,
    is_active = true, removed_at = NULL, last_seen_at = now()
WHERE source_id = %(source_id)s
"""


def upsert_jobs(conn: psycopg.Connection, jobs: list[Job]) -> dict[str, int]:
    """Insert new jobs and update changed ones. Returns counts.

    A job counts as changed if its content_hash differs, or if its derived skills
    differ (so improving the skills tagger reaches rows that are already loaded).
    """
    with conn.transaction():
        rows = conn.execute(
            "SELECT source_id, content_hash, skills FROM jobs WHERE source_id = ANY(%s)",
            ([j.source_id for j in jobs],),
        )
        existing = {r["source_id"]: (r["content_hash"], tuple(r["skills"])) for r in rows}
        new = [j for j in jobs if j.source_id not in existing]
        changed = [
            j for j in jobs
            if j.source_id in existing and existing[j.source_id] != (j.content_hash, j.skills)
        ]
        with conn.cursor() as cur:
            if new:
                cur.executemany(INSERT_SQL, [job_params(j) for j in new])
            if changed:
                cur.executemany(UPDATE_SQL, [job_params(j) for j in changed])
    return {"inserted": len(new), "updated": len(changed), "unchanged": len(jobs) - len(new) - len(changed)}


def job_params(job: Job) -> dict:
    params = asdict(job)
    for name in ("functions", "industries", "skills"):
        params[name] = list(params[name])  # Postgres arrays come from lists, not tuples
    return params


# ---------- entry point ----------

def run(raw_dir: Path, limit: int, seed: int, database_url: str) -> dict[str, int]:
    started = time.perf_counter()
    db.migrate(database_url)
    lookups = load_lookups(raw_dir)
    stats: Counter = Counter()
    sample = reservoir_sample(unique_jobs(read_postings(raw_dir / "postings.csv"), lookups, stats), limit, seed)
    sample = [with_skills(job) for job in sample]
    with db.connect(database_url) as conn:
        counts = upsert_jobs(conn, sample)
    result = {**stats, "sampled": len(sample), **counts, "seconds": round(time.perf_counter() - started, 1)}
    log.info("ingest done %s", result)
    return result


def main() -> None:
    from matchwise.config import get_settings, setup_logging

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)
    run(args.raw_dir, args.limit, args.seed, settings.database_url)


if __name__ == "__main__":
    main()
