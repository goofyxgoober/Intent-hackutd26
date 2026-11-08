"""SQLite storage for users, connected repos and their intent graphs.

Every row below `users` is scoped to one user and one repo, so two people
connecting the same repository keep separate intent graphs.
"""
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    github_id   INTEGER UNIQUE NOT NULL,
    login       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    last_login  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS repos (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    full_name       TEXT NOT NULL COLLATE NOCASE,
    default_branch  TEXT NOT NULL,
    last_synced_sha TEXT,
    connected_at    REAL NOT NULL,
    UNIQUE (user_id, full_name)
);
CREATE TABLE IF NOT EXISTS push_events (
    id           INTEGER PRIMARY KEY,
    repo_id      INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    before_sha   TEXT NOT NULL,
    after_sha    TEXT NOT NULL,
    forced       INTEGER NOT NULL DEFAULT 0,
    commit_count INTEGER NOT NULL DEFAULT 0,
    messages     TEXT NOT NULL DEFAULT '[]',
    received_at  REAL NOT NULL,
    batch_id     INTEGER
);
CREATE TABLE IF NOT EXISTS sync_batches (
    id          INTEGER PRIMARY KEY,
    repo_id     INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    base_sha    TEXT,
    head_sha    TEXT NOT NULL,
    status      TEXT NOT NULL,
    source      TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL,
    reviewed_at REAL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_user(github_id: int, login: str) -> int:
    now = time.time()
    with connect() as conn:
        conn.execute(
            """INSERT INTO users (github_id, login, created_at, last_login) VALUES (?, ?, ?, ?)
               ON CONFLICT(github_id) DO UPDATE SET login = excluded.login, last_login = excluded.last_login""",
            (github_id, login, now, now),
        )
        return conn.execute("SELECT id FROM users WHERE github_id = ?", (github_id,)).fetchone()["id"]


def fetch_repo(user_id: int, full_name: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM repos WHERE user_id = ? AND full_name = ?", (user_id, full_name)
        ).fetchone()
