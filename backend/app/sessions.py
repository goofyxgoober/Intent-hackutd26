"""In-memory session store.

GitHub access tokens never leave the backend; the browser only holds an
opaque, httpOnly session id. Swap for SQLite/Redis if sessions must survive
restarts.
"""
import secrets
import time
from typing import Optional
from dataclasses import dataclass, field

from .config import settings


@dataclass
class Session:
    access_token: str
    user: dict
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > settings.session_ttl_seconds


_sessions: dict[str, Session] = {}


def create_session(access_token: str, user: dict) -> str:
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = Session(access_token=access_token, user=user)
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
