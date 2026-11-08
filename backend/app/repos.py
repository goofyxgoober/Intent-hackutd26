"""Connected repositories and their intent graphs, stored per user and repo."""
import base64
import json
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from . import db
from .auth import require_session
from .config import settings
from .github import check_ref, compare_refs, list_commits
from .github_client import gh
from .models import IntentGraphIn, IntentNode
from .sessions import Session

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
            "full_name": self.full_name,
            "default_branch": self.default_branch,
            "last_synced_sha": self.last_synced_sha,
            "connected_at": self.connected_at,
        }


def connected_repo(owner: str, repo: str, session: Session = Depends(require_session)) -> ConnectedRepo:
    row = db.fetch_repo(session.user_id, f"{owner}/{repo}")
    if row is None:
        raise HTTPException(404, f"{owner}/{repo} is not connected. POST /api/repos/{owner}/{repo}/connect first.")
    return ConnectedRepo(row, session)


def _node_out(row: sqlite3.Row) -> dict:
    return {
        **json.loads(row["data"]),
        "version": row["version"],
        "stale": bool(row["stale"]),
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------- repos


@router.get("")
def list_connected(session: Session = Depends(require_session)) -> "list[dict]":
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT r.*, (SELECT COUNT(*) FROM intent_nodes n WHERE n.repo_id = r.id) AS intent_count
               FROM repos r WHERE r.user_id = ? ORDER BY r.connected_at DESC""",
            (session.user_id,),
        ).fetchall()
    return [
        {**ConnectedRepo(r, session).public(), "intent_count": r["intent_count"]} for r in rows
    ]


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
    return {**ConnectedRepo(row, session).public(), "can_push": bool(perms.get("push"))}


@router.get("/{owner}/{repo}")
def get_connected(repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    return repo.public()


@router.delete("/{owner}/{repo}", status_code=204)
def disconnect_repo(repo: ConnectedRepo = Depends(connected_repo)) -> Response:
    """Forget the repo and every intent stored for it."""
    with db.connect() as conn:
        conn.execute("DELETE FROM repos WHERE id = ?", (repo.id,))
    return Response(status_code=204)


# ---------------------------------------------------------------- changes


async def _changes(repo: ConnectedRepo, ref: Optional[str]) -> dict:
    token = repo.session.access_token
    head_ref = check_ref(ref or repo.default_branch)
    head = await gh(token, "GET", f"/repos/{repo.full_name}/commits/{head_ref}")
    head_sha = head["sha"]

    if repo.last_synced_sha is None:
        return {"base": None, "head": head_sha, "initial_sync": True, "commits": [], "files": [], "affected_intents": []}
    if repo.last_synced_sha == head_sha:
        return {"base": head_sha, "head": head_sha, "initial_sync": False, "commits": [], "files": [], "affected_intents": []}

    cmp = await compare_refs(token, repo.full_name, repo.last_synced_sha, head_sha)
    files = cmp["files"]
    paths = {f["path"] for f in files} | {f["previous_path"] for f in files if f["previous_path"]}
    with db.connect() as conn:
        affected = db.intents_for_paths(conn, repo.id, paths)
    return {
        "base": repo.last_synced_sha,
        "head": head_sha,
        "initial_sync": False,
        "commits": cmp["commits"],
        "truncated": cmp["truncated"],
        "files": files,
        "affected_intents": affected,
    }


@router.get("/{owner}/{repo}/changes")
async def preview_changes(ref: Optional[str] = None, repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """Files modified since the last sync, and the intents that cover them. Changes nothing."""
    return await _changes(repo, ref)


@router.post("/{owner}/{repo}/sync")
async def sync_repo(ref: Optional[str] = None, repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """Accept the current head as synced; intents on modified files are flagged stale."""
    result = await _changes(repo, ref)
    paths = {f["path"] for f in result["files"]} | {
        f["previous_path"] for f in result["files"] if f["previous_path"]
    }
    with db.connect() as conn:
        result["stale_marked"] = db.mark_stale(conn, repo.id, paths)
        conn.execute("UPDATE repos SET last_synced_sha = ? WHERE id = ?", (result["head"], repo.id))
    return result


@router.get("/{owner}/{repo}/activity")
def recent_activity(limit: int = 50, repo: ConnectedRepo = Depends(connected_repo)) -> "list[dict]":
    """File changes pushed to the default branch, as received by the webhook."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT commit_sha, path, status, received_at FROM file_events WHERE repo_id = ? ORDER BY id DESC LIMIT ?",
            (repo.id, max(1, min(limit, 500))),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- intents


def _sync_dependency_edges(conn: sqlite3.Connection, repo_id: int, node: IntentNode) -> None:
    deps = list(dict.fromkeys(node.downstream_dependencies))
    marks = ",".join("?" * len(deps)) or "NULL"
    conn.execute(
        f"DELETE FROM intent_edges WHERE repo_id = ? AND source = ? AND target NOT IN ({marks})",
        (repo_id, node.node_id, *deps),
    )
    for target in deps:
        conn.execute(
            """INSERT INTO intent_edges (repo_id, source, target, relation)
               SELECT ?, ?, ?, 'depends_on' WHERE NOT EXISTS
               (SELECT 1 FROM intent_edges WHERE repo_id = ? AND source = ? AND target = ?)""",
            (repo_id, node.node_id, target, repo_id, node.node_id, target),
        )


@router.get("/{owner}/{repo}/intents")
def list_intents(
    source_file: Optional[str] = None, stale: Optional[bool] = None,
    repo: ConnectedRepo = Depends(connected_repo),
) -> "list[dict]":
    sql, args = "SELECT * FROM intent_nodes WHERE repo_id = ?", [repo.id]
    if source_file is not None:
        sql, args = sql + " AND source_file = ?", args + [source_file]
    if stale is not None:
        sql, args = sql + " AND stale = ?", args + [int(stale)]
    with db.connect() as conn:
        rows = conn.execute(sql + " ORDER BY node_id", args).fetchall()
    return [_node_out(r) for r in rows]


@router.get("/{owner}/{repo}/intents/{node_id}")
def get_intent(node_id: str, repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM intent_nodes WHERE repo_id = ? AND node_id = ?", (repo.id, node_id)
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"No intent named {node_id}")
    return _node_out(row)


@router.put("/{owner}/{repo}/intents/{node_id}")
def put_intent(
    node_id: str, node: IntentNode, expected_version: Optional[int] = None,
    repo: ConnectedRepo = Depends(connected_repo),
) -> dict:
    """Create or replace one intent. Pass expected_version to avoid overwriting someone else's edit."""
    if node.node_id != node_id:
        raise HTTPException(422, "node_id in the body must match the URL")
    now = time.time()
    with db.connect() as conn:
        current = conn.execute(
            "SELECT version FROM intent_nodes WHERE repo_id = ? AND node_id = ?", (repo.id, node_id)
        ).fetchone()
        if expected_version is not None:
            actual = current["version"] if current else 0
            if actual != expected_version:
                raise HTTPException(
                    409, f"{node_id} is at version {actual}, not {expected_version}. Reload and retry."
                )
        data = node.model_dump_json()
        if current:
            conn.execute(
                """UPDATE intent_nodes SET source_file = ?, data = ?, version = version + 1,
                   stale = 0, updated_at = ? WHERE repo_id = ? AND node_id = ?""",
                (node.source_file, data, now, repo.id, node_id),
            )
        else:
            conn.execute(
                """INSERT INTO intent_nodes (repo_id, node_id, source_file, data, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (repo.id, node_id, node.source_file, data, now),
            )
        _sync_dependency_edges(conn, repo.id, node)
        row = conn.execute(
            "SELECT * FROM intent_nodes WHERE repo_id = ? AND node_id = ?", (repo.id, node_id)
        ).fetchone()
    return _node_out(row)


@router.get("/{owner}/{repo}/intents/{node_id}/history")
async def intent_history(
    node_id: str, limit: int = 20, repo: ConnectedRepo = Depends(connected_repo)
) -> dict:
    """Commits that touched the source file behind this intent."""
    node = get_intent(node_id, repo)
    commits = await list_commits(
        repo.session.access_token, repo.full_name, repo.default_branch, node["source_file"], limit
    )
    return {"node_id": node_id, "source_file": node["source_file"], "commits": commits}


@router.delete("/{owner}/{repo}/intents/{node_id}", status_code=204)
def delete_intent(node_id: str, repo: ConnectedRepo = Depends(connected_repo)) -> Response:
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM intent_nodes WHERE repo_id = ? AND node_id = ?", (repo.id, node_id)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"No intent named {node_id}")
        conn.execute(
            "DELETE FROM intent_edges WHERE repo_id = ? AND (source = ? OR target = ?)",
            (repo.id, node_id, node_id),
        )
    return Response(status_code=204)


# ---------------------------------------------------------------- graph


def _graph(repo: ConnectedRepo) -> dict:
    with db.connect() as conn:
        nodes = conn.execute(
            "SELECT * FROM intent_nodes WHERE repo_id = ? ORDER BY node_id", (repo.id,)
        ).fetchall()
        edges = conn.execute(
            "SELECT source, target, relation FROM intent_edges WHERE repo_id = ? ORDER BY source, target",
            (repo.id,),
        ).fetchall()
    return {
        "repo_name": repo.full_name,
        "nodes": [n["node_id"] for n in nodes],
        "edges": [dict(e) for e in edges],
        "intent_nodes": [_node_out(n) for n in nodes],
    }


@router.get("/{owner}/{repo}/graph")
def get_graph(repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """The IntentGraph (CONTEXT.md 5.2), plus full node details under intent_nodes."""
    return _graph(repo)


@router.put("/{owner}/{repo}/graph")
def replace_graph(graph: IntentGraphIn, repo: ConnectedRepo = Depends(connected_repo)) -> dict:
    """Replace the whole graph in one transaction, e.g. after the intent engine re-parses the repo."""
    ids = [n.node_id for n in graph.nodes]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Duplicate node_id in nodes")
    now = time.time()
    with db.connect() as conn:
        conn.execute("DELETE FROM intent_edges WHERE repo_id = ?", (repo.id,))
        conn.execute("DELETE FROM intent_nodes WHERE repo_id = ?", (repo.id,))
        for node in graph.nodes:
            conn.execute(
                """INSERT INTO intent_nodes (repo_id, node_id, source_file, data, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (repo.id, node.node_id, node.source_file, node.model_dump_json(), now),
            )
        for edge in graph.edges:
            conn.execute(
                "INSERT OR IGNORE INTO intent_edges (repo_id, source, target, relation) VALUES (?, ?, ?, ?)",
                (repo.id, edge.source, edge.target, edge.relation),
            )
        for node in graph.nodes:
            _sync_dependency_edges(conn, repo.id, node)
    return _graph(repo)


@router.post("/{owner}/{repo}/intents/export")
async def export_intents(
    branch: Optional[str] = None, repo: ConnectedRepo = Depends(connected_repo)
) -> dict:
    """Commit the intent graph to the repo as JSON, on its own branch so main is untouched."""
    token = repo.session.access_token
    info = await gh(token, "GET", f"/repos/{repo.full_name}")
    if not (info.get("permissions") or {}).get("push"):
        raise HTTPException(403, f"Your GitHub account can't push to {repo.full_name}")

    branch = branch or settings.intent_branch
    if await gh(token, "GET", f"/repos/{repo.full_name}/git/ref/heads/{branch}", allow_404=True) is None:
        base = await gh(token, "GET", f"/repos/{repo.full_name}/git/ref/heads/{repo.default_branch}")
        await gh(
            token, "POST", f"/repos/{repo.full_name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base["object"]["sha"]},
        )

    graph = _graph(repo)
    document = {
        "repo_name": graph["repo_name"],
        "nodes": [
            {k: v for k, v in n.items() if k not in ("version", "stale", "updated_at")}
            for n in graph["intent_nodes"]
        ],
        "edges": graph["edges"],
    }
    path = settings.intent_file_path
    existing = await gh(
        token, "GET", f"/repos/{repo.full_name}/contents/{path}", params={"ref": branch}, allow_404=True
    )
    body = {
        "message": f"Update intent graph ({len(document['nodes'])} nodes)",
        "content": base64.b64encode(json.dumps(document, indent=2).encode()).decode(),
        "branch": branch,
    }
    if existing:
        body["sha"] = existing["sha"]
    result = await gh(token, "PUT", f"/repos/{repo.full_name}/contents/{path}", json=body)
    return {
        "branch": branch,
        "path": path,
        "commit_sha": result["commit"]["sha"],
        "html_url": result["content"]["html_url"],
    }
