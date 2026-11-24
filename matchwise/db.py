"""Postgres connections and a small migration runner.

Migrations are plain SQL files in migrations/, applied in filename order.
Each file runs in its own transaction and is recorded in schema_migrations,
so running migrate() again only applies new files.
"""

import logging
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Any fixed number works: every process that migrates takes the same lock,
# so two app instances starting together can't apply a migration twice.
MIGRATION_LOCK_ID = 74_110_001


def connect(database_url: str) -> psycopg.Connection:
    """A single connection whose rows come back as dicts.

    Autocommit: each statement commits on its own, and code that needs several
    writes to succeed or fail together wraps them in `with conn.transaction():`.
    register_vector lets numpy arrays go in and out of `vector` columns
    (it needs the extension, so call this only after migrate()).
    """
    conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
    register_vector(conn)
    return conn


def create_pool(database_url: str) -> ConnectionPool:
    """Connection pool for the API (one connection per request, reused)."""
    return ConnectionPool(
        database_url,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row, "autocommit": True},
        configure=register_vector,
        open=True,
    )


def migrate(database_url: str, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations and return the file names that were applied."""
    applied: list[str] = []
    # autocommit=True so each `with conn.transaction()` below is a real transaction.
    with psycopg.connect(database_url, autocommit=True) as conn:
        # Session-level lock; released automatically when the connection closes.
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   name       text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT now()
               )"""
        )
        done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
            log.info("applied migration %s", path.name)
    return applied


if __name__ == "__main__":
    from matchwise.config import get_settings, setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)
    names = migrate(settings.database_url)
    print(f"applied {len(names)} migration(s): {names}")
