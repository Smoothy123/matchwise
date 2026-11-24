"""Turn postings into vectors with all-MiniLM-L6-v2 and keep them up to date.

    python -m matchwise.embeddings      # embed every active job whose text changed

Each job is embedded from a short "job card" (see job_card). The sha256 of that
exact text is stored in jobs.embedded_hash, so a job needs (re-)embedding
exactly when the hash of its current card differs from the stored one. A run
that crashes halfway simply carries on from where it stopped next time.
"""

import hashlib
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache

import numpy as np
import psycopg

from matchwise import db
from matchwise.skills import strip_boilerplate

log = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONS = 384

# MiniLM reads at most 256 word pieces and silently drops the rest. Cutting the
# description ourselves (sized so almost every card fits) means edits the model
# would never see don't change the card, so they don't trigger re-embedding.
DESCRIPTION_CHARS = 800

ENCODE_BATCH = 64   # texts per forward pass of the model
WRITE_BATCH = 256   # rows per database transaction

SENIORITY_LABELS = {
    "intern": "Internship",
    "entry": "Entry level",
    "associate": "Associate",
    "mid_senior": "Mid-senior level",
    "director": "Director",
    "executive": "Executive",
}

# Anything that maps a list of texts to an (n, 384) array of unit vectors.
# Production uses embed_texts; tests pass a fast fake.
Embedder = Callable[[Sequence[str]], np.ndarray]


def job_card(job: Mapping) -> str:
    """The text we embed for a posting: what the job is first, then the start of the description."""
    facts = [
        SENIORITY_LABELS.get(job["seniority"]),
        job["employment_type"],
        job["location"],
        "Remote" if job["remote"] else None,
    ]
    lines = [
        job["title"],
        " · ".join(f for f in facts if f),
        "Functions: " + ", ".join(job["functions"]) if job["functions"] else "",
        "Skills: " + ", ".join(job["skills"]) if job["skills"] else "",
        shorten(strip_boilerplate(job["description"]), DESCRIPTION_CHARS),
    ]
    return "\n".join(line for line in lines if line)


def shorten(text: str, limit: int) -> str:
    """Collapse whitespace and cut to at most `limit` characters, on a word boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def card_hash(card: str) -> str:
    return hashlib.sha256(card.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _model():
    # Imported here, not at the top: loading torch takes seconds, and most of
    # the app (and most tests) never needs the model.
    from sentence_transformers import SentenceTransformer

    started = time.perf_counter()
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    log.info("loaded %s in %.1fs", MODEL_NAME, time.perf_counter() - started)
    return model


def embed_texts(texts: Sequence[str]) -> np.ndarray:
    """One unit-length vector per text, so cosine similarity is just a dot product."""
    return _model().encode(
        list(texts),
        batch_size=ENCODE_BATCH,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )


CARD_COLUMNS_SQL = """
SELECT id, title, seniority, employment_type, location, remote, functions, skills,
       description, embedded_hash
FROM jobs
WHERE is_active
ORDER BY id
"""


def embed_pending(conn: psycopg.Connection, embed: Embedder = embed_texts) -> dict[str, float]:
    """Embed every active job whose card text changed since it was last embedded."""
    started = time.perf_counter()
    rows = conn.execute(CARD_COLUMNS_SQL).fetchall()
    pending = []
    for row in rows:
        card = job_card(row)
        digest = card_hash(card)
        if digest != row["embedded_hash"]:
            pending.append((row["id"], card, digest))

    for start in range(0, len(pending), WRITE_BATCH):
        batch = pending[start : start + WRITE_BATCH]
        vectors = embed([card for _, card, _ in batch])
        with conn.transaction():  # each batch is saved on its own, so progress survives a crash
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE jobs SET embedding = %s, embedded_hash = %s WHERE id = %s",
                    [(vector, digest, job_id) for (job_id, _, digest), vector in zip(batch, vectors)],
                )
        log.info("embedded %d/%d", start + len(batch), len(pending))

    result = {
        "checked": len(rows),
        "embedded": len(pending),
        "seconds": round(time.perf_counter() - started, 1),
    }
    log.info("embedding done %s", result)
    return result


def main() -> None:
    from matchwise.config import get_settings, setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)
    db.migrate(settings.database_url)
    with db.connect(settings.database_url) as conn:
        embed_pending(conn)


if __name__ == "__main__":
    main()
