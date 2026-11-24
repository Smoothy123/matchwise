"""Two-stage matching: retrieve broadly by meaning, then rank carefully with transparent features.

Stage 1, retrieve: embed the person's *wants* and take the CANDIDATES nearest
active postings that pass every dealbreaker. The dealbreakers are WHERE clauses
in the same SQL query as the vector search. They are never part of the query
text, because embeddings don't understand negation ("not sales" lands next to
sales jobs, as Phase 2 showed).

Stage 2, re-rank: score each candidate with a weighted sum of simple features,
each between 0 and 1: similarity, skills overlap, location fit, seniority fit,
salary fit, recency. Every feature is returned with the match, so each rank
can be explained. A feature the person hasn't expressed a view on (no skills
given, say) is left out and the other weights are rescaled.

Modes (compared in the Phase 7 evals):
  vector           nearest by similarity only, no filters, no re-ranking
  vector_filters   dealbreaker filters, ranked by similarity
  full             filters + feature re-ranking
  checked          full, then an LLM checks the top jobs against the hard limits and drops
                   any that break one (limit_check.py): for limits the filters can't see
"""

import logging
import math
import time
from datetime import datetime
from enum import Enum

import numpy as np
import psycopg

from matchwise import limit_check
from matchwise.embeddings import SENIORITY_LABELS, Embedder
from matchwise.filters import dealbreaker_sql
from matchwise.llm import LLMClient
from matchwise.places import location_matches, parse_place
from matchwise.preferences import Preferences, Wants
from matchwise.search import tune_hnsw
from matchwise.skills import load_vocabulary

log = logging.getLogger(__name__)

CANDIDATES = 200

# Hand-set from reasoning, not fitted: meaning matters most, then the concrete
# things people state (skills, place, level), with pay and freshness as tie-breakers.
WEIGHTS = {
    "similarity": 0.45,
    "skills": 0.20,
    "location": 0.15,
    "seniority": 0.10,
    "salary": 0.05,
    "recency": 0.05,
}

SENIORITY_ORDER = ["intern", "entry", "associate", "mid_senior", "director", "executive"]
RECENCY_HALF_LIFE_DAYS = 7


class Mode(str, Enum):
    vector = "vector"
    vector_filters = "vector_filters"
    full = "full"
    checked = "checked"


class NoWants(Exception):
    """The profile has only dealbreakers, so there is nothing to search for yet."""


class LimitCheckUnavailable(Exception):
    """Mode.checked needs an LLM, and none is configured."""


# ---------- stage 1: retrieve ----------

# How much the extras ("day shifts", "small team") move the query vector. Measured on the
# ICU-nurse profile: embedded together with the role, "day shifts. sign-on bonus" dropped the
# best match's cosine from 0.64 to 0.54 and pulled in non-nursing shift jobs.
EXTRAS_WEIGHT = 0.3


def core_text(wants: Wants) -> str:
    """What kind of job, at what level, where. Mirrors the job card's layout; never includes dealbreakers."""
    facts = [
        ", ".join(SENIORITY_LABELS[s] for s in wants.seniority),
        ", ".join(wants.locations),
        "Remote" if wants.remote else "",
    ]
    lines = [
        " / ".join(wants.roles),
        " · ".join(f for f in facts if f),
        "Skills: " + ", ".join(wants.skills) if wants.skills else "",
        "Industries: " + ", ".join(wants.industries) if wants.industries else "",
    ]
    return "\n".join(line for line in lines if line)


def query_vector(wants: Wants, embed: Embedder) -> np.ndarray:
    """core + EXTRAS_WEIGHT x extras, normalised: the extras nudge the search, the core steers it."""
    core, extras = core_text(wants), ". ".join(wants.other)
    texts = [t for t in (core, extras) if t]
    if not texts:
        raise NoWants("Tell me what you're looking for first (a role, skills or a place).")
    vectors = embed(texts)
    vector = vectors[0] + EXTRAS_WEIGHT * vectors[1] if len(texts) == 2 else vectors[0]
    return vector / np.linalg.norm(vector)


CANDIDATES_SQL = """
SELECT id, source_id, title, company, location, remote, seniority, employment_type, skills,
       salary_min, salary_max, posted_at,
       1 - (embedding <=> %(query)s) AS similarity
FROM jobs
WHERE {where}
ORDER BY embedding <=> %(query)s
LIMIT %(limit)s
"""


def retrieve(conn: psycopg.Connection, query_vector, clauses: list[str], params: dict, limit: int) -> list[dict]:
    where = " AND ".join(["is_active", "embedding IS NOT NULL", *clauses])
    with conn.transaction():
        tune_hnsw(conn, limit)
        return conn.execute(
            CANDIDATES_SQL.format(where=where), {**params, "query": query_vector, "limit": limit}
        ).fetchall()


# ---------- stage 2: features ----------

def similarity_scaled(similarity: float, low: float, high: float) -> float:
    """Raw cosine scores bunch together (about 0.3 to 0.7), so rescale within the candidate pool."""
    return 1.0 if high - low < 1e-9 else (similarity - low) / (high - low)


def skills_feature(wanted: list[str], job_skills: list[str], idf: dict[str, float]) -> float | None:
    """Share of the wanted skills the job asks for, weighting rare skills above common ones (IDF).

    Only skills in our vocabulary can match a posting's tags, so others are ignored here
    (they still shape the query text).
    """
    known = [s for s in wanted if s in idf]
    if not known:
        return None
    total = sum(idf[s] for s in known)
    return sum(idf[s] for s in known if s in job_skills) / total


def location_feature(wants: Wants, job: dict) -> float | None:
    places = [p for p in map(parse_place, wants.locations) if p is not None]
    if not places and wants.remote is None:
        return None
    if any(location_matches(job["location"], p) for p in places):
        return 1.0
    if job["remote"]:
        # Remote: perfect if they asked for it, good if they named places, weak if they prefer on-site.
        return {True: 1.0, None: 0.7, False: 0.3}[wants.remote]
    return 0.0


def seniority_feature(wanted: list[str], job_seniority: str) -> float | None:
    """1 for the same level, 0.5 for one level away, 0 beyond. Unknown level: 0.5."""
    if not wanted:
        return None
    if job_seniority not in SENIORITY_ORDER:
        return 0.5
    distance = min(abs(SENIORITY_ORDER.index(job_seniority) - SENIORITY_ORDER.index(w)) for w in wanted)
    return max(0.0, 1.0 - 0.5 * distance)


def salary_feature(wanted_min: int | None, job: dict) -> float | None:
    """1 if the top of the range reaches what they'd like, 0 if not, 0.5 if the posting doesn't say."""
    if not wanted_min:
        return None
    if job["salary_max"] is None:
        return 0.5
    return 1.0 if job["salary_max"] >= wanted_min else 0.0


def recency_feature(posted_at: datetime | None, newest: datetime | None) -> float | None:
    """Halves every RECENCY_HALF_LIFE_DAYS, measured from the newest posting (the data is a 2024 snapshot)."""
    if posted_at is None or newest is None:
        return None
    age_days = max(0.0, (newest - posted_at).total_seconds() / 86400)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def combine(features: dict[str, float | None]) -> tuple[float, dict[str, dict]]:
    """Weighted average over the features that apply. Returns the score and each feature's share of it."""
    available = {name: value for name, value in features.items() if value is not None}
    total_weight = sum(WEIGHTS[name] for name in available)
    score = sum(WEIGHTS[name] * value for name, value in available.items()) / total_weight
    breakdown = {  # rounded for display only; the score above is exact
        name: {
            "value": round(value, 4),
            "weight": round(WEIGHTS[name] / total_weight, 4),
            "contribution": round(WEIGHTS[name] * value / total_weight, 4),
        }
        for name, value in available.items()
    }
    return score, breakdown


def skill_idf(conn: psycopg.Connection, skills: list[str]) -> dict[str, float]:
    """Smoothed inverse document frequency for the given vocabulary skills, over active jobs."""
    vocab = set(load_vocabulary().values())
    known = [s for s in skills if s in vocab]
    if not known:
        return {}
    total = conn.execute("SELECT count(*) AS n FROM jobs WHERE is_active").fetchone()["n"]
    counts = {
        row["skill"]: row["df"]
        for row in conn.execute(
            """SELECT s AS skill, count(*) AS df FROM jobs, unnest(skills) AS s
               WHERE is_active AND s = ANY(%s) GROUP BY s""",
            (known,),
        )
    }
    return {s: math.log((total + 1) / (counts.get(s, 0) + 1)) + 1 for s in known}


# ---------- putting it together ----------

def match(
    conn: psycopg.Connection,
    prefs: Preferences,
    embed: Embedder,
    *,
    mode: Mode = Mode.full,
    limit: int = 10,
    candidates: int = CANDIDATES,
    llm: LLMClient | None = None,
    strict_check: bool = False,
) -> list[dict]:
    """strict_check: in Mode.checked, raise if the LLM check fails instead of skipping it (for evals)."""
    if mode == Mode.checked and llm is None:
        raise LimitCheckUnavailable("The limit check needs the LLM: set LLM_API_KEY and LLM_MODEL in .env.")
    started = time.perf_counter()
    vector = query_vector(prefs.wants, embed)

    remote_ok = prefs.wants.remote is True or prefs.dealbreakers.only_remote
    clauses, params = dealbreaker_sql(prefs.dealbreakers, remote_ok) if mode != Mode.vector else ([], {})
    pool = retrieve(conn, vector, clauses, params, limit=max(candidates, limit))
    retrieved = time.perf_counter()
    if not pool:
        return []

    idf = skill_idf(conn, prefs.wants.skills)
    newest = conn.execute("SELECT max(posted_at) AS newest FROM jobs WHERE is_active").fetchone()["newest"]
    low, high = min(r["similarity"] for r in pool), max(r["similarity"] for r in pool)

    matches = []
    for job in pool:
        features = {
            "similarity": similarity_scaled(job["similarity"], low, high),
            "skills": skills_feature(prefs.wants.skills, job["skills"], idf),
            "location": location_feature(prefs.wants, job),
            "seniority": seniority_feature(prefs.wants.seniority, job["seniority"]),
            "salary": salary_feature(prefs.wants.min_salary, job),
            "recency": recency_feature(job["posted_at"], newest),
        }
        score, breakdown = combine(features)
        matches.append({
            **job,
            "job_id": job["id"],
            "score": round(score, 4) if mode in (Mode.full, Mode.checked) else round(job["similarity"], 4),
            "features": breakdown,
            "matched_skills": sorted(set(prefs.wants.skills) & set(job["skills"])),
        })

    if mode in (Mode.full, Mode.checked):
        matches.sort(key=lambda m: m["score"], reverse=True)
    # Other modes keep the retrieval order: nearest first.
    reranked = time.perf_counter()
    dropped: list[dict] = []
    if mode == Mode.checked:
        matches, dropped = limit_check.keep_allowed(conn, llm, prefs, matches, limit, fail_open=not strict_check)
    log.info(
        "match mode=%s candidates=%d filters=%d dropped_by_llm_check=%d retrieve_ms=%.0f rerank_ms=%.0f check_ms=%.0f",
        mode.value, len(pool), len(clauses), len(dropped), (retrieved - started) * 1000,
        (reranked - retrieved) * 1000, (time.perf_counter() - reranked) * 1000,
    )
    return matches[:limit]
