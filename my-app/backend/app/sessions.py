"""In-memory session store.

GitHub access tokens never leave the backend; the browser only holds an
opaque, httpOnly session id. Sessions end when the backend restarts; users and
their intent data persist in SQLite.
"""
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

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
    _sessions[sid] = Session(access_token=access_token, user=user, user_id=user_id)
    return sid


def get_session(sid: Optional[str]) -> Optional[Session]:
    if not sid:
        return None
    session = _sessions.get(sid)
    if session and session.expired:
        _sessions.pop(sid, None)
        return None
    return session


def delete_session(sid: Optional[str]) -> None:
    if sid:
        _sessions.pop(sid, None)
