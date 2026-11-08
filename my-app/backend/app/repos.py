"""Connected repositories. Each one is a workspace with its own intent folder."""
import sqlite3
import time
from typing import Optional

import json
from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect

from . import db, events, graph_view, sync
from .auth import require_session
from .github import check_ref, compare_refs
from .github_client import gh
from .intent.store import IntentStore
from .config import settings
from .sessions import Session, get_session

router = APIRouter(prefix="/api/repos", tags=["repos"])


class ConnectedRepo:
    def __init__(self, row: sqlite3.Row, session: Session):
        self.id: int = row["id"]
        self.full_name: str = row["full_name"]
        self.default_branch: str = row["default_branch"]
        self.last_synced_sha: Optional[str] = row["last_synced_sha"]
        self.connected_at: float = row["connected_at"]
        self.session = session

    def public(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "default_branch": self.default_branch,
            "last_synced_sha": self.last_synced_sha,
            "connected_at": self.connected_at,
        }


def connected_repo(owner: str, repo: str, session: Session = Depends(require_session)) -> ConnectedRepo:
    row = db.fetch_repo(session.user_id, f"{owner}/{repo}")
    if row is None:
        raise HTTPException(404, f"{owner}/{repo} is not connected. POST /api/repos/{owner}/{repo}/connect first.")
    sync.remember_token(row["id"], session.access_token)
    return ConnectedRepo(row, session)


# ---------------------------------------------------------------- repos


@router.get("")
def list_connected(session: Session = Depends(require_session)) -> "list[dict]":
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM repos WHERE user_id = ? ORDER BY connected_at DESC", (session.user_id,)
        ).fetchall()
    return [ConnectedRepo(r, session).public() for r in rows]


@router.post("/{owner}/{repo}/connect")
async def connect_repo(owner: str, repo: str, session: Session = Depends(require_session)) -> dict:
    """Link a GitHub repo to this user after checking they can read it."""
    info = await gh(session.access_token, "GET", f"/repos/{owner}/{repo}")
    perms = info.get("permissions") or {}
    if not perms.get("pull"):
        raise HTTPException(403, f"Your GitHub account can't read {owner}/{repo}")
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO repos (user_id, full_name, default_branch, connected_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, full_name) DO UPDATE SET default_branch = excluded.default_branch""",
            (session.user_id, info["full_name"], info["default_branch"], time.time()),
        )
    row = db.fetch_repo(session.user_id, info["full_name"])
    sync.remember_token(row["id"], session.access_token)
    return {**ConnectedRepo(row, session).public(), "can_push": bool(perms.get("push"))}


@router.get("/{owner}/{repo}")
def get_connected(repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    return repo.public()


@router.delete("/{owner}/{repo}", status_code=204)
def disconnect_repo(repo: ConnectedRepo = Depends(connected_repo)) -> Response:
    """Forget the repo. Its intent folder stays on disk until removed by hand."""
    with db.connect() as conn:
        conn.execute("DELETE FROM repos WHERE id = ?", (repo.id,))
    return Response(status_code=204)


# ---------------------------------------------------------------- changes


async def _changes(repo: ConnectedRepo, ref: Optional[str]) -> dict:
    """Read-only preview of what a sync would cover."""
    token = repo.session.access_token
    head_ref = check_ref(ref or repo.default_branch)
    head_sha = (await gh(token, "GET", f"/repos/{repo.full_name}/commits/{head_ref}"))["sha"]
    empty = {"commits": [], "files": [], "affected_tenets": [], "changed_leaves": [], "rerun_claims": [], "orphans": []}
    if repo.last_synced_sha is None:
        return {"base": None, "head": head_sha, "initial_sync": True, **empty}
    if repo.last_synced_sha == head_sha:
        return {"base": head_sha, "head": head_sha, "initial_sync": False, **empty}
    cmp = await compare_refs(token, repo.full_name, repo.last_synced_sha, head_sha)
    changed = [f["path"] for f in cmp["files"]] + [f["previous_path"] for f in cmp["files"] if f["previous_path"]]
    deleted = [f["path"] for f in cmp["files"] if f["status"] == "removed"]
    return {
        "base": repo.last_synced_sha,
        "head": head_sha,
        "initial_sync": False,
        "commits": cmp["commits"],
        "files": cmp["files"],
        "truncated": cmp["truncated"],
        **sync._affected(IntentStore(repo.id), changed, deleted),
    }


@router.get("/{owner}/{repo}/changes")
async def preview_changes(ref: Optional[str] = None, repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """Files modified since the last sync, and the intents that cover them. Changes nothing."""
    return await _changes(repo, ref)


@router.post("/{owner}/{repo}/sync")
async def sync_repo(repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """Sync now: snapshot the codebase, then create a batch for Jev and the Test Runner."""
    batch = await sync.process(repo.id, source="manual", token=repo.session.access_token)
    return {**(batch or {}), "synced": True}


@router.post("/{owner}/{repo}/pipeline")
async def run_repo_pipeline(repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """Run full 4-step pipeline: pull code, check commit diffs, create requirements/files, start tenet grilling."""
    token = repo.session.access_token
    full_name = repo.full_name
    events.emit(repo.id, "graph.stage", stage=0, message=f"pulling {full_name} and untangling the AST")
    head = await sync._branch_head(token, full_name, repo.default_branch)
    from . import pipeline
    result = await pipeline.execute_full_pipeline(
        workspace_id=repo.id,
        token=token,
        full_name=full_name,
        head_sha=head,
        base_sha=repo.last_synced_sha,
    )
    events.emit(repo.id, "graph.refresh")
    return result


# ---------------------------------------------------------------- intent graph for the Codebase view


@router.get("/{owner}/{repo}/graph")
def repo_graph(repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """The Functional Intent Graph for this repo. Empty `nodes` until it has been synced once."""
    return graph_view.build_graph(IntentStore(repo.id), repo.full_name)


class _GraphSocket:
    """Adapts workspace events to the graph stream the dashboard reads (docs/graph-frontend-contract.md)."""

    def __init__(self, ws: WebSocket, repo_id: int, full_name: str):
        self.ws, self.repo_id, self.full_name = ws, repo_id, full_name

    async def snapshot(self, stage: int = 1, message: str = "") -> None:
        graph = graph_view.build_graph(IntentStore(self.repo_id), self.full_name)
        await self.ws.send_json({"type": "snapshot", "graph": graph})
        await self.ws.send_json({"type": "status", "stage": stage if graph["nodes"] else 0, "message": message})

    async def send_text(self, raw: str) -> None:  # called by events._broadcast
        event = json.loads(raw)
        kind = event.get("type", "")
        if kind == "graph.stage":
            await self.ws.send_json({"type": "status", "stage": event.get("stage", 0), "message": event.get("message", "")})
        elif kind == "graph.refresh" or kind.startswith(("sync.", "claim.", "tenet.")):
            await self.snapshot(1, "graph refreshed" if kind == "graph.refresh" else kind.replace(".", " "))


@router.websocket("/{owner}/{repo}/graph")
async def repo_graph_stream(websocket: WebSocket, owner: str, repo: str):
    """Snapshot on connect, then a fresh snapshot after every sync or tenet change."""
    session = get_session(websocket.cookies.get(settings.session_cookie))
    row = db.fetch_repo(session.user_id, f"{owner}/{repo}") if session else None
    if row is None:
        await websocket.close(code=4401 if session is None else 4404)
        return
    await websocket.accept()
    sock = _GraphSocket(websocket, row["id"], row["full_name"])
    await events.subscribe(row["id"], sock)  # type: ignore[arg-type]
    try:
        await sock.snapshot(message=f"connected to {row['full_name']}")
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        events.unsubscribe(row["id"], sock)  # type: ignore[arg-type]
