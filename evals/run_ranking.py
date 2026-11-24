"""Compare the ranking versions on your labels and print the README table.

    python -m evals.run_ranking

Every version ranks for the same frozen preferences (profiles_extracted.json)
against the same database, and is scored against the same labels (labels.jsonl).
Writes results/ranking.md (the table) and results/ranking.json (per persona).
"""

import json
from collections.abc import Callable
from datetime import datetime, timezone

from evals.data import GOOD, LABELS_JSONL, RESULTS_DIR, Label, load_extracted, load_labels, read_jsonl
from evals.metrics import mean_and_ci, ndcg_at_k, precision_at_k, rate_at_k, recall_at_k
from matchwise import db, embeddings
from matchwise.ranking import Mode, match

VERSIONS: dict[str, Mode] = {
    "vector only": Mode.vector,
    "vector + filters": Mode.vector_filters,
    "vector + filters + re-ranking": Mode.full,
}
METRICS = ("P@5", "R@20", "nDCG@10", "violations@10", "judged@10")


def score_ranking(ranked: list[str], labels: list[Label]) -> dict[str, float | None]:
    """All metrics for one persona's ranking."""
    grades = {lab.source_id: lab.grade for lab in labels}
    good = {lab.source_id for lab in labels if lab.grade >= GOOD}
    breaks = {lab.source_id for lab in labels if lab.violation}
    return {
        "P@5": precision_at_k(ranked, good, 5),
        "R@20": recall_at_k(ranked, good, 20),
        "nDCG@10": ndcg_at_k(ranked, grades, 10),
        "violations@10": rate_at_k(ranked, breaks, 10),
        "judged@10": rate_at_k(ranked, set(grades), 10),
    }


def summarise(per_profile: dict[str, dict[str, float | None]]) -> dict[str, tuple[float, float, float, int]]:
    """Mean, 95% interval and number of personas for each metric (skipping undefined values)."""
    out = {}
    for metric in METRICS:
        values = [scores[metric] for scores in per_profile.values() if scores[metric] is not None]
        out[metric] = (*mean_and_ci(values), len(values))
    return out


def markdown_table(results: dict[str, dict[str, tuple[float, float, float, int]]]) -> str:
    lines = ["| Version | " + " | ".join(METRICS) + " |", "|---|" + "---|" * len(METRICS)]
    for version, summary in results.items():
        cells = []
        for metric in METRICS:
            mean, low, high, _ = summary[metric]
            cells.append(f"{mean:.2f}" if metric in ("violations@10", "judged@10") else
                         f"{mean:.2f} ({low:.2f}–{high:.2f})")
        lines.append(f"| {version} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def evaluate(rank: Callable[[str, Mode], list[str]], profile_ids: list[str],
             labels: dict[tuple[str, str], Label], versions: dict[str, Mode] = VERSIONS) -> dict:
    """rank(profile_id, mode) -> ranked source ids. Returns per-version, per-persona scores."""
    by_profile: dict[str, list[Label]] = {}
    for (profile, _), label in labels.items():
        by_profile.setdefault(profile, []).append(label)
    return {
        version: {pid: score_ranking(rank(pid, mode), by_profile.get(pid, [])) for pid in profile_ids}
        for version, mode in versions.items()
    }


def main() -> None:
    from matchwise.config import get_settings, setup_logging

    settings = get_settings()
    setup_logging("WARNING")
    prefs = load_extracted()
    labels = load_labels()
    labelled_profiles = sorted({profile for profile, _ in labels})
    with db.connect(settings.database_url) as conn:
        def rank(profile_id: str, mode: Mode) -> list[str]:
            return [m["source_id"] for m in match(conn, prefs[profile_id], embeddings.embed_texts, mode=mode, limit=20)]

        per_version = evaluate(rank, labelled_profiles, labels)
        state = conn.execute(
            """SELECT count(*) FILTER (WHERE is_active) AS active_jobs,
                      (SELECT max(id) FROM refresh_runs WHERE status = 'ok') AS last_refresh_run
               FROM jobs""").fetchone()

    summaries = {version: summarise(scores) for version, scores in per_version.items()}
    table = markdown_table(summaries)
    good = sum(1 for lab in labels.values() if lab.grade >= GOOD)
    # Who made the labels belongs next to the numbers: a person, or a model (named).
    labellers = ", ".join(sorted({r.get("labeller", "human") for r in read_jsonl(LABELS_JSONL)}))
    note = (f"{len(labelled_profiles)} personas, {len(labels)} labelled postings ({good} good matches), "
            f"labelled by: {labellers}. "
            f"Database: {state['active_jobs']} active jobs after refresh run {state['last_refresh_run']}. "
            "Brackets: 95% bootstrap interval over personas.")
    print(table + "\n\n" + note)

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "ranking.md").write_text(table + "\n\n" + note + "\n")
    (RESULTS_DIR / "ranking.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note, "per_version": per_version,
    }, indent=1) + "\n")


if __name__ == "__main__":
    main()
