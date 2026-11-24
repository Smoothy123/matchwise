"""Daily refresh: apply today's snapshot of open postings, and re-embed only what changed.

Every morning the full list of open postings arrives as a snapshot (here a JSONL
file). The refresh compares it with the database by source_id and content_hash:

  added        in the snapshot, not in the database        -> insert
  updated      content_hash (or derived skills) changed    -> update
  reactivated  unchanged, but had been removed earlier     -> mark active again
  unchanged    same content                                 -> just record it was seen
  removed      active in the database, missing today       -> soft delete (is_active = false)

All of that is one transaction, so nobody ever sees half of a day applied.
Then embed_pending() re-embeds only jobs whose *embedded text* changed. A salary
change, or an edit past the part of the description we embed, updates the row
(and so invalidates cached reasons) without a single new embedding.

Safety: if a snapshot would remove more than MAX_REMOVED_FRACTION of active jobs,
it is refused. A truncated or broken feed must not wipe the catalogue.

Simulation (no real feed exists): `simulate` makes tomorrow's snapshot from
today's jobs by removing some, editing some (title, salary, remote flag,
description tail) and adding unseen postings from the Kaggle CSV.

    python -m matchwise.refresh day --seed 1            # simulate a day and apply it
    python -m matchwise.refresh simulate --seed 1 --out data/snapshots/day-1.jsonl
    python -m matchwise.refresh apply data/snapshots/day-1.jsonl
    python -m matchwise.refresh runs                     # recent runs

How this scales to millions of postings: see docs/scaling.md.
"""

import argparse
import json
import logging
import random
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

from matchwise import db, embeddings, ingest
from matchwise.ingest import HASHED_FIELDS, Job, compute_content_hash, with_skills

log = logging.getLogger(__name__)

MAX_REMOVED_FRACTION = 0.2


class SuspiciousSnapshot(Exception):
    """The snapshot would remove so many jobs that it is more likely broken than real."""


# ---------- snapshots ----------

def write_snapshot(path: Path, jobs: Iterable[Job]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(asdict(job), default=str) + "\n")
            count += 1
    return count


def read_snapshot(path: Path) -> Iterator[Job]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            data["posted_at"] = datetime.fromisoformat(data["posted_at"]) if data["posted_at"] else None
            for name in ("functions", "industries", "skills"):
                data[name] = tuple(data[name])
            yield Job(**data)


# ---------- simulating a day of churn ----------

@dataclass(frozen=True)
class ChurnPlan:
    seed: int
    add: int = 150               # new postings
    edit_fraction: float = 0.05  # of the jobs that stay
    remove_fraction: float = 0.03


EDIT_KINDS = ("title", "salary", "remote", "description_tail")


def current_jobs(conn: psycopg.Connection) -> list[Job]:
    names = [f.name for f in fields(Job)]
    rows = conn.execute(f"SELECT {', '.join(names)} FROM jobs WHERE is_active ORDER BY source_id").fetchall()
    return [Job(**{**row, "functions": tuple(row["functions"]), "industries": tuple(row["industries"]),
                   "skills": tuple(row["skills"])}) for row in rows]


def rehash(job: Job) -> Job:
    """Recompute content_hash and skills after changing a job's fields."""
    job = replace(job, content_hash=compute_content_hash({name: getattr(job, name) for name in HASHED_FIELDS}))
    return with_skills(job)


def edit(job: Job, kind: str) -> Job:
    """One realistic edit. Title and remote edits change the embedded text; salary and
    description-tail edits change the content but usually not what we embed."""
    if kind == "title":
        title = job.title.removeprefix("Senior ") if job.title.startswith("Senior ") else f"Senior {job.title}"
        job = replace(job, title=title)
    elif kind == "salary":
        if job.salary_max:
            job = replace(job, salary_min=round(job.salary_min * 1.05), salary_max=round(job.salary_max * 1.05))
        else:
            job = replace(job, salary_min=60000, salary_max=75000, salary_currency="USD")
    elif kind == "remote":
        job = replace(job, remote=not job.remote)
    else:  # description_tail
        job = replace(job, description=job.description + "\n\nUpdate: applications are now reviewed weekly.")
    return rehash(job)


def new_postings(conn: psycopg.Connection, raw_dir: Path, count: int, seed: int, posted_at: datetime) -> list[Job]:
    """Postings from the Kaggle CSV that have never been loaded, dated `posted_at`."""
    known = {row["source_id"] for row in conn.execute("SELECT source_id FROM jobs")}
    lookups = ingest.load_lookups(raw_dir)
    rows = (r for r in ingest.read_postings(raw_dir / "postings.csv") if ingest.clean_id(r["job_id"]) not in known)
    picked = ingest.reservoir_sample(ingest.unique_jobs(rows, lookups, Counter()), count, seed)
    return [rehash(replace(job, posted_at=posted_at)) for job in picked]


def simulate(conn: psycopg.Connection, raw_dir: Path, plan: ChurnPlan) -> tuple[list[Job], dict]:
    """Tomorrow's snapshot, made from today's active jobs. The same seed gives the same day."""
    rng = random.Random(plan.seed)
    today = current_jobs(conn)
    removed = set(rng.sample([j.source_id for j in today], round(len(today) * plan.remove_fraction)))
    staying = [j for j in today if j.source_id not in removed]
    to_edit = set(rng.sample([j.source_id for j in staying], round(len(staying) * plan.edit_fraction)))

    kinds: Counter = Counter()
    snapshot = []
    for job in staying:
        if job.source_id in to_edit:
            kind = rng.choice(EDIT_KINDS)
            kinds[kind] += 1
            job = edit(job, kind)
        snapshot.append(job)

    newest = max((j.posted_at for j in today if j.posted_at), default=datetime.now().astimezone())
    added = new_postings(conn, raw_dir, plan.add, plan.seed, posted_at=newest + timedelta(days=1))
    snapshot += added
    plan_summary = {"kept": len(staying), "removed": len(removed), "edited": dict(kinds), "added": len(added)}
    return snapshot, plan_summary


# ---------- applying a snapshot ----------

def apply_snapshot(
    conn: psycopg.Connection, jobs: Iterable[Job], max_removed_fraction: float = MAX_REMOVED_FRACTION
) -> dict[str, int]:
    """Bring the jobs table in line with the snapshot, in one transaction. Returns counts."""
    snapshot = {job.source_id: job for job in jobs}
    with conn.transaction():
        existing = {
            row["source_id"]: row
            for row in conn.execute("SELECT source_id, content_hash, skills, is_active FROM jobs")
        }
        active = {sid for sid, row in existing.items() if row["is_active"]}
        removed = sorted(active - snapshot.keys())
        if active and len(removed) / len(active) > max_removed_fraction:
            raise SuspiciousSnapshot(
                f"snapshot would remove {len(removed)} of {len(active)} active jobs "
                f"(more than {max_removed_fraction:.0%}); refusing. Check the feed.")

        added, updated, same = [], [], []
        for sid, job in snapshot.items():
            row = existing.get(sid)
            if row is None:
                added.append(job)
            elif (row["content_hash"], tuple(row["skills"])) != (job.content_hash, job.skills):
                updated.append(job)
            else:
                same.append(sid)
        reactivated = [sid for sid in same if not existing[sid]["is_active"]]

        with conn.cursor() as cur:
            if added:
                cur.executemany(ingest.INSERT_SQL, [ingest.job_params(j) for j in added])
            if updated:  # UPDATE_SQL also marks the job active and seen now
                cur.executemany(ingest.UPDATE_SQL, [ingest.job_params(j) for j in updated])
        conn.execute(
            "UPDATE jobs SET last_seen_at = now(), is_active = true, removed_at = NULL WHERE source_id = ANY(%s)",
            (same,))
        conn.execute(
            "UPDATE jobs SET is_active = false, removed_at = now() WHERE source_id = ANY(%s)", (removed,))

    return {
        "snapshot_size": len(snapshot),
        "added": len(added),
        "updated": len(updated),
        "reactivated": len(reactivated),
        "removed": len(removed),
        "unchanged": len(same) - len(reactivated),
    }


def prune_reasons(conn: psycopg.Connection) -> int:
    """Drop cached reasons for postings whose content no longer exists among active jobs."""
    return conn.execute(
        """DELETE FROM reasons_cache r
           WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.is_active AND j.content_hash = r.content_hash)"""
    ).rowcount


def run_refresh(
    conn: psycopg.Connection,
    jobs: Iterable[Job],
    snapshot_name: str,
    embed: embeddings.Embedder = embeddings.embed_texts,
    max_removed_fraction: float = MAX_REMOVED_FRACTION,
) -> dict:
    """Apply a snapshot, re-embed what changed, prune stale reasons, and log the run."""
    started = time.perf_counter()
    run_id = conn.execute(
        "INSERT INTO refresh_runs (snapshot, status) VALUES (%s, 'running') RETURNING id", (snapshot_name,)
    ).fetchone()["id"]
    try:
        counts = apply_snapshot(conn, jobs, max_removed_fraction)
        applied = time.perf_counter()
        embedded = embeddings.embed_pending(conn, embed)["embedded"]
        embedded_at = time.perf_counter()
        pruned = prune_reasons(conn)
    except Exception as error:
        conn.execute(
            "UPDATE refresh_runs SET status = 'failed', finished_at = now(), error = %s WHERE id = %s",
            (f"{type(error).__name__}: {error}", run_id))
        log.error("refresh run %d failed: %s", run_id, error)
        raise

    result = {
        **counts,
        "embedded": embedded,
        "reasons_pruned": pruned,
        "apply_ms": round((applied - started) * 1000),
        "embed_ms": round((embedded_at - applied) * 1000),
        "total_ms": round((time.perf_counter() - started) * 1000),
    }
    conn.execute(
        """UPDATE refresh_runs SET status = 'ok', finished_at = now(),
               snapshot_size = %(snapshot_size)s, added = %(added)s, updated = %(updated)s,
               reactivated = %(reactivated)s, removed = %(removed)s, unchanged = %(unchanged)s,
               embedded = %(embedded)s, reasons_pruned = %(reasons_pruned)s,
               apply_ms = %(apply_ms)s, embed_ms = %(embed_ms)s, total_ms = %(total_ms)s
           WHERE id = %(id)s""",
        {**result, "id": run_id},
    )
    log.info("refresh run %d (%s) %s", run_id, snapshot_name, result)
    return {"run_id": run_id, **result}


# ---------- command line ----------

def main() -> None:
    from matchwise.config import get_settings, setup_logging

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("simulate", "day"):
        p = sub.add_parser(name)
        p.add_argument("--seed", type=int, required=True)
        p.add_argument("--add", type=int, default=ChurnPlan.add)
        p.add_argument("--edit", type=float, default=ChurnPlan.edit_fraction)
        p.add_argument("--remove", type=float, default=ChurnPlan.remove_fraction)
        p.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
        p.add_argument("--out", type=Path, help="snapshot file (default data/snapshots/day-<seed>.jsonl)")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("snapshot", type=Path)
    apply_parser.add_argument("--force", action="store_true", help="apply even if it removes many jobs")
    sub.add_parser("runs")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)
    db.migrate(settings.database_url)
    with db.connect(settings.database_url) as conn:
        if args.command in ("simulate", "day"):
            plan = ChurnPlan(seed=args.seed, add=args.add, edit_fraction=args.edit, remove_fraction=args.remove)
            snapshot, summary = simulate(conn, args.raw_dir, plan)
            out = args.out or Path(f"data/snapshots/day-{args.seed}.jsonl")
            write_snapshot(out, snapshot)
            print(f"simulated {out}: {summary}")
            if args.command == "day":
                print(run_refresh(conn, snapshot, out.name))
        elif args.command == "apply":
            limit = 1.0 if args.force else MAX_REMOVED_FRACTION
            print(run_refresh(conn, read_snapshot(args.snapshot), args.snapshot.name, max_removed_fraction=limit))
        else:
            for row in conn.execute(
                """SELECT id, snapshot, status, snapshot_size, added, updated, reactivated, removed, unchanged,
                          embedded, reasons_pruned, apply_ms, embed_ms, total_ms
                   FROM refresh_runs ORDER BY id DESC LIMIT 10"""):
                print(row)


if __name__ == "__main__":
    main()
