"""Plain-language reasons for each match: why this job fits, grounded in the posting and the person's preferences.

Grounding is enforced, not just requested:
- The LLM sees only the posting and the person's stated preferences, each preference
  with an ID (W1, W2, ...).
- matched_preferences must be IDs from that list, and code checks them. A reply with
  an unknown ID, or a missing or extra job, goes back to the model as an error.
- Gaps we can already see from the data ("salary not stated", "not in Austin") are
  computed in code and handed to the LLM as facts it must list in caveats. Honesty
  about those doesn't depend on the model noticing them.

Caching: a reason depends on exactly four things: the posting's content, the
person's preferences, the prompt and the model. The cache key is a hash of all
four, so a repeat request makes no LLM call, and changing any of them (an edited
posting, a new preference, a better prompt) produces a fresh reason.

Batching: uncached jobs go to the LLM up to BATCH_SIZE at a time, because free
tiers allow about 10 requests a minute and 10 one-job calls would take a minute.
Each reason is still cached separately, so batching doesn't affect reuse.
"""

import hashlib
import logging
import time

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from matchwise.embeddings import SENIORITY_LABELS, shorten
from matchwise.llm import LLMClient, LLMError
from matchwise.places import location_matches, parse_place
from matchwise.preferences import Dealbreakers, Preferences
from matchwise.skills import load_vocabulary, strip_boilerplate

log = logging.getLogger(__name__)

PROMPT_VERSION = "reasons-v2"  # what the API uses; older versions are kept so evals can compare
BATCH_SIZE = 5
DESCRIPTION_CHARS = 1500


class Explanation(BaseModel):
    """What the API returns for one match."""
    reason: str
    matched_preferences: list[str]   # the person's own preferences, in words
    caveats: list[str]


class JobReason(BaseModel):
    """What the LLM returns for one job."""
    job_id: int
    reason: str = Field(min_length=10, max_length=400, description="One or two sentences, specific to this job")
    matched_preferences: list[str] = Field(default=[], description="IDs (W1, W2, ...) of preferences this job meets")
    caveats: list[str] = Field(default=[], description="What doesn't fit, is unclear, or isn't stated")


class ReasonBatch(BaseModel):
    reasons: list[JobReason]


# ---------- what the LLM is shown ----------

def preference_items(prefs: Preferences) -> dict[str, str]:
    """The person's stated wants, numbered: {"W1": "role: backend engineer", ...}."""
    w = prefs.wants
    items = (
        [f"role: {r}" for r in w.roles]
        + [f"skill: {s}" for s in w.skills]
        + [f"place: {p}" for p in w.locations]
        + [f"industry: {i}" for i in w.industries]
        + [f"level: {SENIORITY_LABELS[s]}" for s in w.seniority]
        + ({True: ["prefers remote work"], False: ["prefers on-site work"], None: []}[w.remote])
        + ([f"would like at least ${w.min_salary:,} a year"] if w.min_salary else [])
        + [f"also wants: {o}" for o in w.other]
    )
    return {f"W{i}": text for i, text in enumerate(items, start=1)}


def dealbreaker_lines(d: Dealbreakers, remote_ok: bool = False) -> list[str]:
    """The person's hard limits in words, matching how filters.py applies them."""
    where = ", ".join(d.only_locations) + (" (or remote)" if remote_ok else "")
    return (
        [f"no job titles containing '{w}'" for w in d.exclude_title_words]
        + [f"no {f} jobs" for f in d.exclude_functions]
        + [f"no {i} industry" for i in d.exclude_industries]
        + [f"never {c}" for c in d.exclude_companies]
        + [f"no postings mentioning '{p}'" for p in d.exclude_description_phrases]
        + [f"no {SENIORITY_LABELS[s]} roles" for s in d.exclude_seniority]
        + [f"no {t} work" for t in d.exclude_employment_types]
        + ([f"only in: {where}"] if d.only_locations else [])
        + (["remote jobs only"] if d.only_remote else [])
        + ([f"at least ${d.min_salary:,} a year"] if d.min_salary else [])
    )


def known_gaps(prefs: Preferences, job: dict) -> list[str]:
    """Mismatches and unknowns we can read straight from the data."""
    w, d = prefs.wants, prefs.dealbreakers
    gaps = []
    places = [p for p in map(parse_place, w.locations) if p is not None]
    if places and not job["remote"] and not any(location_matches(job["location"], p) for p in places):
        gaps.append(f"Location is {job['location'] or 'not stated'}, not one of your places ({', '.join(w.locations)})")
    if w.remote is True and not job["remote"]:
        gaps.append("Not listed as remote")
    wanted_pay = max((p for p in (w.min_salary, d.min_salary) if p), default=None)
    if wanted_pay:
        if job["salary_max"] is None:
            gaps.append(f"Salary not stated (you want at least ${wanted_pay:,})")
        elif job["salary_max"] < wanted_pay:
            gaps.append(f"Pay tops out at ${job['salary_max']:,}, below the ${wanted_pay:,} you want")
    if w.seniority:
        if job["seniority"] == "unknown":
            gaps.append("Seniority level not stated")
        elif job["seniority"] not in w.seniority:
            gaps.append(f"Level is {SENIORITY_LABELS[job['seniority']]}")
    vocabulary = set(load_vocabulary().values())
    missing = [s for s in w.skills if s in vocabulary and s not in job["skills"]]
    if missing:
        gaps.append(f"Doesn't mention: {', '.join(missing)}")
    return gaps


def posting_block(job: dict, description: str, gaps: list[str]) -> str:
    where = (job["location"] or "location not stated") + (" (remote)" if job["remote"] else "")
    level = " · ".join(x for x in (SENIORITY_LABELS.get(job["seniority"]), job["employment_type"]) if x)
    pay = (f"${job['salary_min']:,}-${job['salary_max']:,} a year" if job["salary_max"] else "not stated")
    lines = [
        f"=== job {job['job_id']} ===",
        f"Title: {job['title']}",
        f"Company: {job['company'] or 'not stated'}",
        f"Location: {where}",
        f"Level: {level or 'not stated'}",
        f"Salary: {pay}",
        f"Skills found in posting: {', '.join(job['skills']) or 'none tagged'}",
        f"Description (start): {shorten(strip_boilerplate(description), DESCRIPTION_CHARS)}",
        "Known gaps (must appear in caveats): " + ("; ".join(gaps) if gaps else "none"),
    ]
    return "\n".join(lines)


SYSTEM_PROMPT_V1 = """You explain to a job seeker why each job posting fits them.

Rules
- Use ONLY the posting text and their stated preferences below. Never invent facts:
  no salary, benefits, team details, schedule or technology the posting doesn't state.
- reason: one or two plain sentences, specific to this posting. Name the concrete things
  that match (the role, skills, place, level, or something in the description). No generic
  praise like "great opportunity". If it's a weak fit, say so honestly.
- matched_preferences: the IDs (W1, W2, ...) of their stated preferences this posting
  clearly meets. Only IDs from the list. Leave out anything you aren't sure of.
- caveats: short phrases about what doesn't fit, is unclear, or isn't stated but matters
  to them. Include every item under "Known gaps", reworded if you like. Don't repeat
  caveats inside the reason.
- Return one entry per job, using its job id."""

# v2, from the judge's findings on v1: reasons counted adjacent roles as matches (a technician
# job "matching" nurse), skipped role mismatches (DevOps offered for backend), and never flagged
# postings that break a hard limit the keyword filters missed (a title saying "Nights" for
# someone who ruled out night shifts), because v1 told the model every job passed the limits.
SYSTEM_PROMPT_V2 = """You explain to a job seeker why each job posting fits them, and where it doesn't.

Rules
- Use ONLY the posting text, its tagged skills and their stated preferences below. Never invent
  facts: no salary, benefits, team details, schedule or technology the posting doesn't state.
- reason: one or two plain sentences, specific to this posting. Name the concrete things that
  match (the role, skills, place, level, or something in the description). If the job is a
  different kind of role from what they asked for (a technician or director job for someone who
  wants nurse jobs; a DevOps or data engineer job for someone who wants backend roles), say so
  plainly. No generic praise. If it's a weak fit, say so.
- matched_preferences: the IDs (W1, W2, ...) of preferences this posting clearly meets. A role
  preference counts only if the posting IS that role, not a related or adjacent one. Only IDs
  from the list. Leave out anything you aren't sure of.
- Check each posting against their hard limits. If anything in it seems to break one (a title
  saying "Nights" when they ruled out night shifts; a fixed-term contract, or a consulting firm,
  when they ruled those out), make that the FIRST caveat, starting with
  "Possible conflict with your limit:".
- caveats: then short phrases about what doesn't fit, is unclear, or isn't stated but matters to
  them, including every item under "Known gaps". Don't repeat caveats inside the reason.
- Return one entry per job, using its job id."""

PROMPTS = {"reasons-v1": SYSTEM_PROMPT_V1, "reasons-v2": SYSTEM_PROMPT_V2}
LIMITS_HEADING = {
    "reasons-v1": "Their hard limits (every job below already passes these)",
    "reasons-v2": "Their hard limits (check each posting against these; the filters can miss things)",
}


def prompt_text(prefs: Preferences, items: dict[str, str], postings: list[str],
                prompt_version: str = PROMPT_VERSION) -> str:
    wants = "\n".join(f"{key}: {text}" for key, text in items.items())
    remote_ok = prefs.wants.remote is True or prefs.dealbreakers.only_remote
    limits = "\n".join(f"- {line}" for line in dealbreaker_lines(prefs.dealbreakers, remote_ok)) or "- none"
    return (
        f"Their stated preferences:\n{wants}\n\n"
        f"{LIMITS_HEADING[prompt_version]}:\n{limits}\n\n"
        "Postings:\n\n" + "\n\n".join(postings)
    )


# ---------- generating and caching ----------

def prefs_hash(prefs: Preferences) -> str:
    return hashlib.sha256(prefs.model_dump_json().encode()).hexdigest()


def cache_key(content_hash: str, preferences_hash: str, model: str, prompt_version: str = PROMPT_VERSION) -> str:
    return hashlib.sha256(f"{content_hash}|{preferences_hash}|{prompt_version}|{model}".encode()).hexdigest()


def generate(llm: LLMClient, prefs: Preferences, jobs: list[dict], descriptions: dict[int, str],
             prompt_version: str = PROMPT_VERSION) -> dict[int, Explanation]:
    """One LLM call for up to BATCH_SIZE jobs."""
    items = preference_items(prefs)
    expected = sorted(job["job_id"] for job in jobs)

    def check(batch: ReasonBatch) -> None:
        got = sorted(r.job_id for r in batch.reasons)
        if got != expected:
            raise ValueError(f"Return exactly one reason for each of the job ids {expected}; you returned {got}.")
        for r in batch.reasons:
            unknown = [i for i in r.matched_preferences if i not in items]
            if unknown:
                raise ValueError(
                    f"job {r.job_id}: matched_preferences may only contain {', '.join(items)}; not {unknown}.")

    postings = [posting_block(job, descriptions[job["job_id"]], known_gaps(prefs, job)) for job in jobs]
    batch = llm.structured(
        system=PROMPTS[prompt_version], user=prompt_text(prefs, items, postings, prompt_version),
        schema=ReasonBatch, purpose="reasons", check=check,
    )
    return {
        r.job_id: Explanation(
            reason=r.reason.strip(),
            matched_preferences=[items[i] for i in dict.fromkeys(r.matched_preferences)],
            caveats=[c.strip() for c in r.caveats if c.strip()],
        )
        for r in batch.reasons
    }


def explain_matches(
    conn: psycopg.Connection, llm: LLMClient, prefs: Preferences, matches: list[dict],
    prompt_version: str = PROMPT_VERSION,
) -> dict[int, Explanation | None]:
    """A reason for each match: from the cache when possible, else generated and cached.

    If the LLM fails for a batch, those jobs get None and the matches are still
    returned: a missing reason shouldn't hide the jobs themselves.
    """
    if not matches:
        return {}
    started = time.perf_counter()
    ids = [m["job_id"] for m in matches]
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, content_hash, description FROM jobs WHERE id = ANY(%s)", (ids,))}
    p_hash = prefs_hash(prefs)
    keys = {job_id: cache_key(rows[job_id]["content_hash"], p_hash, llm.model, prompt_version) for job_id in ids}
    cached = {r["cache_key"]: r["reason"] for r in conn.execute(
        "SELECT cache_key, reason FROM reasons_cache WHERE cache_key = ANY(%s)", (list(keys.values()),))}

    results: dict[int, Explanation | None] = {}
    todo = []
    for match in matches:
        hit = cached.get(keys[match["job_id"]])
        if hit is not None:
            results[match["job_id"]] = Explanation.model_validate(hit)
        else:
            todo.append(match)

    calls = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start : start + BATCH_SIZE]
        calls += 1
        try:
            generated = generate(llm, prefs, batch, {j["job_id"]: rows[j["job_id"]]["description"] for j in batch},
                                 prompt_version)
        except LLMError as error:
            log.error("reasons failed for jobs %s: %s", [j["job_id"] for j in batch], error)
            results.update({j["job_id"]: None for j in batch})
            continue
        for job in batch:
            explanation = generated[job["job_id"]]
            results[job["job_id"]] = explanation
            conn.execute(
                """INSERT INTO reasons_cache (cache_key, content_hash, prefs_hash, prompt_version, model, reason)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (cache_key) DO NOTHING""",
                (keys[job["job_id"]], rows[job["job_id"]]["content_hash"], p_hash, prompt_version, llm.model,
                 Jsonb(explanation.model_dump())),
            )

    log.info(
        "reasons requested=%d cache_hits=%d generated=%d llm_batches=%d ms=%.0f",
        len(matches), len(matches) - len(todo), len(todo), calls, (time.perf_counter() - started) * 1000,
    )
    return results
