"""Session store with SQLite persistence and memory cache.

GitHub access tokens are saved in SQLite (intentflow.db) so sessions
survive server restarts and hot reloads without logging users out.
The browser only holds an opaque, httpOnly session id.
"""
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

from . import db
from .config import settings


@dataclass
class Session:
    access_token: str
    user: dict
    user_id: int
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > settings.session_ttl_seconds


_sessions: "dict[str, Session]" = {}


def create_session(access_token: str, user: dict, user_id: int) -> str:
    sid = secrets.token_urlsafe(32)
    s = Session(access_token=access_token, user=user, user_id=user_id)
    _sessions[sid] = s
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions (sid, access_token, user_data, user_id, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (sid, access_token, json.dumps(user), user_id, s.created_at),
            )
    except Exception:
        pass
    return sid


def get_session(sid: Optional[str]) -> Optional[Session]:
    if not sid:
        return None
    session = _sessions.get(sid)
    if session:
        if session.expired:
            delete_session(sid)
            return None
        return session

    # Rehydrate from SQLite if not in memory (e.g. after server reload or restart)
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT access_token, user_data, user_id, created_at FROM sessions WHERE sid = ?",
                (sid,),
            ).fetchone()
            if row:
                created_at = row["created_at"]
                if time.time() - created_at > settings.session_ttl_seconds:
                    delete_session(sid)
                    return None
                user = json.loads(row["user_data"])
                session = Session(
                    access_token=row["access_token"],
                    user=user,
                    user_id=row["user_id"],
                    created_at=created_at,
                )
                _sessions[sid] = session
                return session
    except Exception:
        pass

    return None


def delete_session(sid: Optional[str]) -> None:
    if sid:
        _sessions.pop(sid, None)
        try:
            with db.connect() as conn:
                conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
        except Exception:
            pass
