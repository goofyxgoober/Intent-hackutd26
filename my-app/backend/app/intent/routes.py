"""Workspace API: what agents and the two views call (spec sections 7, 10, 12, 14).

Every route is under /api/workspaces/{workspace_id}. Users authenticate with their
session cookie; agents send "Authorization: Bearer <key>" (see AGENT_KEYS).
"""
import posixpath
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect

from .. import events, sync
from ..actors import Actor, Workspace, actor_from_credentials, load_workspace, workspace_and_actor
from ..config import settings
from . import export as exporter
from .models import (AxiomEdit, Annotation, ClaimCreate, ClaimFields, CodeLink, Demote, JevVerdict, Promote,
                     Remake, Scrap, SpecDoc, TenetCreate, TenetUpdate, TestRun)
from .store import AXIOM, IntentStore, safe_repo_path

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["intent"])
WA = Depends(workspace_and_actor)


def _store(wa) -> "tuple[IntentStore, Actor, Workspace]":
    ws, actor = wa
    return IntentStore(ws.id), actor, ws


@router.get("")
def workspace(wa=WA) -> dict:
    _, actor, ws = _store(wa)
    return {"id": ws.id, "full_name": ws.full_name, "default_branch": ws.default_branch,
            "last_synced_sha": ws.last_synced_sha, "you": {"kind": actor.kind, "name": actor.name}}


@router.get("/tree")
def tree(wa=WA) -> dict:
    return _store(wa)[0].tree()


# ---------------------------------------------------------------- Tenets


@router.post("/tenets", status_code=201)
def create_tenet(body: TenetCreate, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.create_tenet(actor, body.name, body.functionality, body.parent_id, body.cross_cutting,
                              body.provenance.model_dump(exclude_none=True))


@router.get("/tenets/{tenet_id}")
def get_tenet(tenet_id: str, wa=WA) -> dict:
    store = _store(wa)[0]
    tenets = store.tenets()
    t = tenets.get(tenet_id) or store.tenet(tenet_id)
    return {**t, "level": store.level(tenets, tenet_id), "referenced_by": store.referencers(tenets, tenet_id),
            "footprint": store.footprint(tenets, tenet_id)}


@router.patch("/tenets/{tenet_id}")
def update_tenet(tenet_id: str, body: TenetUpdate, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.update_tenet(actor, tenet_id, body.model_dump(exclude_none=True))


@router.post("/tenets/{tenet_id}/move")
def move_tenet(tenet_id: str, body: dict, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    if not isinstance(body.get("parent_id"), str):
        raise HTTPException(422, "parent_id is required")
    return store.move_tenet(actor, tenet_id, body["parent_id"])


@router.delete("/tenets/{tenet_id}", status_code=204)
def delete_tenet(tenet_id: str, wa=WA) -> Response:
    store, actor, _ = _store(wa)
    store.delete_tenet(actor, tenet_id)
    return Response(status_code=204)


@router.post("/tenets/{tenet_id}/references")
def add_reference(tenet_id: str, body: dict, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    if not isinstance(body.get("target"), str):
        raise HTTPException(422, "target is required")
    return store.add_reference(actor, tenet_id, body["target"])


@router.delete("/tenets/{tenet_id}/references/{target}")
def remove_reference(tenet_id: str, target: str, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.remove_reference(actor, tenet_id, target)


@router.put("/tenets/{tenet_id}/links")
def set_links(tenet_id: str, links: List[CodeLink], wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.set_links(actor, tenet_id, [l.model_dump(exclude_none=True) for l in links])


@router.get("/tenets/{tenet_id}/rejected")
def rejected(tenet_id: str, wa=WA) -> List[dict]:
    """Rejected interpretations, for the Remake Agent (section 10.5)."""
    return _store(wa)[0].rejected_interpretations(tenet_id)


# ---------------------------------------------------------------- Claims


@router.post("/tenets/{tenet_id}/claims", status_code=201)
def create_claim(tenet_id: str, body: ClaimCreate, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.create_claim(actor, tenet_id, body.model_dump())


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str, wa=WA) -> dict:
    store = _store(wa)[0]
    c = store.claim(claim_id)
    return {**c, "result": store.summarize_result(c)}


@router.patch("/claims/{claim_id}")
def update_claim(claim_id: str, body: ClaimFields, wa=WA) -> dict:
    """Edit a Hypothesis. Axioms are refused here for everyone."""
    store, actor, _ = _store(wa)
    return store.update_hypothesis(actor, claim_id, body.model_dump(exclude_none=True))


@router.put("/claims/{claim_id}/axiom")
def edit_axiom(claim_id: str, body: AxiomEdit, wa=WA) -> dict:
    """User-only hand edit of an Axiom, behind a warning (section 11.8)."""
    store, actor, _ = _store(wa)
    fields = body.model_dump(exclude_none=True, exclude={"acknowledge_warning", "reason"})
    return store.edit_axiom(actor, claim_id, fields, body.acknowledge_warning, body.reason)


@router.get("/claims/{claim_id}/impact")
def impact(claim_id: str, wa=WA) -> dict:
    return _store(wa)[0].impact(claim_id)


@router.post("/claims/{claim_id}/promote")
def promote(claim_id: str, body: Promote, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.promote(actor, claim_id, body.accept_without_verification)


@router.post("/claims/{claim_id}/demote")
def demote(claim_id: str, body: Demote, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.demote(actor, claim_id, body.reason)


@router.post("/claims/{claim_id}/scrap")
def scrap(claim_id: str, body: Scrap, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.scrap(actor, claim_id, body.reason, body.rejected_interpretation)


@router.post("/claims/{claim_id}/remake", status_code=201)
def remake(claim_id: str, body: Remake, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.remake(actor, claim_id, body.model_dump())


@router.delete("/claims/{claim_id}/flags/{kind}")
def clear_flag(claim_id: str, kind: str, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.clear_flag(actor, claim_id, kind)


@router.post("/claims/{claim_id}/results")
def append_result(claim_id: str, body: TestRun, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.append_result(actor, claim_id, body.model_dump())


@router.get("/claims/{claim_id}/results")
def get_results(claim_id: str, wa=WA) -> dict:
    store = _store(wa)[0]
    c = store.claim(claim_id)
    rf = store.result_file(claim_id)
    return {**rf, "tenet_id": c["tenet_id"], "summary": store.summarize_result(c, rf)}


# ---------------------------------------------------------------- engine outputs


@router.get("/annotations")
def get_annotation(path: str, wa=WA) -> dict:
    a = _store(wa)[0].get_annotation(safe_repo_path(path))
    if a is None:
        raise HTTPException(404, f"No annotation for {path}")
    return a


@router.put("/annotations")
def put_annotation(path: str, body: Annotation, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.put_annotation(actor, safe_repo_path(path), body.model_dump())


@router.get("/spec")
def get_spec(wa=WA) -> dict:
    spec = _store(wa)[0].spec()
    if spec is None:
        raise HTTPException(404, "The spec hasn't been compiled yet")
    return spec


@router.put("/spec")
def put_spec(body: SpecDoc, wa=WA) -> dict:
    store, actor, _ = _store(wa)
    return store.put_spec(actor, body.markdown, body.sections)


@router.post("/jev/verdicts")
def jev_verdict(body: JevVerdict, wa=WA) -> dict:
    store, actor, ws = _store(wa)
    if body.batch_id is not None and sync.get_batch(ws.id, body.batch_id) is None:
        raise HTTPException(422, f"No sync batch {body.batch_id}")
    entry = store.record_jev(actor, body.model_dump())
    if body.batch_id is not None:
        sync.mark_reviewed(ws.id, body.batch_id)
    return entry


@router.get("/changelog")
def changelog(limit: int = 200, wa=WA) -> List[dict]:
    return _store(wa)[0].read_changelog(limit)


@router.get("/history")
def history(kind: Optional[str] = None, wa=WA) -> List[dict]:
    if kind not in (None, "axiom_versions", "scrapped", "rejected", "change_sets"):
        raise HTTPException(422, "kind must be axiom_versions, scrapped, rejected or change_sets")
    return _store(wa)[0].history(kind)


@router.get("/inbox")
def inbox(wa=WA) -> dict:
    """Everything waiting on the user; nothing here blocks anything else."""
    store, _, ws = _store(wa)
    t = store.tree()
    return {
        "flagged_axioms": [c for c in t["claims"].values() if c["status"] == AXIOM and c["flags"]],
        "low_confidence_verdicts": [e for e in store.read_changelog() if e.get("to_review_inbox")],
        "proposed_tenets": [x["id"] for x in t["tenets"] if x.get("proposed")],
        "proposed_claims": [c["id"] for c in t["claims"].values() if c.get("proposed")],
        "batches_awaiting_review": [
            {k: b[k] for k in ("id", "base", "head", "affected_tenets", "orphans")}
            for b in sync.list_batches(ws.id, status="awaiting_review")
        ],
    }


# ---------------------------------------------------------------- codebase view and sync


@router.get("/codebase")
def codebase_view(wa=WA) -> dict:
    """Folder tree, files with annotation status and constraining Tenets, import edges (14.2, 14.3)."""
    store = _store(wa)[0]
    snap = store.imports()
    if snap is None:
        raise HTTPException(404, "No snapshot yet. Sync the repo to ingest it.")
    by_file = {}
    for t in store.tenets().values():
        for link in t["code_links"]:
            by_file.setdefault(link["path"], []).append(t["id"])
    annotated = store.annotated_paths()
    folders = {"": set()}
    for f in snap["files"]:
        parts = f["path"].split("/")
        for i in range(len(parts)):
            parent = "/".join(parts[:i])
            child = "/".join(parts[: i + 1])
            folders.setdefault(parent, set()).add(child)
            if i < len(parts) - 1:
                folders.setdefault(child, set())
    files_out = []
    for f in snap["files"]:
        p = f["path"]
        a = store.get_annotation(p)
        annot_summary = a.get("summary") if a and isinstance(a, dict) else None
        files_out.append({
            **f,
            "annotated": p in annotated,
            "annotation": annot_summary,
            "tenets": by_file.get(p, []),
        })

    return {
        "head": snap["head"],
        "folders": [{"path": p, "name": posixpath.basename(p) or "/", "children": sorted(c)}
                    for p, c in sorted(folders.items())],
        "files": files_out,
        "edges": snap["edges"],
        "external": snap["external"],
    }


@router.get("/sync/status")
def sync_status(wa=WA) -> dict:
    """Is this repo being watched, and when was it last checked?"""
    ws = _store(wa)[2]
    return {**sync.polling_status(ws.id), "last_synced_sha": ws.last_synced_sha}


@router.get("/sync/latest")
def latest_change(wa=WA) -> Optional[dict]:
    """The most recent batch that changed files (commits, files, changed line numbers, diffs), or null."""
    ws = _store(wa)[2]
    for b in sync.list_batches(ws.id, limit=20):
        if not b.get("initial") and b.get("files"):
            return b
    return None


@router.post("/sync/check")
async def check_now(wa=WA) -> dict:
    """Poll once immediately instead of waiting for the next interval."""
    ws = _store(wa)[2]
    batch = await sync.check_once(ws.id)
    return {"changed": batch is not None, "batch": batch, **sync.polling_status(ws.id)}


@router.get("/sync/batches")
def batches(status: Optional[str] = None, limit: int = 20, wa=WA) -> List[dict]:
    return sync.list_batches(_store(wa)[2].id, status, limit)


@router.get("/sync/batches/{batch_id}")
def batch(batch_id: int, wa=WA) -> dict:
    b = sync.get_batch(_store(wa)[2].id, batch_id)
    if b is None:
        raise HTTPException(404, f"No sync batch {batch_id}")
    return b


@router.post("/export")
async def export_folder(wa=WA) -> dict:
    store, actor, ws = _store(wa)
    if not actor.is_user:
        raise HTTPException(403, "Only a user can export to GitHub")
    return await exporter.export_to_branch(actor.session.access_token, ws.full_name, ws.default_branch,
                                           settings.intent_branch, settings.intent_folder, store)


@router.post("/pipeline")
async def run_pipeline(wa=WA) -> dict:
    """Run full 4-step pipeline: pull code, check commit diffs, create requirements/files, start tenet grilling."""
    store, actor, ws = _store(wa)
    token = actor.session.access_token if actor.is_user else sync._tokens.get(ws.id)
    if not token:
        raise HTTPException(400, "No access token available for pipeline run")
    from .. import pipeline
    head = await sync._branch_head(token, ws.full_name, ws.default_branch)
    return await pipeline.execute_full_pipeline(
        workspace_id=ws.id,
        token=token,
        full_name=ws.full_name,
        head_sha=head,
        base_sha=ws.last_synced_sha,
    )


# ---------------------------------------------------------------- live updates

ws_router = APIRouter()


@ws_router.websocket("/ws/workspaces/{workspace_id}")
async def workspace_socket(websocket: WebSocket, workspace_id: int):
    """Pushes every change in the workspace. Agents pass ?key=<agent key>."""
    try:
        actor = actor_from_credentials(websocket.cookies.get(settings.session_cookie),
                                       websocket.query_params.get("key"), websocket.query_params.get("name"))
        load_workspace(workspace_id, actor)
    except HTTPException as e:
        await websocket.close(code=4401 if e.status_code == 401 else 4404)
        return
    await websocket.accept()
    await events.subscribe(workspace_id, websocket)
    try:
        await websocket.send_json({"type": "hello", "workspace_id": workspace_id, "you": actor.kind})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        events.unsubscribe(workspace_id, websocket)
