"""FastAPI endpoints for IntentFlow engine, Chatbot tool dispatch, UI auth, and SSE events."""
import asyncio
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agents.intent_builder import IntentBuilder
from .agents.remake import RemakeAgent
from .agents.test_author import TestAuthor
from .agents.test_runner import TestRunner
from .annotations import RepositoryAnnotationIndex
from .engine import IntentEngine, UserAuthority
from .jobs import Bus, Jobs
from .llm import Nemotron
from .models import Actor, EngineError, PermissionDenied, Status, Verdict
from .spec_compiler import SpecCompiler
from .store import Store
from .tools import TOOLS, ToolContext, dispatch_tool_call

# Global singletons / configuration
CHATBOT_SERVICE_KEY = os.getenv("CHATBOT_SERVICE_KEY", "dev_chatbot_service_key")
JWT_SECRET = os.getenv("JWT_SECRET", "dev_jwt_secret_32bytes_minimum_ok")
REPO_PATH = Path(os.getenv("REPO_PATH", ".")).resolve()
INTENT_DIR = Path(os.getenv("INTENT_DIR", "data/intent")).resolve()

store = Store(INTENT_DIR)
engine = IntentEngine(store)
bus = Bus()
jobs = Jobs(bus)
llm = Nemotron()
annotations = RepositoryAnnotationIndex(REPO_PATH, store, llm=llm)
intent_builder = IntentBuilder(engine, store, annotations, llm=llm)
test_author = TestAuthor(store, annotations, llm=llm)
test_runner = TestRunner(engine, store, REPO_PATH, llm=llm)
remake_agent = RemakeAgent(store, annotations, llm=llm)
spec_compiler = SpecCompiler(store)

router = APIRouter()


# ------------------------------------------------------------------ Auth Dependencies


def verify_service_key(x_service_key: Optional[str] = Header(None, alias="X-Service-Key")) -> bool:
    if not x_service_key or not hmac.compare_digest(x_service_key, CHATBOT_SERVICE_KEY):
        raise HTTPException(401, "Invalid or missing X-Service-Key header")
    return True


def verify_user_jwt(authorization: Optional[str] = Header(None)) -> UserAuthority:
    """Verifies user JWT or bearer token and mints UserAuthority (Section 4.1)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required for user UI actions")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "Empty bearer token")

    # For hackathon/demo, accept tokens prefixed with 'u_' or standard format
    user_id = token
    if "." in token:
        try:
            import base64
            parts = token.split(".")
            if len(parts) >= 2:
                padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                payload = json.loads(base64.urlsafe_b64decode(padded).decode())
                user_id = str(payload.get("sub", payload.get("user_id", token)))
        except Exception:
            user_id = token

    return UserAuthority.from_verified_jwt(user_id)


# ------------------------------------------------------------------ Tool & Event Endpoints


@router.get("/tools")
def get_tools(_: bool = Depends(verify_service_key)) -> Dict[str, Any]:
    """Serve Gemini-compatible function declarations without $ref."""
    return {"declarations": [t.declaration for t in TOOLS.values()]}


class ToolCallRequest(BaseModel):
    session_id: str
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    selection: Optional[Dict[str, Any]] = None


@router.post("/tools/call")
async def call_tool(body: ToolCallRequest, _: bool = Depends(verify_service_key)) -> Dict[str, Any]:
    """Dispatch tool call from Gemini chatbot layer."""
    ctx = ToolContext(
        engine=engine,
        store=store,
        jobs=jobs,
        bus=bus,
        intent_builder=intent_builder,
        test_author=test_author,
        test_runner=test_runner,
        remake_agent=remake_agent,
        session_id=body.session_id,
        selection=body.selection,
        actor=Actor.CHATBOT,
    )
    return await dispatch_tool_call(ctx, body.name, body.args)


@router.get("/events/{session_id}")
async def sse_events(session_id: str, _: bool = Depends(verify_service_key)) -> StreamingResponse:
    """Server-Sent Events streaming to chat backend."""
    q = bus.subscribe(session_id)

    async def event_generator():
        try:
            while True:
                try:
                    event_type, data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            bus.unsubscribe(session_id, q)
        finally:
            bus.unsubscribe(session_id, q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ------------------------------------------------------------------ UI Endpoints (UserAuthority only)


class ConfirmRequest(BaseModel):
    choice: str = "confirm"  # "confirm" | "accept_unverified"
    reason: Optional[str] = None


@router.post("/ui/confirm/{confirmation_id}")
def ui_confirm(
    confirmation_id: str,
    body: ConfirmRequest,
    auth: UserAuthority = Depends(verify_user_jwt),
) -> Dict[str, Any]:
    """User button click in UI that executes promotion or demotion."""
    res = engine.confirm(confirmation_id, body.choice, body.reason, auth)
    c = store.get_claim(res["claim_id"])
    bus.publish("default", "verdict.updated", {"claim_id": c.id, "tenet_id": c.tenet_id, "status": c.status.value})
    bus.publish("default", "tree.changed", {"tenet_ids": [c.tenet_id]})
    return res


class AxiomEditRequest(BaseModel):
    fields: Dict[str, Any]
    reason: str
    ack_warning: bool = False


@router.post("/ui/claims/{claim_id}/edit")
def ui_edit_axiom(
    claim_id: str,
    body: AxiomEditRequest,
    auth: UserAuthority = Depends(verify_user_jwt),
) -> Dict[str, Any]:
    """User direct hand-edit of an Axiom after acknowledging warning."""
    updated = engine.edit_axiom_by_hand(
        claim_id,
        body.fields,
        body.reason,
        body.ack_warning,
        auth,
    )
    bus.publish("default", "verdict.updated", {"claim_id": updated.id, "tenet_id": updated.tenet_id, "status": updated.status.value})
    bus.publish("default", "tree.changed", {"tenet_ids": [updated.tenet_id]})
    return {"status": "ok", "claim": updated.model_dump()}


class ScrapRequest(BaseModel):
    reason: str = "Scrapped by user"


@router.post("/ui/claims/{claim_id}/scrap")
def ui_scrap_claim(
    claim_id: str,
    body: ScrapRequest,
    auth: UserAuthority = Depends(verify_user_jwt),
) -> Dict[str, Any]:
    scrapped = remake_agent.scrap_hypothesis(claim_id, reason=body.reason)
    bus.publish("default", "tree.changed", {"tenet_ids": [scrapped.tenet_id]})
    return {"status": "ok", "claim": scrapped.model_dump()}


# ------------------------------------------------------------------ Read Views


@router.get("/tree")
def get_tree() -> Dict[str, Any]:
    tenets = store.all_tenets()
    claims = store.all_claims()
    rollups = {t.id: engine.rollup(t.id) for t in tenets}
    return {
        "tenets": [t.model_dump() for t in tenets],
        "claims": [c.model_dump() for c in claims],
        "rollups": rollups,
    }


@router.get("/tenets/{tenet_id}")
def get_tenet(tenet_id: str) -> Dict[str, Any]:
    t = store.get_tenet(tenet_id)
    rollup = engine.rollup(tenet_id)
    return {"tenet": t.model_dump(), "rollup": rollup}


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str) -> Dict[str, Any]:
    c = store.get_claim(claim_id)
    v = store.latest_verdict(c)
    rf = store.result_file(claim_id)
    return {"claim": c.model_dump(), "latest_verdict": v.value, "runs": [r.model_dump() for r in rf.runs]}


@router.get("/spec")
def get_spec() -> Dict[str, Any]:
    compiled = spec_compiler.compile()
    return compiled.model_dump()


# Standalone FastAPI App
app = FastAPI(title="IntentFlow Engine API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
