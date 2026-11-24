"""Build the labelling pool, then label it yourself in the terminal.

    python -m evals.label pool      # once: which postings to label for each persona
    python -m evals.label           # label (resumes where you stopped; q to quit)
    python -m evals.label status    # progress

Why a pool: nobody can read 5,000 postings per persona. Instead we label the
union of what every system ranks highest (top `depth` from vector-only,
vector + filters, and the full re-ranker), plus a plain keyword search so the pool
isn't only things our embeddings like. This is "pooling", the standard method
from TREC search evaluations. Postings outside the pool count as "not a match";
judged@10 in the results shows how much that assumption matters.

The pool is shuffled and you never see which system found a posting, so you
can't favour one system without meaning to.

Grades: 2 = good match (you'd want to see it), 1 = okay or partial, 0 = not a fit.
Add x if it breaks something the persona ruled out (e.g. 0x). Judge against what
the persona SAID (shown at the top), not against what the extractor understood.
"""

import argparse
import hashlib
import json
import random
import textwrap
from datetime import datetime, timezone

import psycopg

from evals.data import (
    LABELS_JSONL, POOL_JSON, EvalProfile, append_jsonl, load_extracted, load_labels, load_profiles,
)
from matchwise import db, embeddings
from matchwise.embeddings import SENIORITY_LABELS
from matchwise.preferences import Preferences
from matchwise.ranking import Mode, match
from matchwise.skills import strip_boilerplate

KEYWORD_SQL = """
SELECT source_id FROM jobs
WHERE is_active AND to_tsvector('english', title || ' ' || description) @@ websearch_to_tsquery('english', %(q)s)
ORDER BY ts_rank(to_tsvector('english', title || ' ' || description), websearch_to_tsquery('english', %(q)s)) DESC
LIMIT %(limit)s
"""


def keyword_query(prefs: Preferences) -> str:
    """Role and skill words joined with 'or', for Postgres full-text search."""
    words = {w for phrase in prefs.wants.roles + prefs.wants.skills for w in phrase.lower().split() if len(w) > 2}
    return " or ".join(sorted(words))


def build_pool(conn: psycopg.Connection, profile_id: str, prefs: Preferences, embed, depth: int,
               keyword_depth: int) -> list[str]:
    """Union of every system's top `depth` plus keyword hits, in a shuffled order that's fixed per persona."""
    found: list[str] = []
    for mode in Mode:
        found += [m["source_id"] for m in match(conn, prefs, embed, mode=mode, limit=depth)]
    query = keyword_query(prefs)
    if query:
        found += [r["source_id"] for r in conn.execute(KEYWORD_SQL, {"q": query, "limit": keyword_depth})]
    pool = list(dict.fromkeys(found))  # drop duplicates, keep first-seen order
    random.Random(int(hashlib.sha256(profile_id.encode()).hexdigest()[:8], 16)).shuffle(pool)
    return pool


# ---------- the labelling screen ----------

def posting_card(row: dict, full: bool = False) -> str:
    level = " · ".join(x for x in (SENIORITY_LABELS.get(row["seniority"]), row["employment_type"]) if x)
    pay = f"${row['salary_min']:,}-${row['salary_max']:,}/yr" if row["salary_max"] else "pay not stated"
    where = (row["location"] or "?") + (" (remote)" if row["remote"] else "")
    text = " ".join(strip_boilerplate(row["description"]).split())
    text = text if full else text[:700] + ("..." if len(text) > 700 else "")
    return "\n".join([
        f"\033[1m{row['title']}\033[0m",
        f"{row['company'] or '?'} · {where} · {level or 'level not stated'} · {pay}",
        f"functions: {', '.join(row['functions']) or '-'} · skills: {', '.join(row['skills']) or '-'}",
        "",
        textwrap.fill(text, 100),
    ])


def label_loop(conn: psycopg.Connection, profiles: list[EvalProfile], pool: dict[str, list[str]]) -> None:
    labels = load_labels()
    todo = [(p, sid) for p in profiles for sid in pool.get(p.id, []) if (p.id, sid) not in labels]
    total = sum(len(v) for v in pool.values())
    rows = {r["source_id"]: r for r in conn.execute(
        """SELECT source_id, title, company, location, remote, seniority, employment_type, functions, skills,
                  salary_min, salary_max, description FROM jobs WHERE source_id = ANY(%s)""",
        ([sid for _, sid in todo],))}
    history: list[tuple[EvalProfile, str]] = []
    i = 0
    current = None
    while i < len(todo):
        profile, sid = todo[i]
        if profile is not current:
            current = profile
            print("\n" + "=" * 100 + f"\nPERSONA {profile.id}")
            for message in profile.messages:
                print(textwrap.fill(f'"{message}"', 100, initial_indent="  ", subsequent_indent="   "))
            print("=" * 100)
        done = total - len(todo) + i
        print(f"\n[{done + 1}/{total}] {profile.id}\n" + posting_card(rows[sid]))
        answer = ""
        while not answer or answer == "d":
            if answer == "d":
                print("\n" + posting_card(rows[sid], full=True))
            answer = input("\ngrade 2/1/0 (+x = breaks a limit) · d full text · b back · s skip · q quit > ")
            answer = answer.strip().lower()
        if answer == "q":
            break
        if answer == "s":
            i += 1
            continue
        if answer == "b":
            if history:  # re-label the previous posting; the new label replaces the old one
                todo.insert(i, history.pop())
            continue
        if not answer or answer[0] not in "210" or answer[1:] not in ("", "x"):
            print("  type 2, 1 or 0, optionally followed by x (e.g. 0x)")
            continue
        append_jsonl(LABELS_JSONL, {
            "profile": profile.id, "source_id": sid, "title": rows[sid]["title"],
            "grade": int(answer[0]), "violation": answer.endswith("x"),
            "labelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        history.append((profile, sid))
        i += 1
    print(f"\nlabels saved to {LABELS_JSONL.relative_to(LABELS_JSONL.parent.parent)}")


def status(profiles: list[EvalProfile], pool: dict[str, list[str]]) -> None:
    labels = load_labels()
    for p in profiles:
        mine = [labels[(p.id, sid)] for sid in pool.get(p.id, []) if (p.id, sid) in labels]
        good = sum(1 for lab in mine if lab.grade == 2)
        flagged = sum(1 for lab in mine if lab.violation)
        print(f"{p.id:22} {len(mine):3}/{len(pool.get(p.id, [])):3} labelled · {good:2} good · {flagged} break a limit")


def main() -> None:
    from matchwise.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="label", choices=["pool", "label", "status"])
    parser.add_argument("--depth", type=int, default=20, help="top-N taken from each system for the pool")
    parser.add_argument("--keyword-depth", type=int, default=10)
    parser.add_argument("--profile", help="only this persona")
    args = parser.parse_args()

    profiles = [p for p in load_profiles() if not args.profile or p.id == args.profile]
    with db.connect(get_settings().database_url) as conn:
        if args.command == "pool":
            extracted = load_extracted()
            pool = json.loads(POOL_JSON.read_text()) if POOL_JSON.exists() else {}
            for p in profiles:
                pool[p.id] = build_pool(conn, p.id, extracted[p.id], embeddings.embed_texts, args.depth,
                                        args.keyword_depth)
                print(f"{p.id:22} {len(pool[p.id])} postings to label")
            POOL_JSON.write_text(json.dumps(pool, indent=1) + "\n")
            print(f"total: {sum(len(v) for v in pool.values())} postings -> {POOL_JSON.name}")
            return
        pool = json.loads(POOL_JSON.read_text())
        if args.command == "status":
            status(profiles, pool)
        else:
            label_loop(conn, profiles, pool)


if __name__ == "__main__":
    main()
