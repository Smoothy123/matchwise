"""Paths and loaders for eval data.

Everything is plain TOML / JSON / JSONL in the repo, so every number in the
README can be traced back to files you can read: the personas, the frozen
preferences, the labelling pool, your labels and the judge's scores.
"""

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from matchwise.preferences import Preferences

EVALS_DIR = Path(__file__).resolve().parent
PROFILES_TOML = EVALS_DIR / "profiles.toml"
EXTRACTED_JSON = EVALS_DIR / "profiles_extracted.json"
POOL_JSON = EVALS_DIR / "pool.json"
LABELS_JSONL = EVALS_DIR / "labels.jsonl"
REFERENCE_SCORES_JSONL = EVALS_DIR / "reference_scores.jsonl"  # a person's, or an independent model's, scores
RESULTS_DIR = EVALS_DIR / "results"
JUDGEMENTS_JSONL = RESULTS_DIR / "judgements.jsonl"

GOOD = 2  # grade for "a good match": the threshold for precision and recall


@dataclass(frozen=True)
class EvalProfile:
    id: str
    messages: list[str]


@dataclass(frozen=True)
class Label:
    profile: str
    source_id: str
    grade: int          # 2 = good match, 1 = okay, 0 = not a fit
    violation: bool     # breaks something the person ruled out


def load_profiles(path: Path = PROFILES_TOML) -> list[EvalProfile]:
    data = tomllib.loads(path.read_text())
    return [EvalProfile(id=p["id"], messages=list(p["messages"])) for p in data["profile"]]


def load_extracted(path: Path = EXTRACTED_JSON) -> dict[str, Preferences]:
    data = json.loads(path.read_text())
    return {pid: Preferences.model_validate(prefs) for pid, prefs in data["profiles"].items()}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_labels(path: Path = LABELS_JSONL) -> dict[tuple[str, str], Label]:
    """Latest label per (profile, posting): relabelling appends, and the newest line wins."""
    labels = {}
    for r in read_jsonl(path):
        labels[(r["profile"], r["source_id"])] = Label(r["profile"], r["source_id"], r["grade"], r["violation"])
    return labels
