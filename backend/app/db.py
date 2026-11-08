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
CREATE TABLE IF NOT EXISTS intent_nodes (
    repo_id     INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    node_id     TEXT NOT NULL,
    source_file TEXT NOT NULL,
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    stale       INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (repo_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_intent_source ON intent_nodes(repo_id, source_file);
CREATE TABLE IF NOT EXISTS intent_edges (
    repo_id  INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    source   TEXT NOT NULL,
    target   TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (repo_id, source, target, relation)
);
CREATE TABLE IF NOT EXISTS file_events (
    id          INTEGER PRIMARY KEY,
    repo_id     INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    commit_sha  TEXT NOT NULL,
    path        TEXT NOT NULL,
    status      TEXT NOT NULL,
    received_at REAL NOT NULL
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


def mark_stale(conn: sqlite3.Connection, repo_id: int, paths: "set[str]") -> int:
    if not paths:
        return 0
    marks = ",".join("?" * len(paths))
    cur = conn.execute(
        f"UPDATE intent_nodes SET stale = 1 WHERE repo_id = ? AND source_file IN ({marks})",
        (repo_id, *paths),
    )
    return cur.rowcount


def intents_for_paths(conn: sqlite3.Connection, repo_id: int, paths: "set[str]") -> "list[str]":
    if not paths:
        return []
    marks = ",".join("?" * len(paths))
    rows = conn.execute(
        f"SELECT node_id FROM intent_nodes WHERE repo_id = ? AND source_file IN ({marks}) ORDER BY node_id",
        (repo_id, *paths),
    ).fetchall()
    return [r["node_id"] for r in rows]


def fetch_repo(user_id: int, full_name: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM repos WHERE user_id = ? AND full_name = ?", (user_id, full_name)
        ).fetchone()
