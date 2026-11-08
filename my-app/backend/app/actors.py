"""Who is making a request: the signed-in user, or an agent holding an API key.

The spec's permission matrix (section 7) is enforced against these roles:
  user         a person signed in with GitHub
  builder      Hypothesis-editing agents: Intent Builder, Test Author, Remake Agent
  test_runner  the Test Runner (append-only access to results)
  engine       Annotator, Jev, link builder, Spec Compiler
"""
import hmac
import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import Depends, HTTPException, Request

from . import db
from .config import settings
from .sessions import Session, get_session

AGENT_ROLES = ("builder", "test_runner", "engine")


@dataclass
class Actor:
    kind: str  # "user" or one of AGENT_ROLES
    name: str  # GitHub login, or the agent's self-reported name
    user_id: Optional[int] = None
    session: Optional[Session] = None

    @property
    def is_user(self) -> bool:
        return self.kind == "user"

    def provenance(self, extra: Optional[dict] = None) -> dict:
        out = {"kind": "user" if self.is_user else "agent", "role": self.kind, "actor": self.name}
        if extra:
            out.update({k: v for k, v in extra.items() if k in ("run_id", "commit_range", "via")})
        return out


def _agent_keys() -> Dict[str, str]:
    keys = {}
    for pair in settings.agent_keys.split(","):
        role, _, key = pair.strip().partition(":")
        if role in AGENT_ROLES and len(key) >= 16:
            keys[key] = role
    return keys


def actor_from_credentials(session_id: Optional[str], bearer: Optional[str], agent_name: Optional[str]) -> Actor:
    if bearer:
        for key, role in _agent_keys().items():
            if hmac.compare_digest(bearer, key):
                return Actor(kind=role, name=(agent_name or role)[:64])
        raise HTTPException(401, "Unknown agent key")
    session = get_session(session_id)
    if session is None:
        raise HTTPException(401, "Not authenticated")
    return Actor(kind="user", name=session.user.get("login", "user"), user_id=session.user_id, session=session)


def current_actor(request: Request) -> Actor:
    auth = request.headers.get("Authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    return actor_from_credentials(
        request.cookies.get(settings.session_cookie), bearer, request.headers.get("X-Agent-Name")
    )


@dataclass
class Workspace:
    """One connected repo for one user. Its id is what agents address."""
    id: int
    user_id: int
    full_name: str
    default_branch: str
    last_synced_sha: Optional[str]


def load_workspace(workspace_id: int, actor: Actor) -> Workspace:
    with db.connect() as conn:
        row: Optional[sqlite3.Row] = conn.execute("SELECT * FROM repos WHERE id = ?", (workspace_id,)).fetchone()
    # Users only see their own workspaces; agents are trusted deployment-wide.
    if row is None or (actor.is_user and row["user_id"] != actor.user_id):
        raise HTTPException(404, f"Workspace {workspace_id} not found")
    if actor.session is not None:
        from . import sync  # local import: sync depends on this module

        sync.remember_token(row["id"], actor.session.access_token)
    return Workspace(row["id"], row["user_id"], row["full_name"], row["default_branch"], row["last_synced_sha"])


def workspace_and_actor(workspace_id: int, actor: Actor = Depends(current_actor)) -> "tuple[Workspace, Actor]":
    return load_workspace(workspace_id, actor), actor
