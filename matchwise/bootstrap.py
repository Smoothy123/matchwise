"""Get a database ready to serve: migrate, load the sample if there are no jobs, embed what's missing.

    python -m matchwise.bootstrap

docker-compose runs this as the `init` service before the API starts, so
`docker compose up` is the only command needed. Every step skips work that is
already done, so running it again is cheap (a couple of seconds).
"""

import logging
from pathlib import Path

from matchwise import db, embeddings, ingest

log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
MISSING_DATA = """
No job postings loaded, and {csv} isn't there yet.
Download the dataset (see data/README.md), unzip it into data/raw/, then run
`docker compose up` again (or `docker compose run --rm init`).
The API starts anyway; /health will show 0 jobs until then.
"""


def run(database_url: str, raw_dir: Path = RAW_DIR, limit: int = 5000, seed: int = 42,
        embed: embeddings.Embedder = embeddings.embed_texts) -> dict:
    db.migrate(database_url)
    with db.connect(database_url) as conn:
        jobs = conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
    loaded = 0
    if jobs == 0:
        csv = raw_dir / "postings.csv"
        if not csv.exists():
            log.warning(MISSING_DATA.format(csv=csv))
            return {"status": "no data", "loaded": 0, "embedded": 0}
        loaded = ingest.run(raw_dir, limit, seed, database_url)["inserted"]
    with db.connect(database_url) as conn:
        embedded = embeddings.embed_pending(conn, embed)["embedded"]  # nothing to do = no model load
    result = {"status": "ready", "loaded": loaded, "embedded": embedded}
    log.info("bootstrap %s", result)
    return result


def main() -> None:
    from matchwise.config import get_settings, setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)
    run(settings.database_url)


if __name__ == "__main__":
    main()
