"""Git sync (spec section 12): pushes are debounced into batches, the codebase
snapshot updates first, then the batch waits for Jev and the Test Runner.

GitHub tokens are kept in memory only, taken from the user's session whenever
they use a workspace. A webhook batch that arrives with no token waits until the
user next opens the workspace or presses sync.
"""
import asyncio
import json
import time
from typing import Dict, List, Optional

from . import codebase, db, events
from .config import settings
from .github import compare_refs
from .github_client import gh
from .intent.store import AXIOM, HYPOTHESIS, IntentStore

_tokens: Dict[int, str] = {}
_timers: Dict[int, asyncio.Task] = {}


def remember_token(workspace_id: int, token: str) -> None:
    _tokens[workspace_id] = token


def record_push(payload: dict) -> List[int]:
    """Store a push to the default branch for every workspace tracking that repo."""
    repository = payload["repository"]
    if payload.get("ref") != f"refs/heads/{repository['default_branch']}":
        return []
    messages = [c.get("message", "").split("\n", 1)[0] for c in payload.get("commits", [])][:50]
    now = time.time()
    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM repos WHERE full_name = ?", (repository["full_name"],))]
        for wid in ids:
            conn.execute(
                """INSERT INTO push_events (repo_id, before_sha, after_sha, forced, commit_count, messages, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (wid, payload.get("before", ""), payload["after"], int(bool(payload.get("forced"))),
                 len(payload.get("commits", [])), json.dumps(messages), now),
            )
    return ids


def schedule(workspace_id: int) -> None:
    """(Re)start the debounce timer; the batch runs once pushes go quiet."""
    old = _timers.get(workspace_id)
    if old and not old.done():
        old.cancel()

    async def later():
        await asyncio.sleep(settings.sync_debounce_seconds)
        try:
            await process(workspace_id, source="webhook")
        finally:
            _timers.pop(workspace_id, None)

    _timers[workspace_id] = asyncio.get_running_loop().create_task(later())


def _affected(store: IntentStore, changed: List[str], deleted: List[str]) -> dict:
    tenets, claims = store.tenets(), store.claims()
    changed_set = set(changed)
    leaves = sorted(t["id"] for t in tenets.values()
                    if not t["children"] and any(l["path"] in changed_set for l in t["code_links"]))
    upward = set()
    for leaf in leaves:
        upward |= store.upward(tenets, leaf)
    affected = sorted(set(leaves) | upward)
    rerun = sorted(c["id"] for c in claims.values() if c["tenet_id"] in affected)
    gone = set(deleted)
    orphans = []
    for t in tenets.values():
        if t["code_links"] and all(l["path"] in gone for l in t["code_links"]):
            own = [claims[c] for c in t["claims"] if c in claims]
            orphans.append({
                "tenet_id": t["id"],
                "scrap_candidates": [c["id"] for c in own if c["status"] == HYPOTHESIS],
                "demotion_requests": [c["id"] for c in own if c["status"] == AXIOM],
            })
    return {"changed_leaves": leaves, "affected_tenets": affected, "rerun_claims": rerun, "orphans": orphans}


def _save_batch(wid: int, base: Optional[str], head: str, source: str, status: str, data: dict,
                event_ids: List[int]) -> dict:
    now = time.time()
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO sync_batches (repo_id, base_sha, head_sha, status, source, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (wid, base, head, status, source, json.dumps(data), now),
        )
        batch_id = cur.lastrowid
        if event_ids:
            marks = ",".join("?" * len(event_ids))
            conn.execute(f"UPDATE push_events SET batch_id = ? WHERE id IN ({marks})", (batch_id, *event_ids))
        conn.execute("UPDATE repos SET last_synced_sha = ? WHERE id = ?", (head, wid))
    return {"id": batch_id, "base": base, "head": head, "status": status, "source": source,
            "created_at": now, **data}


async def process(workspace_id: int, source: str, token: Optional[str] = None) -> Optional[dict]:
    """Turn pending pushes (or a manual sync) into one batch."""
    token = token or _tokens.get(workspace_id)
    with db.connect() as conn:
        repo = conn.execute("SELECT * FROM repos WHERE id = ?", (workspace_id,)).fetchone()
        pending = conn.execute(
            "SELECT * FROM push_events WHERE repo_id = ? AND batch_id IS NULL ORDER BY id", (workspace_id,)
        ).fetchall()
    if repo is None or (source == "webhook" and not pending):
        return None
    if token is None:
        events.emit(workspace_id, "sync.waiting", pending_pushes=len(pending))
        return None

    full_name = repo["full_name"]
    if source == "webhook":
        head = pending[-1]["after_sha"]
    else:
        head = (await gh(token, "GET", f"/repos/{full_name}/commits/{repo['default_branch']}"))["sha"]
    # Re-diff from the last-synced marker so force pushes need no event replay.
    base = repo["last_synced_sha"]
    store = IntentStore(workspace_id)
    hints = [m for e in pending for m in json.loads(e["messages"])]
    event_ids = [e["id"] for e in pending]

    if base == head:
        if event_ids:
            with db.connect() as conn:
                marks = ",".join("?" * len(event_ids))
                conn.execute(f"UPDATE push_events SET batch_id = -1 WHERE id IN ({marks})", event_ids)
        return {"base": base, "head": head, "status": "up_to_date", "files": [], "commits": []}

    # The Codebase view updates first, always, independent of Jev.
    if base is None:
        snapshot = await codebase.snapshot_repo(token, full_name, head)
        store.put_imports(snapshot)
        data = {"initial": True, "files": [], "commits": [], "file_count": len(snapshot["files"]),
                "changed_leaves": [], "affected_tenets": [], "rerun_claims": [], "orphans": []}
        batch = _save_batch(workspace_id, None, head, source, "ingested", data, event_ids)
        events.emit(workspace_id, "sync.batch", batch=batch)
        return batch

    cmp = await compare_refs(token, full_name, base, head)
    renames = {f["previous_path"]: f["path"] for f in cmp["files"] if f["status"] == "renamed" and f["previous_path"]}
    store.apply_renames(renames)
    snapshot = await codebase.snapshot_repo(token, full_name, head)
    store.put_imports(snapshot)

    changed = [f["path"] for f in cmp["files"]] + list(renames)
    deleted = [f["path"] for f in cmp["files"] if f["status"] == "removed"]
    pure_rename = bool(cmp["files"]) and all(
        f["status"] == "renamed" and f["additions"] == 0 and f["deletions"] == 0 for f in cmp["files"]
    )
    data = {
        "initial": False,
        "compare_status": cmp["status"],  # "diverged" after a force push
        "files": cmp["files"],
        "commits": cmp["commits"],
        "hints": hints or [c["message"] for c in cmp["commits"]],
        "renames": renames,
        "skip_reason": "pure_rename" if pure_rename else None,
        "truncated": cmp["truncated"],
        **_affected(store, changed, deleted),
    }
    status = "skipped" if pure_rename else "awaiting_review"
    batch = _save_batch(workspace_id, base, head, source, status, data, event_ids)
    events.emit(workspace_id, "sync.batch", batch={k: v for k, v in batch.items() if k != "files"})
    return batch


def list_batches(workspace_id: int, status: Optional[str] = None, limit: int = 20) -> List[dict]:
    sql, args = "SELECT * FROM sync_batches WHERE repo_id = ?", [workspace_id]
    if status:
        sql, args = sql + " AND status = ?", args + [status]
    with db.connect() as conn:
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(limit, 100)))).fetchall()
    return [_batch_out(r) for r in rows]


def get_batch(workspace_id: int, batch_id: int) -> Optional[dict]:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM sync_batches WHERE repo_id = ? AND id = ?", (workspace_id, batch_id)).fetchone()
    return _batch_out(r) if r else None


def mark_reviewed(workspace_id: int, batch_id: int) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE sync_batches SET status = 'reviewed', reviewed_at = ? WHERE repo_id = ? AND id = ?",
                     (time.time(), workspace_id, batch_id))


def _batch_out(r) -> dict:
    return {"id": r["id"], "base": r["base_sha"], "head": r["head_sha"], "status": r["status"],
            "source": r["source"], "created_at": r["created_at"], "reviewed_at": r["reviewed_at"],
            **json.loads(r["data"])}
