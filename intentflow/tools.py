"""Tool registry, Gemini-compatible declarations schema generator, and tool dispatch."""
import json
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .agents.intent_builder import IntentBuilder
from .agents.remake import RemakeAgent
from .agents.test_author import TestAuthor
from .agents.test_runner import TestRunner
from .engine import IntentEngine
from .jobs import Bus, Jobs
from .models import Actor, EngineError, PermissionDenied, Status, StructuredFailure, Verdict
from .store import Store


@dataclass
class ToolDef:
    declaration: Dict[str, Any]
    handler: Callable[..., Coroutine[Any, Any, Dict[str, Any]]]


TOOLS: Dict[str, ToolDef] = {}


def register_tool(name: str, description: str, properties: Dict[str, Any], required: List[str] = ()):
    def decorator(fn):
        TOOLS[name] = ToolDef(
            declaration={
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(required),
                },
            },
            handler=fn,
        )
        return fn

    return decorator


class ToolContext:
    def __init__(
        self,
        engine: IntentEngine,
        store: Store,
        jobs: Jobs,
        bus: Bus,
        intent_builder: IntentBuilder,
        test_author: TestAuthor,
        test_runner: TestRunner,
        remake_agent: RemakeAgent,
        session_id: str,
        selection: Optional[Dict[str, Any]] = None,
        actor: Actor = Actor.CHATBOT,
    ):
        self.engine = engine
        self.store = store
        self.jobs = jobs
        self.bus = bus
        self.intent_builder = intent_builder
        self.test_author = test_author
        self.test_runner = test_runner
        self.remake_agent = remake_agent
        self.session_id = session_id
        self.selection = selection or {}
        self.actor = actor


# ===================================================================== Read Tools


@register_tool(
    name="get_tree",
    description="Get hierarchical overview of the Tenet tree with rolled-up verdicts and badges.",
    properties={"depth": {"type": "integer", "description": "Maximum depth to retrieve"}},
)
async def handle_get_tree(ctx: ToolContext, depth: int = 2) -> Dict[str, Any]:
    tenets = ctx.store.all_tenets()
    claims = ctx.store.all_claims()
    rollups = {t.id: ctx.engine.rollup(t.id) for t in tenets}

    return {
        "ok": True,
        "say": f"Retrieved {len(tenets)} tenets and {len(claims)} claims across the tree.",
        "data": {
            "tenets": [t.model_dump() for t in tenets],
            "rollups": rollups,
            "claims_count": len(claims),
        },
    }


@register_tool(
    name="get_tenet_context",
    description="Drill into a specific Tenet: functionality, claims, children, references, linked files, rollups.",
    properties={"tenet_id": {"type": "string", "description": "The permanent ID of the Tenet"}},
    required=["tenet_id"],
)
async def handle_get_tenet_context(ctx: ToolContext, tenet_id: str) -> Dict[str, Any]:
    t = ctx.store.get_tenet(tenet_id)
    all_claims = [c for c in ctx.store.all_claims() if c.tenet_id == tenet_id]

    axioms = []
    hypotheses = []
    for c in all_claims:
        v = ctx.store.latest_verdict(c)
        c_dict = c.model_dump()
        c_dict["latest_verdict"] = v.value
        c_dict["is_stale"] = (v == Verdict.STALE)
        if c.status == Status.AXIOM:
            axioms.append(c_dict)
        elif c.status == Status.HYPOTHESIS:
            hypotheses.append(c_dict)

    children = [ctx.store.get_tenet(cid).model_dump() for cid in t.children if ctx.store.find_tenet(cid)]
    rollup = ctx.engine.rollup(t.id)

    return {
        "ok": True,
        "say": f"Tenet {t.name} ({tenet_id}): {len(axioms)} axioms, {len(hypotheses)} hypotheses. Verdict is {rollup['verdict']}.",
        "data": {
            "tenet": t.model_dump(),
            "axioms": axioms,
            "hypotheses": hypotheses,
            "children": children,
            "rollup": rollup,
            "linked_files": [l.file for l in t.code_links],
        },
    }


@register_tool(
    name="get_claim",
    description="Get detailed statement, test explanation, test recipe, history, and status for one Claim.",
    properties={"claim_id": {"type": "string", "description": "The permanent ID of the Claim"}},
    required=["claim_id"],
)
async def handle_get_claim(ctx: ToolContext, claim_id: str) -> Dict[str, Any]:
    c = ctx.store.get_claim(claim_id)
    v = ctx.store.latest_verdict(c)
    rf = ctx.store.result_file(claim_id)

    return {
        "ok": True,
        "say": f"Claim {claim_id} is a {c.status.value} with latest verdict {v.value}.",
        "data": {
            "claim": c.model_dump(),
            "latest_verdict": v.value,
            "run_history": [r.model_dump() for r in rf.runs],
        },
    }


@register_tool(
    name="get_impact",
    description="Read-only impact analysis: what breaks if this Claim is demoted or changed (Rule 12).",
    properties={"claim_id": {"type": "string", "description": "The permanent ID of the Claim"}},
    required=["claim_id"],
)
async def handle_get_impact(ctx: ToolContext, claim_id: str) -> Dict[str, Any]:
    imp = ctx.engine.impact(claim_id)
    return {
        "ok": True,
        "say": f"Demoting {claim_id} affects {len(imp['dependent_claims'])} dependent claims and {len(imp['referencing_tenets'])} referencing tenets.",
        "data": imp,
    }


@register_tool(
    name="get_job",
    description="Check the status and result of an asynchronous background job.",
    properties={"job_id": {"type": "string", "description": "The job ID returned when work was started"}},
    required=["job_id"],
)
async def handle_get_job(ctx: ToolContext, job_id: str) -> Dict[str, Any]:
    job = ctx.jobs.get_job(job_id)
    if not job:
        raise EngineError("NOT_FOUND", f"Job {job_id} not found")
    return {
        "ok": True,
        "say": f"Job {job_id} is {job['status']}.",
        "data": job,
        "job_id": job_id,
    }


@register_tool(
    name="get_pending_grill",
    description="Resume grilling session or retrieve currently unanswered grilling questions.",
    properties={"session_id": {"type": "string", "description": "Chat session ID"}},
    required=["session_id"],
)
async def handle_get_pending_grill(ctx: ToolContext, session_id: str) -> Dict[str, Any]:
    state = ctx.intent_builder.load_state(session_id)
    if not state:
        return {"ok": True, "say": "No active grilling session found.", "data": {"active": False}}
    return {
        "ok": True,
        "say": f"Grilling session active on Tenet {state.tenet_id} with {len(state.questions)} open questions.",
        "data": {"active": True, "grill": state.model_dump()},
    }


# ===================================================================== Pipeline Triggers


@register_tool(
    name="start_grilling",
    description="Start an Intent Builder grilling session to discover and verify functionality down the tree.",
    properties={
        "tenet_id": {"type": "string", "description": "Optional tenet to start grilling at (defaults to root)"},
        "purpose_hint": {"type": "string", "description": "Optional hint about codebase purpose for the root"},
    },
)
async def handle_start_grilling(ctx: ToolContext, tenet_id: Optional[str] = None, purpose_hint: Optional[str] = None) -> Dict[str, Any]:
    state = await ctx.intent_builder.start_grilling(ctx.session_id, tenet_id, purpose_hint)
    t = ctx.store.get_tenet(state.tenet_id)

    # Publish grilling question event if questions exist
    if state.questions:
        ctx.bus.publish(
            ctx.session_id,
            "grill.question",
            {
                "grill_id": state.id,
                "tenet_id": state.tenet_id,
                "tenet_name": t.name,
                "questions": [q.model_dump() for q in state.questions],
            },
        )

    return {
        "ok": True,
        "say": f"Drafted Tenet '{t.name}'. Prepared {len(state.questions)} questions to verify.",
        "data": {
            "grill": {
                "session_id": state.id,
                "tenet_id": state.tenet_id,
                "tenet_name": t.name,
                "questions": [q.model_dump() for q in state.questions],
                "done": state.done,
                "progress": {
                    "queued": len(state.queue),
                    "asked_total": state.asked_total,
                },
            }
        },
    }


@register_tool(
    name="submit_grill_answer",
    description="Submit user's answer to a grilling question (answers are preserved verbatim).",
    properties={
        "grill_id": {"type": "string", "description": "Grilling session ID"},
        "question_id": {"type": "string", "description": "Question ID being answered"},
        "user_text": {"type": "string", "description": "Verbatim user answer text"},
        "dont_know": {"type": "boolean", "description": "True if user said they do not know or want to skip"},
    },
    required=["grill_id", "question_id", "user_text"],
)
async def handle_submit_grill_answer(ctx: ToolContext, grill_id: str, question_id: str, user_text: str, dont_know: bool = False) -> Dict[str, Any]:
    state = await ctx.intent_builder.submit_answer(grill_id, question_id, user_text, dont_know)

    if state.questions:
        t = ctx.store.get_tenet(state.tenet_id)
        ctx.bus.publish(
            ctx.session_id,
            "grill.question",
            {
                "grill_id": state.id,
                "tenet_id": state.tenet_id,
                "tenet_name": t.name,
                "questions": [q.model_dump() for q in state.questions],
            },
        )

    ctx.bus.publish(ctx.session_id, "tree.changed", {"tenet_ids": [state.tenet_id]})

    return {
        "ok": True,
        "say": "Recorded answer. " + ("Grilling complete." if state.done else f"Advancing on Tenet {state.tenet_id}."),
        "data": {
            "grill": state.model_dump(),
            "done": state.done,
            "created": state.created,
        },
    }


@register_tool(
    name="author_tests",
    description="Trigger the Test Author to write plain-language explanation and complete implementation recipe.",
    properties={"claim_id": {"type": "string", "description": "Claim ID to author tests for"}},
    required=["claim_id"],
)
async def handle_author_tests(ctx: ToolContext, claim_id: str) -> Dict[str, Any]:
    async def task(progress_cb):
        progress_cb("Analyzing code context and fixtures...", 0, 1)
        c = await ctx.test_author.author(claim_id)
        progress_cb("Recipe generated.", 1, 1)
        return {
            "claim_id": c.id,
            "summary": f"Authored unit recipe for Claim {c.id}: {c.statement[:60]}",
        }

    job_id = ctx.jobs.spawn(ctx.session_id, "author_tests", task, lock_key=claim_id)
    return {
        "ok": True,
        "say": f"Started test authoring for Claim {claim_id}.",
        "data": {"claim_id": claim_id},
        "job_id": job_id,
    }


@register_tool(
    name="run_tests",
    description="Run tests in sandbox bottom-up: leaf tests first, followed by integration tests.",
    properties={
        "tenet_id": {"type": "string", "description": "Optional Tenet ID to run tests for"},
        "claim_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional specific Claim IDs to run"},
        "subtree": {"type": "boolean", "description": "Whether to run across subtree (defaults to true)"},
    },
)
async def handle_run_tests(ctx: ToolContext, tenet_id: Optional[str] = None, claim_ids: Optional[List[str]] = None, subtree: bool = True) -> Dict[str, Any]:
    async def task(progress_cb):
        progress_cb("Running tests bottom-up...", 0, 1)
        results = []
        if claim_ids:
            for cid in claim_ids:
                r = ctx.test_runner.run_claim_test(cid)
                results.append(r.model_dump())
        else:
            runs = ctx.test_runner.run_tests_bottom_up(tenet_id, subtree=subtree)
            results = [r.model_dump() for r in runs]
        progress_cb("Tests completed.", 1, 1)
        return {"summary": f"Executed {len(results)} tests.", "results": results}

    job_id = ctx.jobs.spawn(ctx.session_id, "run_tests", task, lock_key=tenet_id or "all_tests")
    return {
        "ok": True,
        "say": "Started running tests in sandbox.",
        "data": {"tenet_id": tenet_id},
        "job_id": job_id,
    }


@register_tool(
    name="revise_hypothesis",
    description="Revise a Hypothesis statement per user instructions (never works on locked Axioms).",
    properties={
        "claim_id": {"type": "string", "description": "Hypothesis ID to revise"},
        "user_instruction": {"type": "string", "description": "What to change in the hypothesis"},
    },
    required=["claim_id", "user_instruction"],
)
async def handle_revise_hypothesis(ctx: ToolContext, claim_id: str, user_instruction: str) -> Dict[str, Any]:
    c = ctx.store.get_claim(claim_id)
    if c.status == Status.AXIOM:
        raise EngineError(
            "AXIOM_LOCKED",
            f"Claim {claim_id} is a locked Axiom. Cannot revise with LLM unless demoted first (Rule 1).",
            hint="Offer to request demotion so the user can unlock it.",
        )

    async def task(progress_cb):
        progress_cb("Drafting revised hypothesis...", 0, 1)
        sys_prompt = "You revise Hypotheses based on user instructions. Keep assertions atomic and testable."
        user_prompt = f"Current hypothesis: {c.statement}\nUser instruction: {user_instruction}\nRevise the statement."

        class RevisedOut(BaseModel):
            revised_statement: str

        from pydantic import BaseModel

        res: RevisedOut = await ctx.remake_agent.llm.structured(
            "deep",
            sys_prompt,
            user_prompt,
            RevisedOut,
            agent="revise_hypothesis",
            thinking=True,
            medium_effort=True,
        )
        old_stmt = c.statement
        c.statement = res.revised_statement
        ctx.store.put_claim(c, Actor.BUILDER)
        # Old results are now stale due to hash binding (Rule 6)
        progress_cb("Hypothesis updated.", 1, 1)
        return {
            "summary": f"Revised hypothesis from '{old_stmt[:40]}' to '{c.statement[:40]}'. Prior test results are now stale.",
            "old_statement": old_stmt,
            "new_statement": c.statement,
        }

    job_id = ctx.jobs.spawn(ctx.session_id, "revise_hypothesis", task, lock_key=claim_id)
    return {
        "ok": True,
        "say": f"Revising hypothesis {claim_id}...",
        "data": {"claim_id": claim_id},
        "job_id": job_id,
    }


@register_tool(
    name="add_hypothesis",
    description="Add a new Hypothesis from user's own words, then trigger test authoring.",
    properties={
        "tenet_id": {"type": "string", "description": "Owning Tenet ID"},
        "user_text": {"type": "string", "description": "Exact hypothesis statement"},
    },
    required=["tenet_id", "user_text"],
)
async def handle_add_hypothesis(ctx: ToolContext, tenet_id: str, user_text: str) -> Dict[str, Any]:
    c = ctx.store.create_claim(
        tenet_id=tenet_id,
        statement=user_text,
        actor=Actor.CHATBOT,
        status=Status.HYPOTHESIS,
        confidence=0.3,
        provenance={"via": "user_via_chat", "session_id": ctx.session_id},
    )

    # Spawn test authoring
    async def task(progress_cb):
        await ctx.test_author.author(c.id)
        return {"summary": f"Authored test recipe for user hypothesis {c.id}"}

    job_id = ctx.jobs.spawn(ctx.session_id, "author_tests", task, lock_key=c.id)

    return {
        "ok": True,
        "say": f"Created new Hypothesis '{user_text[:60]}' on Tenet {tenet_id}.",
        "data": {"claim_id": c.id, "tenet_id": tenet_id},
        "job_id": job_id,
    }


@register_tool(
    name="scrap_hypothesis",
    description="Scrap a Hypothesis and record it in rejected interpretations (can optionally remake).",
    properties={
        "claim_id": {"type": "string", "description": "Claim ID to scrap"},
        "reason": {"type": "string", "description": "Reason for scrapping"},
        "remake": {"type": "boolean", "description": "Whether to invoke Remake Agent to generate alternative"},
    },
    required=["claim_id"],
)
async def handle_scrap_hypothesis(ctx: ToolContext, claim_id: str, reason: str = "Scrapped by user", remake: bool = False) -> Dict[str, Any]:
    c = ctx.remake_agent.scrap_hypothesis(claim_id, reason=reason)
    job_id = None

    if remake:
        async def task(progress_cb):
            progress_cb("Remaking alternative hypothesis...", 0, 1)
            replacements = await ctx.remake_agent.remake(c.tenet_id, scrapped_claim_id=claim_id)
            progress_cb("Remake complete.", 1, 1)
            return {
                "summary": f"Remade {len(replacements)} alternative hypotheses differing from rejected interpretations.",
                "replacements": [r.model_dump() for r in replacements],
            }

        job_id = ctx.jobs.spawn(ctx.session_id, "remake", task, lock_key=c.tenet_id)

    return {
        "ok": True,
        "say": f"Scrapped Hypothesis {claim_id}." + (" Remaking alternative..." if remake else ""),
        "data": {"claim_id": claim_id, "status": "scrapped"},
        "job_id": job_id,
    }


@register_tool(
    name="probe_axiom",
    description="Axiom under question: generate probing boundary tests and repeat the original test without modifying the Axiom.",
    properties={"claim_id": {"type": "string", "description": "Axiom ID to probe"}},
    required=["claim_id"],
)
async def handle_probe_axiom(ctx: ToolContext, claim_id: str) -> Dict[str, Any]:
    async def task(progress_cb):
        progress_cb("Generating probing hypotheses...", 0, 1)
        probes = await ctx.test_author.probe_axiom(claim_id)
        progress_cb("Running probing tests...", 1, 2)
        runs = [ctx.test_runner.run_claim_test(p.id).model_dump() for p in probes]
        progress_cb("Done probing.", 2, 2)
        return {
            "summary": f"Generated and executed {len(probes)} probing tests for Axiom {claim_id}.",
            "probes": [p.model_dump() for p in probes],
            "results": runs,
        }

    job_id = ctx.jobs.spawn(ctx.session_id, "probe_axiom", task, lock_key=claim_id)
    return {
        "ok": True,
        "say": f"Started probing Axiom {claim_id} with additional edge-case tests.",
        "data": {"claim_id": claim_id},
        "job_id": job_id,
    }


@register_tool(
    name="sync_status",
    description="Check latest git sync and Jev review batch status.",
    properties={},
)
async def handle_sync_status(ctx: ToolContext) -> Dict[str, Any]:
    changelog = ctx.store.read_changelog(limit=5)
    jev_events = [e for e in changelog if e.get("actor") == "jev"]
    latest_jev = jev_events[-1] if jev_events else None

    return {
        "ok": True,
        "say": "Retrieved sync status.",
        "data": {
            "latest_decision": latest_jev,
            "total_changelog_entries": len(changelog),
        },
    }


# ===================================================================== Request-Only Tools


@register_tool(
    name="request_status_change",
    description="Request status change (promote to Axiom or demote to Hypothesis). Does NOT change state; returns confirmation card for UI.",
    properties={
        "claim_id": {"type": "string", "description": "Claim ID"},
        "target": {"type": "string", "enum": ["axiom", "hypothesis"], "description": "Target status"},
        "reason": {"type": "string", "description": "Reason (required for demotion)"},
    },
    required=["claim_id", "target"],
)
async def handle_request_status_change(ctx: ToolContext, claim_id: str, target: str, reason: Optional[str] = None) -> Dict[str, Any]:
    res = ctx.engine.request_status_change(claim_id, target, reason)
    confirm_card = {
        "type": "confirm_card",
        "confirmation_id": res["confirmation_id"],
        "claim_id": claim_id,
        "target": target,
        "verified": res["verified"],
        "impact": res["impact"],
    }

    return {
        "ok": True,
        "say": f"Prepared confirmation card for {target} change on Claim {claim_id}. Review impact and confirm in the UI.",
        "data": res,
        "ui": [confirm_card],
    }


@register_tool(
    name="open_axiom_editor",
    description="Open the hand-editor for an Axiom in the UI with impact warning. Chatbot never drafts Axiom text directly.",
    properties={"claim_id": {"type": "string", "description": "Axiom ID to edit"}},
    required=["claim_id"],
)
async def handle_open_axiom_editor(ctx: ToolContext, claim_id: str) -> Dict[str, Any]:
    c = ctx.store.get_claim(claim_id)
    if c.status != Status.AXIOM:
        raise EngineError("VALIDATION", f"Claim {claim_id} is not an Axiom")
    imp = ctx.engine.impact(claim_id)

    editor_card = {
        "type": "axiom_editor",
        "claim_id": claim_id,
        "impact": imp,
    }

    return {
        "ok": True,
        "say": f"Opened Axiom hand-editor card for {claim_id}.",
        "data": {"claim_id": claim_id, "impact": imp},
        "ui": [editor_card],
    }


# ===================================================================== Dispatcher


async def dispatch_tool_call(ctx: ToolContext, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute tool call and wrap into standard response envelope."""
    if name not in TOOLS:
        return {
            "ok": False,
            "say": f"Unknown tool '{name}'",
            "data": {},
            "ui": [],
            "job_id": None,
            "error": {"code": "NOT_FOUND", "message": f"Tool '{name}' not found"},
        }

    tool_def = TOOLS[name]
    try:
        res = await tool_def.handler(ctx, **args)
        # Ensure standard envelope shape
        return {
            "ok": res.get("ok", True),
            "say": res.get("say", ""),
            "data": res.get("data", {}),
            "ui": res.get("ui", []),
            "job_id": res.get("job_id"),
            "error": res.get("error"),
        }
    except EngineError as ee:
        return {
            "ok": False,
            "say": f"Error: {ee.message}",
            "data": ee.data,
            "ui": [],
            "job_id": None,
            "error": ee.to_dict(),
        }
    except PermissionDenied as pd:
        return {
            "ok": False,
            "say": f"Permission Denied: {str(pd)}",
            "data": {},
            "ui": [],
            "job_id": None,
            "error": {"code": "PERMISSION_DENIED", "message": str(pd)},
        }
    except Exception as e:
        return {
            "ok": False,
            "say": f"Internal tool failure: {str(e)}",
            "data": {},
            "ui": [],
            "job_id": None,
            "error": {"code": "INTERNAL", "message": str(e)},
        }
