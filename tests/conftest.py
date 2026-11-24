import csv
import hashlib
import os
from pathlib import Path

import numpy as np
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from psycopg.types.json import Jsonb

from matchwise import db, ingest
from matchwise.ingest import Lookups
from matchwise.llm import Completion, LLMClient
from matchwise.preferences import Dealbreakers, Preferences, Wants

LONG_TEXT = (
    "You will join a small team and own your work end to end, from first design to running it in "
    "production. We value clear writing, careful reviews and steady delivery over heroics. "
)


def raw_posting(**overrides: str) -> dict[str, str]:
    """A valid postings.csv row (only the columns the loader reads), with overrides."""
    row = {
        "job_id": "1001",
        "company_name": "Acme Corp",
        "company_id": "",
        "title": "Backend Engineer",
        "description": "Build REST APIs in Python on PostgreSQL and Docker. " + LONG_TEXT,
        "location": "Austin, TX",
        "remote_allowed": "1.0",
        "formatted_experience_level": "Mid-Senior level",
        "formatted_work_type": "Full-time",
        "min_salary": "120000.0",
        "med_salary": "",
        "max_salary": "150000.0",
        "pay_period": "YEARLY",
        "currency": "USD",
        "listed_time": "1713397508000.0",
    }
    row.update(overrides)
    return row


@pytest.fixture
def no_lookups() -> Lookups:
    return Lookups(functions={}, industries={}, companies={})


def fake_embed(texts) -> np.ndarray:
    """Stand-in for MiniLM: a random unit vector seeded by the text, so the same text
    always gets the same vector. Fast and offline, but carries no meaning."""
    vectors = []
    for text in texts:
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).normal(size=384).astype(np.float32)
        vectors.append(v / np.linalg.norm(v))
    return np.stack(vectors)


class ScriptedTransport:
    """Stand-in for the LLM API: returns canned replies in order and records what it was sent."""

    model = "scripted"

    def __init__(self, replies: list[str], on_call=None):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []
        self.on_call = on_call  # lets a test do something "while the LLM is thinking"

    def complete(self, messages):
        self.calls.append([dict(m) for m in messages])  # copy: the client appends to its list later
        if self.on_call:
            self.on_call()
        return Completion(text=self.replies.pop(0), input_tokens=100, output_tokens=20)


def scripted_llm(*replies: str, on_call=None) -> LLMClient:
    return LLMClient(ScriptedTransport(list(replies), on_call=on_call))


def unit_vector(*hot: int) -> np.ndarray:
    """A 384-d unit vector with equal weight on the given dimensions."""
    v = np.zeros(384, dtype=np.float32)
    v[list(hot)] = 1.0
    return v / np.linalg.norm(v)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    """A six-row copy of the Kaggle layout: 3 usable postings, 1 duplicate, 2 unusable."""
    postings = [
        raw_posting(),
        raw_posting(
            job_id="1002", company_name="", company_id="55.0", title="Registered Nurse",
            description="Provide patient care in our ICU. BLS and ACLS required. " + LONG_TEXT,
            location="Denver, CO", remote_allowed="", formatted_experience_level="Entry level",
            min_salary="40.0", max_salary="50.0", pay_period="HOURLY",
        ),
        raw_posting(job_id="1003", title="Sales Associate", description="Sell things."),  # too short
        raw_posting(job_id="1004"),  # same content as 1001 under another id
        raw_posting(
            job_id="1005", title="Data Analyst",
            description="Report on sales with SQL, Tableau and Excel. " + LONG_TEXT,
            location="New York, NY", remote_allowed="", formatted_experience_level="Associate",
            formatted_work_type="Contract", min_salary="", max_salary="", pay_period="", currency="",
        ),
        raw_posting(job_id="1006", title=""),  # no title
    ]
    root = tmp_path / "raw"
    _write_csv(root / "postings.csv", postings)
    _write_csv(root / "mappings/skills.csv", [
        {"skill_abr": "IT", "skill_name": "Information Technology"},
        {"skill_abr": "ENG", "skill_name": "Engineering"},
        {"skill_abr": "HCPR", "skill_name": "Health Care Provider"},
    ])
    _write_csv(root / "jobs/job_skills.csv", [
        {"job_id": "1001", "skill_abr": "IT"},
        {"job_id": "1001", "skill_abr": "ENG"},
        {"job_id": "1002", "skill_abr": "HCPR"},
        {"job_id": "1004", "skill_abr": "ENG"},  # 1004 is a repost of 1001: same side-table rows
        {"job_id": "1004", "skill_abr": "IT"},
    ])
    _write_csv(root / "mappings/industries.csv", [
        {"industry_id": "4", "industry_name": "Software Development"},
        {"industry_id": "14", "industry_name": "Hospitals and Health Care"},
    ])
    _write_csv(root / "jobs/job_industries.csv", [
        {"job_id": "1001", "industry_id": "4"},
        {"job_id": "1002", "industry_id": "14"},
        {"job_id": "1004", "industry_id": "4"},
    ])
    _write_csv(root / "companies/companies.csv", [{"company_id": "55", "name": "Mercy Health"}])
    return root


# ---------- a small catalogue of jobs, shared by the ranking, reasons, agent and eval tests ----------

JOBS = {
    # source_id: (title, location, raw overrides, functions, skills, company, vector dims)
    "be": ("Backend Engineer", "Austin, TX", {}, ["Engineering"], ["python", "postgresql"], "Acme Corp", (0,)),
    "sales": ("Sales Development Rep", "Austin, TX", {"formatted_experience_level": "Entry level"},
              ["Sales"], [], "Acme Corp", (0, 1)),
    "wholesale": ("Wholesale Buyer", "Austin, TX", {}, ["Purchasing"], [], "Shop Co", (1,)),
    "night": ("ICU Nurse", "Houston, TX", {"description": "Night shifts in our ICU. " + LONG_TEXT},
              ["Health Care Provider"], [], "HCA Houston Healthcare", (2,)),
    "remote": ("Data Engineer", "United States",
               {"remote_allowed": "1.0", "formatted_work_type": "Contract", "min_salary": "", "max_salary": ""},
               ["Engineering"], ["python"], "Data Co", (0, 2)),
    "dallas_or": ("Backend Engineer", "Dallas, OR", {}, ["Engineering"], ["python"], "Oregon Co", (0, 3)),
    "lowpay": ("Junior Developer", "Dallas, TX",
               {"min_salary": "40000", "max_salary": "50000", "formatted_experience_level": "Entry level"},
               ["Engineering"], ["python"], "Small Co", (0, 4)),
    "intern": ("Software Intern", "Austin, TX", {"formatted_experience_level": "Internship"},
               ["Engineering"], ["python"], "Acme Corp", (0, 5)),
}

BACKEND_NEVER_SALES = Preferences(
    wants=Wants(roles=["backend engineer"], skills=["python", "postgresql"], locations=["Austin, TX"],
                seniority=["mid_senior"]),
    dealbreakers=Dealbreakers(exclude_title_words=["sales"], exclude_functions=["Sales"]),
)


def same_vector(texts) -> np.ndarray:
    """An embedder that maps every text to the same vector, so job vectors alone decide similarity."""
    return np.stack([unit_vector(0)] * len(texts))


def save_profile(conn, profile_id: str, prefs: Preferences) -> None:
    conn.execute("INSERT INTO profiles (id, preferences, version) VALUES (%s, %s, 1)",
                 (profile_id, Jsonb(prefs.model_dump())))


@pytest.fixture
def catalog(conn):
    """The JOBS above, loaded with hand-set vectors (pointing along the listed dimensions)."""
    for sid, (title, location, overrides, functions, skills, company, dims) in JOBS.items():
        raw = raw_posting(job_id=sid, title=title, location=location, company_name=company,
                          **{"remote_allowed": "", **overrides})
        ingest.upsert_jobs(conn, [ingest.normalise(raw, Lookups({}, {}, {}))])
        conn.execute("UPDATE jobs SET functions = %s, skills = %s, embedding = %s WHERE source_id = %s",
                     (functions, skills, unit_vector(*dims), sid))
    return conn


# ---------- database ----------

@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set (run tests inside docker compose)")
    name = conninfo_to_dict(url)["dbname"]
    if not name.endswith("_test"):
        # These tests TRUNCATE tables; refuse to touch anything that isn't a test database.
        pytest.exit(f"TEST_DATABASE_URL must point at a *_test database, got {name!r}")
    with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as admin:
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    db.migrate(url)
    return url


@pytest.fixture
def conn(db_url: str):
    """A connection to an empty test database."""
    with db.connect(db_url) as conn:
        conn.execute(
            "TRUNCATE jobs, profiles, profile_messages, reasons_cache, refresh_runs, chat_messages RESTART IDENTITY")
        yield conn


@pytest.fixture(autouse=True)
def no_real_llm(request, monkeypatch):
    """Offline tests must never reach the real LLM, even when .env has a key.
    Only tests marked `live` keep it."""
    if "live" not in request.keywords:
        monkeypatch.setenv("LLM_API_KEY", "")
