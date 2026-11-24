"""Reason quality: an LLM judge scores each reason, and a reference scorer checks the judge.

    python -m evals.judge run [--model M]   # generate reasons for each persona's top 5, judge them
    python -m evals.judge compare           # reasons-v1 vs the current prompt, on the same postings
    python -m evals.judge score             # a person scores a sample (the judge's scores stay hidden)
    python -m evals.judge agree             # how often the judge agrees with the reference scores

The reference scores (reference_scores.jsonl) say who made them in a `scorer` field:
"human" from `score`, or a model name when an independent model scored the same sample.

Rubric, each 1-5:
  specific  names concrete details of this posting, not text that fits any job
  grounded  every claim and every "matched preference" is supported by the posting
            or by what the person said; nothing invented
  honest    caveats cover the real mismatches and unknowns; the reason doesn't oversell

The judge sees what the person SAID (their messages), the posting and the reason.
It does not see our pre-computed "known gaps": it has to find mismatches itself.
Judging with a different model from the one that wrote the reasons reduces the
risk of a model favouring its own writing.

Judgements are cached in results/judgements.jsonl, keyed by a hash of the reason
text plus the judge's model and prompt version, so re-running costs nothing.
"""

import argparse
import hashlib
import json
import os
import random
import statistics
import textwrap

import psycopg
from pydantic import BaseModel, Field

from evals.data import (
    REFERENCE_SCORES_JSONL, JUDGEMENTS_JSONL, RESULTS_DIR, EvalProfile, append_jsonl, load_extracted, load_profiles,
    read_jsonl,
)
from evals.label import posting_card
from evals.metrics import mean_and_ci
from matchwise import db, embeddings, reasons
from matchwise.embeddings import shorten
from matchwise.llm import LLMClient
from matchwise.ranking import Mode, match
from matchwise.skills import strip_boilerplate

# judge-v2: v1 saw only the first 2,500 characters of a posting, so it called true claims
# "invented" when the evidence came later (Python at character 2,960 in one DevOps posting).
# v2 sees the whole description plus the skills tagged from it: the same evidence as the writer.
JUDGE_PROMPT_VERSION = "judge-v2"
JUDGE_DESCRIPTION_CHARS = 8000
DIMENSIONS = ("specific", "grounded", "honest")
TOP_K = 5
HUMAN_SAMPLE = 20


class JudgeScore(BaseModel):
    specific: int = Field(ge=1, le=5)
    grounded: int = Field(ge=1, le=5)
    honest: int = Field(ge=1, le=5)
    rationale: str = Field(max_length=400, description="One sentence: the main reason for the scores")


JUDGE_SYSTEM = """You grade a short explanation of why a job posting fits a job seeker.
You get what the job seeker said, the posting, and the explanation (a reason, the preferences it
claims the posting meets, and caveats). Score each dimension from 1 to 5.

specific: 5 = names concrete details from this posting (role, skills, place, something in the
  description). 3 = partly specific. 1 = generic; could describe almost any job.
grounded: 5 = every claim is supported by the posting or by what the person said, and every
  "matched preference" is truly met by this posting. 3 = one doubtful or overstated claim
  (e.g. a technician job counted as matching "nurse"). 1 = invents facts (pay, benefits,
  technology, schedule) or claims matches that clearly aren't there.
honest: 5 = the caveats cover every real mismatch or unknown that matters to this person, and the
  reason doesn't oversell. 3 = misses one important issue. 1 = hides obvious mismatches or calls a
  poor fit a great one.

Be strict and consistent. Judge only from the text given."""


def reason_hash(explanation: dict) -> str:
    return hashlib.sha256(json.dumps(explanation, sort_keys=True).encode()).hexdigest()[:16]


def judge_prompt(profile: EvalProfile, job: dict, explanation: dict) -> str:
    said = "\n".join(f'- "{m}"' for m in profile.messages)
    where = (job["location"] or "not stated") + (" (remote)" if job["remote"] else "")
    pay = f"${job['salary_min']:,}-${job['salary_max']:,} a year" if job["salary_max"] else "not stated"
    posting = "\n".join([
        f"Title: {job['title']}", f"Company: {job['company'] or 'not stated'}", f"Location: {where}",
        f"Level: {job['seniority']} · {job['employment_type'] or 'type not stated'}", f"Salary: {pay}",
        f"Skills tagged anywhere in the posting: {', '.join(job['skills']) or 'none'}",
        f"Description: {shorten(strip_boilerplate(job['description']), JUDGE_DESCRIPTION_CHARS)}",
    ])
    shown = "\n".join([
        f"Reason: {explanation['reason']}",
        f"Claims these preferences are met: {'; '.join(explanation['matched_preferences']) or 'none'}",
        f"Caveats: {'; '.join(explanation['caveats']) or 'none'}",
    ])
    return f"What the job seeker said:\n{said}\n\nThe posting:\n{posting}\n\nThe explanation to grade:\n{shown}"


JOB_COLUMNS = """id, source_id, title, company, location, remote, seniority, employment_type,
                 salary_min, salary_max, functions, skills, description"""
JOB_SQL = f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = ANY(%s)"
JOB_BY_SOURCE_SQL = f"SELECT {JOB_COLUMNS} FROM jobs WHERE source_id = ANY(%s)"


def collect_reasons(conn: psycopg.Connection, writer: LLMClient, profiles: list[EvalProfile], embed,
                    reasons_version: str = reasons.PROMPT_VERSION) -> list[dict]:
    """Each persona's top TOP_K matches with their reasons (generated, or read from the reasons cache)."""
    prefs = load_extracted()
    items = []
    for profile in profiles:
        matches = match(conn, prefs[profile.id], embed, mode=Mode.full, limit=TOP_K)
        explained = reasons.explain_matches(conn, writer, prefs[profile.id], matches, reasons_version)
        jobs = {r["id"]: r for r in conn.execute(JOB_SQL, ([m["job_id"] for m in matches],))}
        for m in matches:
            explanation = explained.get(m["job_id"])
            if explanation is not None:
                items.append({"profile": profile.id, "job": jobs[m["job_id"]],
                              "explanation": explanation.model_dump()})
    return items


def judge_all(judge: LLMClient, profiles: list[EvalProfile], items: list[dict],
              reasons_version: str = reasons.PROMPT_VERSION) -> list[dict]:
    """Judge every item, reusing cached judgements. Returns one record per item."""
    by_id = {p.id: p for p in profiles}
    cached = {(r["reason_hash"], r["judge_model"], r["judge_prompt_version"]): r for r in read_jsonl(JUDGEMENTS_JSONL)}
    records = []
    for item in items:
        key = (reason_hash(item["explanation"]), judge.model, JUDGE_PROMPT_VERSION)
        record = cached.get(key)
        if record is None:
            score = judge.structured(
                system=JUDGE_SYSTEM, user=judge_prompt(by_id[item["profile"]], item["job"], item["explanation"]),
                schema=JudgeScore, purpose="judge")
            record = {
                "profile": item["profile"], "source_id": item["job"]["source_id"], "reason_hash": key[0],
                "reasons_prompt_version": reasons_version, "judge_model": judge.model,
                "judge_prompt_version": JUDGE_PROMPT_VERSION, "explanation": item["explanation"],
                **score.model_dump(),
            }
            append_jsonl(JUDGEMENTS_JSONL, record)
        records.append(record)
    return records


def summary_table(records: list[dict]) -> str:
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        groups.setdefault((r["reasons_prompt_version"], r["judge_model"]), []).append(r)
    lines = ["| Reasons prompt | Judge | Specific | Grounded | Honest | n |", "|---|---|---|---|---|---|"]
    for (version, judge_model), rows in sorted(groups.items()):
        means = [statistics.fmean(r[d] for r in rows) for d in DIMENSIONS]
        lines.append(f"| {version} | {judge_model} | " + " | ".join(f"{m:.2f}" for m in means) + f" | {len(rows)} |")
    return "\n".join(lines)


def paired_comparison(records: list[dict], before: str, after: str) -> dict[str, tuple[float, float, float, int]]:
    """Change in each score from `before` to `after` reasons prompt, on the same (persona, posting) pairs.

    Differences are averaged per persona first, then a bootstrap over personas gives the 95%
    interval: reasons for one persona aren't independent, so personas are the unit to resample.
    Returns {dimension: (mean change, low, high, number of pairs)}.
    """
    scores = {(r["profile"], r["source_id"], r["reasons_prompt_version"]): r for r in records}
    pairs = [(scores[(p, s, before)], scores[(p, s, after)])
             for (p, s, v) in scores if v == before and (p, s, after) in scores]
    out = {}
    for d in DIMENSIONS:
        per_profile: dict[str, list[int]] = {}
        for old, new in pairs:
            per_profile.setdefault(old["profile"], []).append(new[d] - old[d])
        out[d] = (*mean_and_ci([statistics.fmean(v) for v in per_profile.values()]), len(pairs))
    return out


def comparison_table(records: list[dict], before: str, after: str) -> str:
    change = paired_comparison(records, before, after)
    rows = {v: [r for r in records if r["reasons_prompt_version"] == v] for v in (before, after)}
    lines = ["| Reasons prompt | Specific | Grounded | Honest | n |", "|---|---|---|---|---|"]
    for version, rs in rows.items():
        lines.append(f"| {version} | " + " | ".join(f"{statistics.fmean(r[d] for r in rs):.2f}" for d in DIMENSIONS)
                     + f" | {len(rs)} |")
    lines.append("| change (95% CI) | " + " | ".join(
        f"{change[d][0]:+.2f} ({change[d][1]:+.2f} to {change[d][2]:+.2f})" for d in DIMENSIONS)
        + f" | {change[DIMENSIONS[0]][3]} pairs |")
    return "\n".join(lines)


# ---------- reference scores vs the judge ----------

def agreement(judge_records: list[dict], reference_records: list[dict]) -> dict[str, dict[str, float]]:
    """Per dimension: exact agreement, agreement within 1 point, mean absolute difference,
    and the judge's and the reference average (to see if the judge is systematically kinder)."""
    judged = {r["reason_hash"]: r for r in judge_records}
    pairs = [(judged[h["reason_hash"]], h) for h in reference_records if h["reason_hash"] in judged]
    out = {}
    for d in DIMENSIONS:
        diffs = [abs(j[d] - h[d]) for j, h in pairs]
        out[d] = {
            "n": len(pairs),
            "exact": sum(x == 0 for x in diffs) / len(diffs) if diffs else float("nan"),
            "within_1": sum(x <= 1 for x in diffs) / len(diffs) if diffs else float("nan"),
            "mean_abs_diff": statistics.fmean(diffs) if diffs else float("nan"),
            "judge_mean": statistics.fmean(j[d] for j, _ in pairs) if pairs else float("nan"),
            "reference_mean": statistics.fmean(h[d] for _, h in pairs) if pairs else float("nan"),
        }
    return out


def agreement_table(stats: dict[str, dict[str, float]]) -> str:
    lines = ["| Dimension | Exact agreement | Within 1 point | Mean abs. difference | Judge mean | Reference mean | n |",
             "|---|---|---|---|---|---|---|"]
    for d, s in stats.items():
        lines.append(f"| {d} | {s['exact']:.0%} | {s['within_1']:.0%} | {s['mean_abs_diff']:.2f} | "
                     f"{s['judge_mean']:.2f} | {s['reference_mean']:.2f} | {s['n']} |")
    return "\n".join(lines)


def score_loop(conn: psycopg.Connection, profiles: list[EvalProfile], records: list[dict]) -> None:
    """A person scores a fixed random sample of the judged reasons, without seeing the judge's scores."""
    by_id = {p.id: p for p in profiles}
    done = {h["reason_hash"] for h in read_jsonl(REFERENCE_SCORES_JSONL)}
    sample = random.Random(7).sample(records, min(HUMAN_SAMPLE, len(records)))
    todo = [r for r in sample if r["reason_hash"] not in done]
    jobs = {r["source_id"]: r for r in conn.execute(JOB_BY_SOURCE_SQL, ([r["source_id"] for r in todo],))}
    print(f"{len(sample) - len(todo)} of {len(sample)} already scored.")
    for n, record in enumerate(todo, start=len(sample) - len(todo) + 1):
        profile, e = by_id[record["profile"]], record["explanation"]
        print("\n" + "=" * 100 + f"\n[{n}/{len(sample)}] PERSONA {profile.id}")
        for message in profile.messages:
            print(textwrap.fill(f'"{message}"', 100, initial_indent="  ", subsequent_indent="   "))
        print("-" * 100 + "\n" + posting_card(jobs[record["source_id"]], full=True) + "\n" + "-" * 100)
        print(textwrap.fill(e["reason"], 100, initial_indent="REASON:  ", subsequent_indent="         "))
        print(f"MATCHED: {'; '.join(e['matched_preferences']) or 'none'}")
        print(f"CAVEATS: {'; '.join(e['caveats']) or 'none'}")
        scores = {}
        for d in DIMENSIONS:
            while d not in scores:
                answer = input(f"{d} 1-5 (q to stop) > ").strip()
                if answer == "q":
                    return
                if answer in {"1", "2", "3", "4", "5"}:
                    scores[d] = int(answer)
        append_jsonl(REFERENCE_SCORES_JSONL, {"profile": record["profile"], "source_id": record["source_id"],
                                              "reason_hash": record["reason_hash"], "scorer": "human", **scores})


def main() -> None:
    from matchwise.config import get_settings, setup_logging
    from matchwise.llm import client_from_settings

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "compare", "score", "agree"])
    parser.add_argument("--before", default="reasons-v1", help="for compare: the baseline reasons prompt")
    parser.add_argument("--model", help="judge model (default: JUDGE_MODEL or LLM_MODEL from .env)")
    parser.add_argument("--reasons-version", default=reasons.PROMPT_VERSION, choices=sorted(reasons.PROMPTS))
    args = parser.parse_args()

    settings = get_settings()
    setup_logging("WARNING")
    profiles = load_profiles()
    judge = client_from_settings(settings, model=args.model or os.environ.get("JUDGE_MODEL"))
    # Only judgements by the same judge model and judge prompt are comparable with each other.
    current = [r for r in read_jsonl(JUDGEMENTS_JSONL)
               if r["judge_prompt_version"] == JUDGE_PROMPT_VERSION and r["judge_model"] == judge.model]
    # score and agree only read the saved judgements of this reasons version by this judge.
    saved = [r for r in current
             if r["judge_model"] == judge.model and r["reasons_prompt_version"] == args.reasons_version]
    RESULTS_DIR.mkdir(exist_ok=True)
    with db.connect(settings.database_url) as conn:
        if args.command == "run":
            writer = client_from_settings(settings)
            items = collect_reasons(conn, writer, profiles, embeddings.embed_texts, args.reasons_version)
            judge_all(judge, profiles, items, args.reasons_version)
            current = [r for r in read_jsonl(JUDGEMENTS_JSONL)
                       if r["judge_prompt_version"] == JUDGE_PROMPT_VERSION and r["judge_model"] == judge.model]
            table = summary_table(current)  # every reasons version judged so far, by this judge
            print(table + f"\n\nwriter: {writer.model} · judge: {judge.model} · "
                          f"writer usage {writer.usage} · judge usage {judge.usage}")
            (RESULTS_DIR / "reasons.md").write_text(table + "\n")
        elif args.command == "compare":
            table = comparison_table(current, args.before, args.reasons_version)
            note = (f"Judge: {judge.model} ({JUDGE_PROMPT_VERSION}); writer: {settings.llm_model}. "
                    "Each persona's top 5 matches, the same postings for both prompts. "
                    "Change = paired difference, 95% bootstrap interval over personas.")
            print(table + "\n\n" + note)
            (RESULTS_DIR / "reasons.md").write_text(table + "\n\n" + note + "\n")
        elif args.command == "score":
            score_loop(conn, profiles, saved)
        else:
            table = agreement_table(agreement(saved, read_jsonl(REFERENCE_SCORES_JSONL)))
            print(table)
            (RESULTS_DIR / "judge_agreement.md").write_text(table + "\n")


if __name__ == "__main__":
    main()
