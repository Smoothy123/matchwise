"""A second line of defence for hard limits: the LLM reads each top match against the person's limits.

The SQL filters (filters.py) only see structured fields and keywords. The evals found 13% of
top-10 results still broke a stated limit, and every case was only visible in free text: a
"6-month contract via consulting firm", pay stated only in the description, a title ending
"Nights", a "remote" job with an in-store desk. So after re-ranking, the LLM checks the top
jobs against the limits, and jobs it flags are dropped and replaced by the next ones.

False alarms would quietly hide good jobs, so every flag has to be proven:
- the LLM may only cite limits from the person's numbered list (L1, L2, ...), so it can't
  invent a limit they never set;
- it must quote the posting as evidence, and code checks the quote is really in the posting;
- missing information is never a violation (no pay stated is not "below the minimum").
A reply that breaks these rules goes back to the model as an error, like any invalid output.

Verdicts are cached by posting content x limits x prompt x model, so repeat requests are free.
If the LLM fails, the check fails open: the SQL filters still apply, and the jobs are kept.
"""

import hashlib
import json
import logging

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from matchwise.embeddings import SENIORITY_LABELS, shorten
from matchwise.llm import LLMClient, LLMError
from matchwise.preferences import Preferences
from matchwise.skills import strip_boilerplate

log = logging.getLogger(__name__)

# v2, from v1's false alarms on the labelled evals: v1 read "not a 'audit' job" as "never mentions
# audits" (an in-house controller who "coordinates annual audits" was dropped) and read "remote only"
# so strictly that in-person training or a city next to "(listed as remote)" counted as on-site.
PROMPT_VERSION = "limits-v2"

# How a title-word limit is written for the LLM, per prompt version.
TITLE_WORD_RULES = {
    "limits-v1": "not a '{w}' job",
    "limits-v2": "the job itself is not a {w} role (its duties may still mention {w})",
}
BATCH_SIZE = 15          # jobs per LLM call: the top 10 plus a few spares to replace drops
MAX_BATCHES = 3          # at most 45 jobs checked per request, so cost stays bounded
DESCRIPTION_CHARS = 2500

EMPLOYMENT_TYPE_LIMITS = {
    "Contract": "no contract, fixed-term or freelance work",
    "Temporary": "no temporary or seasonal work",
    "Part-time": "no part-time work",
    "Full-time": "no full-time work",
    "Internship": "no internships",
    "Volunteer": "no volunteer roles",
    "Other": "no unusual work arrangements",
}


class Verdict(BaseModel):
    job_id: int
    breaks_limit: bool
    limit_id: str | None = Field(default=None, description="The ID (L1, L2, ...) of the limit it breaks")
    evidence: str | None = Field(default=None, max_length=300, description="A short exact quote from the posting")


class VerdictBatch(BaseModel):
    verdicts: list[Verdict]


def limit_items(prefs: Preferences, prompt_version: str = PROMPT_VERSION) -> dict[str, str]:
    """The person's hard limits as plain rules, numbered: {"L1": "no contract, fixed-term or freelance work", ...}.

    Written by meaning rather than as the SQL filters apply them ("nothing involving night shift",
    not "no postings mentioning 'night shift'"), so the LLM catches other wordings like "Nights".
    """
    d = prefs.dealbreakers
    remote_ok = prefs.wants.remote is True or d.only_remote
    lines = (
        [TITLE_WORD_RULES[prompt_version].format(w=w) for w in d.exclude_title_words]
        + [f"no {f} roles" for f in d.exclude_functions]
        + [f"no jobs in the {i} industry" for i in d.exclude_industries]
        + [f"never at {c}" for c in d.exclude_companies]
        + [f"nothing involving {p}" for p in d.exclude_description_phrases]
        + [f"no {SENIORITY_LABELS[s]} roles" for s in d.exclude_seniority]
        + [EMPLOYMENT_TYPE_LIMITS[t] for t in d.exclude_employment_types]
        + ([f"only jobs located in {', '.join(d.only_locations)}" + (" or fully remote" if remote_ok else "")]
           if d.only_locations else [])
        + (["only fully remote jobs, with no on-site duties"] if d.only_remote else [])
        + ([f"pay must reach at least ${d.min_salary:,} a year (when the posting states pay)"] if d.min_salary else [])
    )
    return {f"L{i}": line for i, line in enumerate(lines, start=1)}


def posting_card(job: dict, description: str) -> str:
    """What the LLM reads for one job. Evidence quotes are checked against this exact text."""
    where = (job["location"] or "not stated") + (" (listed as remote)" if job["remote"] else "")
    pay = f"${job['salary_min']:,}-${job['salary_max']:,} a year" if job["salary_max"] else "not stated"
    return "\n".join([
        f"Title: {job['title']}",
        f"Company: {job['company'] or 'not stated'}",
        f"Location: {where}",
        f"Type: {job['employment_type'] or 'not stated'} | Level: {SENIORITY_LABELS.get(job['seniority'], 'not stated')}",
        f"Pay: {pay}",
        f"Description: {shorten(strip_boilerplate(description), DESCRIPTION_CHARS)}",
    ])


def _normalised(text: str) -> str:
    return " ".join(text.lower().split())


SYSTEM_PROMPT_V1 = """You check job postings against a job seeker's hard limits (listed with IDs L1, L2, ...).
For each posting, decide whether it clearly breaks one of those limits.

- breaks_limit = true only when the posting itself shows it. Examples: "6-month contract" breaks
  "no contract, fixed-term or freelance work"; a title ending "Nights" breaks "nothing involving
  night shift"; "pay $70,000" breaks "pay must reach at least $90,000"; an in-store desk breaks
  "only fully remote jobs"; a job in Denver breaks "only jobs located in Texas".
- Missing or unclear information is NOT a violation: no pay stated, no schedule stated, no
  contract length stated are all fine.
- Only the listed limits count. Don't flag anything else, however unattractive.
- If breaks_limit is true: limit_id = the ID of the limit it breaks, and evidence = a short quote
  copied exactly from the posting text that shows it.
- If breaks_limit is false: leave limit_id and evidence empty.
Return one verdict per job id."""

SYSTEM_PROMPT_V2 = """You check job postings against a job seeker's hard limits (listed with IDs L1, L2, ...).
For each posting, decide whether it clearly breaks one of those limits.

- breaks_limit = true only when the posting itself shows it. Examples: "6-month contract" breaks
  "no contract, fixed-term or freelance work"; a title ending "Nights" breaks "nothing involving
  night shift"; "pay $70,000" breaks "pay must reach at least $90,000"; a job in Denver breaks
  "only jobs located in Texas".
- A limit about a kind of role is broken only when the job IS that kind of role. Mentioning the
  word in the duties, requirements or company description doesn't break it: an accountant who
  "coordinates annual audits" is not in an audit role; a paralegal job asking for "experience in
  personal injury" is not a personal injury firm.
- "Only fully remote" is broken only by required on-site work. A city shown next to
  "(listed as remote)", or occasional in-person training, doesn't break it.
- Missing or unclear information is NOT a violation: no pay stated, no schedule stated, no
  contract length stated are all fine.
- Only the listed limits count. Don't flag anything else, however unattractive.
- If breaks_limit is true: limit_id = the ID of the limit it breaks, and evidence = a short quote
  copied exactly from the posting text that itself shows the violation.
- If breaks_limit is false: leave limit_id and evidence empty.
Return one verdict per job id."""

PROMPTS = {"limits-v1": SYSTEM_PROMPT_V1, "limits-v2": SYSTEM_PROMPT_V2}


def _limits_hash(items: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()


def _cache_key(content_hash: str, limits_hash: str, model: str, prompt_version: str) -> str:
    return hashlib.sha256(f"{content_hash}|{limits_hash}|{prompt_version}|{model}".encode()).hexdigest()


def judge_batch(llm: LLMClient, items: dict[str, str], cards: dict[int, str],
                prompt_version: str = PROMPT_VERSION) -> dict[int, Verdict]:
    """One LLM call: a verdict for each job in `cards` (job_id -> posting card)."""
    def check(batch: VerdictBatch) -> None:
        got = sorted(v.job_id for v in batch.verdicts)
        if got != sorted(cards):
            raise ValueError(f"Return exactly one verdict for each of the job ids {sorted(cards)}; you returned {got}.")
        for v in batch.verdicts:
            if not v.breaks_limit:
                continue
            if v.limit_id not in items:
                raise ValueError(f"job {v.job_id}: limit_id must be one of {', '.join(items)}, not {v.limit_id!r}.")
            if not v.evidence or _normalised(v.evidence) not in _normalised(cards[v.job_id]):
                raise ValueError(f"job {v.job_id}: evidence must be an exact quote from that posting; "
                                 f"{v.evidence!r} isn't in it.")

    limits = "\n".join(f"{key}: {text}" for key, text in items.items())
    postings = "\n\n".join(f"=== job {job_id} ===\n{card}" for job_id, card in cards.items())
    batch = llm.structured(system=PROMPTS[prompt_version], user=f"Their hard limits:\n{limits}\n\nPostings:\n\n{postings}",
                           schema=VerdictBatch, purpose="limit_check", check=check)
    return {v.job_id: v for v in batch.verdicts}


def verdicts_for(conn: psycopg.Connection, llm: LLMClient, items: dict[str, str], jobs: list[dict],
                 prompt_version: str = PROMPT_VERSION, fail_open: bool = True) -> dict[int, Verdict]:
    """Verdicts for `jobs`: from the cache where possible, otherwise one LLM call for the rest.

    If that call fails and fail_open is set, the cached verdicts are still returned; jobs
    without one are simply missing from the result (their caller marks them "skipped").
    """
    ids = [job["job_id"] for job in jobs]
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, content_hash, description FROM jobs WHERE id = ANY(%s)", (ids,))}
    l_hash = _limits_hash(items)
    keys = {job_id: _cache_key(rows[job_id]["content_hash"], l_hash, llm.model, prompt_version) for job_id in ids}
    cached = {r["cache_key"]: r["verdict"] for r in conn.execute(
        "SELECT cache_key, verdict FROM limit_checks WHERE cache_key = ANY(%s)", (list(keys.values()),))}
    verdicts = {job_id: Verdict.model_validate(cached[key]) for job_id, key in keys.items() if key in cached}
    todo = [job for job in jobs if job["job_id"] not in verdicts]
    if todo:
        try:
            fresh = judge_batch(llm, items, {job["job_id"]: posting_card(job, rows[job["job_id"]]["description"])
                                             for job in todo}, prompt_version)
        except LLMError as error:  # fail open: the SQL filters already applied, cached verdicts still count
            if not fail_open:
                raise
            log.warning("limit check skipped for %d of %d jobs: %s", len(todo), len(jobs), error)
            return verdicts
        for job_id, verdict in fresh.items():
            conn.execute(
                """INSERT INTO limit_checks (cache_key, content_hash, limits_hash, prompt_version, model, verdict)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (cache_key) DO NOTHING""",
                (keys[job_id], rows[job_id]["content_hash"], l_hash, prompt_version, llm.model,
                 Jsonb(verdict.model_dump())))
        verdicts.update(fresh)
    return verdicts


def keep_allowed(conn: psycopg.Connection, llm: LLMClient, prefs: Preferences, ranked: list[dict],
                 limit: int, prompt_version: str = PROMPT_VERSION,
                 fail_open: bool = True) -> tuple[list[dict], list[dict]]:
    """Walk the ranked list in batches, dropping jobs that break a limit, until `limit` jobs are kept.

    Returns (kept, dropped). Every job gets a "limit_check" status: "passed" (checked, no limit
    broken), "skipped" (the LLM failed, so only the SQL filters applied), "no limits" (nothing to
    check) or "dropped" (with the verdict under "limit_check_verdict").
    fail_open: if the LLM fails, keep the jobs, marked "skipped" (right for serving: an outage
    shouldn't hide every job, but callers can see it). Evals pass False, so a busy API can never
    leave numbers silently computed on a half-done check.
    """
    items = limit_items(prefs, prompt_version)
    if not items:  # no hard limits: nothing to check, no LLM call
        return [{**job, "limit_check": "no limits"} for job in ranked[:limit]], []
    kept: list[dict] = []
    dropped: list[dict] = []
    for start in range(0, min(len(ranked), BATCH_SIZE * MAX_BATCHES), BATCH_SIZE):
        if len(kept) >= limit:
            break
        batch = ranked[start : start + BATCH_SIZE]
        verdicts = verdicts_for(conn, llm, items, batch, prompt_version, fail_open)
        for job in batch:
            verdict = verdicts.get(job["job_id"])
            if verdict is None:
                kept.append({**job, "limit_check": "skipped"})
            elif verdict.breaks_limit:
                dropped.append({**job, "limit_check": "dropped",
                                "limit_check_verdict": verdict.model_dump() | {"limit": items[verdict.limit_id]}})
            else:
                kept.append({**job, "limit_check": "passed"})
    return kept[:limit], dropped
