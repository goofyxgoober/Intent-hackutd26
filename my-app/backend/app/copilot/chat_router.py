"""Chat router: single choke point for POST /api/chat and POST /api/repos/{repo}/ask.

Spec Sections 1, 2, 5, 6, 7.
Routes messages between Query Engine and Hypothesis Generation Engine.
"""
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.errors import EngineError
from app.intent.retrieval import build_outline
from app.intent.store import IntentStore
from app.copilot.models.schemas import ChatMessage, ChatResponse, SessionChatRequest, TokenMetrics
from app.copilot.repositories import message_repo, session_repo
from app.copilot.services.token_service import calculate_token_metrics
from intentflow import triggers
from intentflow.agents import jev
from intentflow.models import JevDecision, PromptVerdict, RouterResult, new_id


class WorkspaceContext:
    def __init__(self, workspace_id: int):
        self.id = workspace_id
        self.wid = workspace_id
        self.store = IntentStore(workspace_id)
        self.repo_dir = Path(settings.data_dir) / "workspaces" / str(workspace_id) / "repo"


def get_gate_reply(gate_reason: Optional[str]) -> str:
    """Returns terminal reply text per Section 2.3 table."""
    if gate_reason == "tenet_not_selected":
        return "Click a tenet node in the **Tenets** view, then ask me again."
    if gate_reason == "tenet_not_found":
        return "That tenet no longer exists. Click a tenet and try again."
    if gate_reason == "low_confidence":
        return "Do you want me to answer a question, or draft hypotheses for the selected tenet?"
    if gate_reason == "disabled_by_user":
        return "Hypothesis generation is disabled by user settings."
    if gate_reason == "tenet_cap_reached":
        return f"Open hypothesis cap reached ({settings.hypothesis_per_tenet_cap}) for this tenet."
    if gate_reason == "rate_limited":
        return "Rate limit reached for hypothesis generation in this workspace. Please try again shortly."
    if gate_reason == "no_intent_tree":
        return "Workspace does not have an intent tree."
    if gate_reason == "forbidden":
        return "Permission denied: caller cannot generate hypotheses on this workspace."
    if gate_reason == "duplicate_recent":
        return "An identical hypothesis generation was recently completed for this tenet."
    return f"Hypothesis generation blocked: {gate_reason or 'not approved'}."


async def route_chat(
    request: SessionChatRequest,
    user: Any,
    session: Optional[Any] = None,
    meta_db: Optional[Session] = None,
    msg_db: Optional[Session] = None,
    agent: Optional[Any] = None,
    llm: Optional[Any] = None,
    gemini_client: Optional[Any] = None,
) -> ChatResponse:
    """Single choke point for /api/chat and /api/repos/{repo}/ask."""
    message = request.message.strip()

    # 1. Unknown slash command handling (§6 step 2)
    if message.startswith("/") and not message.startswith("/ask") and not message.startswith("/hypothesize"):
        raise EngineError(400, "Unknown command", "UNKNOWN_COMMAND")

    # 2. No workspace_id -> legacy behavior (§6 step 3, §10.3 test 10)
    if not request.workspace_id:
        if agent is None:
            from app.copilot.api.dependencies import get_agent
            agent = get_agent()
        history: List[ChatMessage] = []
        if session and msg_db:
            rows = message_repo.load_recent(msg_db, session.id, limit=6)
            history = [ChatMessage(role=m.role, content=m.content, timestamp=m.timestamp.isoformat()) for m in rows]

        result = await agent.execute_chat(
            user_message=message,
            history=history,
            selected_node_ids=request.selected_node_ids,
        )

        if session is None and meta_db:
            session = session_repo.create_session(
                meta_db,
                getattr(user, "team_id", "default_team"),
                getattr(user, "id", "default_user"),
                title=message,
                selected_node_ids=request.selected_node_ids,
            )

        if session and msg_db:
            message_repo.append_messages(msg_db, session.id, [
                {"role": "user", "content": message},
                {
                    "role": "assistant",
                    "content": result.content,
                    "token_metrics": result.token_metrics.model_dump(),
                    "retrieved_items": result.retrieved_items,
                    "agent_steps": result.agent_steps,
                },
            ])
            if meta_db:
                session_repo.touch_session(meta_db, session.id, added_messages=2)

        return ChatResponse(
            **result.model_dump(),
            session_id=session.id if session else "legacy_session",
            route=None,
            generation=None,
            query=None,
        )

    # 3. Workspace-backed session
    ws_ctx = WorkspaceContext(request.workspace_id)
    store = ws_ctx.store
    repo_dir = ws_ctx.repo_dir

    # Load history
    history = []
    if session and msg_db:
        rows = message_repo.load_recent(msg_db, session.id, limit=4)
        history = [ChatMessage(role=m.role, content=m.content, timestamp=m.timestamp.isoformat()) for m in rows]

    route_obj: Optional[Dict[str, Any]] = None
    gen_obj: Optional[Dict[str, Any]] = None
    query_obj: Optional[Dict[str, Any]] = None
    reply_content = ""

    # ------------------------------------------------------------------ Slash Commands

    if message.startswith("/ask"):
        # Forced query path (skip Jev router; read-only)
        query_text = message[len("/ask"):].strip()
        decision_id = new_id("jd")
        route_obj = {
            "decision_id": decision_id,
            "verdict": "query",
            "confidence": 1.0,
            "source": "explicit_user",
            "approved": False,
            "gate_reason": "not_generation",
            "target_tenet_id": None,
            "degraded": False,
        }
        res = await triggers.trigger_query(
            workspace=ws_ctx,
            user_id=getattr(user, "id", "user"),
            message=query_text,
            history=history,
            selected_tenet_id=request.selected_tenet_id,
            route=None,
            llm=llm,
            gemini_client=gemini_client,
        )
        query_obj = res.model_dump()
        reply_content = res.answer

    elif message.startswith("/hypothesize"):
        # Explicit hypothesis generation (§6 step 2)
        raw_args = message[len("/hypothesize"):].strip()
        m_args = re.match(r"^(\d+)\s*(.*)$", raw_args)
        if m_args:
            count = int(m_args.group(1))
            focus = m_args.group(2).strip() or None
        else:
            count = 3
            focus = raw_args or None

        # Run gate steps 5-10
        tenets_map = store.tenets()
        if not tenets_map:
            gate_reason = "no_intent_tree"
            approved = False
        elif not request.selected_tenet_id:
            gate_reason = "tenet_not_selected"
            approved = False
        elif request.selected_tenet_id not in tenets_map:
            gate_reason = "tenet_not_found"
            approved = False
        else:
            gate_reason = None
            approved = True

        decision = JevDecision(
            decision_id=new_id("jd"),
            verdict=PromptVerdict.HYPOTHESIS_GENERATION,
            confidence=1.0,
            source="explicit_user",
            approved=approved,
            gate_reason=gate_reason,
            target_tenet_id=request.selected_tenet_id if approved else None,
            requested_count=count,
            focus=focus,
        )
        route_obj = decision.model_dump()

        if approved:
            gen_res = await triggers.trigger_hypothesis_generation(
                workspace=ws_ctx,
                user_id=getattr(user, "id", "user"),
                decision=decision,
                llm=llm,
            )
            gen_obj = gen_res.model_dump()
            if gen_res.status == "failed":
                reply_content = f"Generation failed: {gen_res.error_code or 'Unknown error'}"
            else:
                reply_content = f"Drafted {len(gen_res.claims_created)} unverified hypotheses on tenet {request.selected_tenet_id}."
                if gen_res.claims_created:
                    reply_content += "\n" + "\n".join(f"- `{c.get('statement')}`" for c in gen_res.claims_created)
        else:
            reply_content = get_gate_reply(gate_reason)

    else:
        # -------------------------------------------------------------- Natural Prompt Flow
        outline, _ = build_outline(store, repo_dir, message, request.selected_tenet_id)
        tenets_data = list(store.tenets().values())

        router_result = await jev.route_prompt(
            workspace=ws_ctx,
            message=message,
            history=history,
            selected_tenet_id=request.selected_tenet_id,
            outline=outline,
            tenets_data=tenets_data,
            llm=llm,
        )

        decision = jev.decide_prompt(
            store=store,
            route=router_result,
            selected_tenet_id=request.selected_tenet_id,
            allow_generation=request.allow_generation,
            actor=user,
            message=message,
        )
        route_obj = decision.model_dump()

        if decision.verdict == PromptVerdict.AXIOM_MODIFICATION_REQUEST:
            # Axiom request refusal (§6 step 4b)
            reply_content = (
                "Axioms are human-only and cannot be created, edited, or promoted via terminal. "
                "In the Tenets view, select the claim and choose 'Edit axiom' with impact preview to make changes."
            )

        elif decision.verdict == PromptVerdict.HYPOTHESIS_GENERATION:
            if decision.approved:
                gen_res = await triggers.trigger_hypothesis_generation(
                    workspace=ws_ctx,
                    user_id=getattr(user, "id", "user"),
                    decision=decision,
                    llm=llm,
                )
                gen_obj = gen_res.model_dump()
                if gen_res.status == "failed":
                    reply_content = f"Generation failed: {gen_res.error_code or 'Unknown error'}"
                else:
                    reply_content = f"Drafted {len(gen_res.claims_created)} unverified hypotheses on tenet {request.selected_tenet_id}."
                    if gen_res.claims_created:
                        reply_content += "\n" + "\n".join(f"- `{c.get('statement')}`" for c in gen_res.claims_created)
            else:
                reply_content = get_gate_reply(decision.gate_reason)

        else:
            # Query path (including degraded router)
            query_res = await triggers.trigger_query(
                workspace=ws_ctx,
                user_id=getattr(user, "id", "user"),
                message=message,
                history=history,
                selected_tenet_id=request.selected_tenet_id,
                route=router_result,
                llm=llm,
                gemini_client=gemini_client,
            )
            query_obj = query_res.model_dump()
            reply_content = query_res.answer

    # 4. Message persistence (§6 step 5)
    if session is None and meta_db:
        session = session_repo.create_session(
            meta_db,
            getattr(user, "team_id", "default_team"),
            getattr(user, "id", "default_user"),
            title=message,
            selected_node_ids=request.selected_node_ids,
        )

    meta_json = {
        "route": route_obj,
        "generation": gen_obj,
        "query": query_obj,
    }

    if session and msg_db:
        message_repo.append_messages(msg_db, session.id, [
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": reply_content,
                "token_metrics": calculate_token_metrics(message, reply_content).model_dump(),
                "retrieved_items": query_obj.get("plan", {}).get("files", []) if query_obj else [],
                "agent_steps": ["jev_routed"],
                "meta_json": meta_json,
            },
        ])
        if meta_db:
            session_repo.touch_session(meta_db, session.id, added_messages=2)

    return ChatResponse(
        bot_type="intent_terminal",
        content=reply_content,
        token_metrics=calculate_token_metrics(message, reply_content),
        retrieved_items=query_obj.get("plan", {}).get("files", []) if query_obj else [],
        agent_steps=["jev_routed"],
        session_id=session.id if session else "session_none",
        route=route_obj,
        generation=gen_obj,
        query=query_obj,
    )
