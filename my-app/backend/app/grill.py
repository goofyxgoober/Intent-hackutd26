"""Interactive tenet grilling state machine, question dispatch, and claim synthesis."""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .actors import Actor
from .config import settings
from .events import emit
from .intent.store import IntentStore, new_id


def get_sessions_dir(workspace_id: int) -> Path:
    p = Path(settings.data_dir) / "workspaces" / str(workspace_id) / "intent" / ".sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_grill_session_file(workspace_id: int) -> Path:
    return get_sessions_dir(workspace_id) / f"grill_ws_{workspace_id}.json"


def load_grill_state(workspace_id: int) -> Optional[dict]:
    f = get_grill_session_file(workspace_id)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_grill_state(workspace_id: int, state: dict) -> None:
    f = get_grill_session_file(workspace_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, indent=2), encoding="utf-8")


def generate_questions_for_tenet(tenet: dict, repo_title: str) -> List[dict]:
    """Generates repository- and tenet-tailored architectural questions with concrete options."""
    t_name = tenet.get("name", "System")
    t_func = tenet.get("functionality", "")
    t_lower = (t_name + " " + t_func).lower()

    if "service" in t_lower or "vector" in t_lower or "pinecone" in t_lower or "cloud" in t_lower:
        return [
            {
                "id": new_id("q"),
                "text": f"How should {t_name} handle downstream service rate limits (e.g. Pinecone/Google Docs quota errors)?",
                "why": "Define failure isolation and non-negotiable backoff contracts.",
                "options": [
                    "Exponential backoff with in-memory retry queue and persistent failure logging",
                    "Fail fast immediately with a 503 response and rollback the active transaction",
                    "Graceful degradation: serve cached lexical results and buffer writes in DynamoDB",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": "What is the invariant requirement for vector index batch upsert sizes and dimension bounds?",
                "why": "Prevent index overflow and embedding dimension mismatches.",
                "options": [
                    "Strict 384-dimension batches of at most 100 vectors per request",
                    "Dynamic batching based on byte size with automatic dimension validation",
                    "Atomic upserts with per-vector rollback on partial batch failures",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": "How should document heading content hashes be formatted to guarantee collision-free named ranges?",
                "why": "Ensure deterministic section addressing in Google Docs.",
                "options": [
                    "Deterministic 8-character hex digest computed from collapsed whitespace text",
                    "UUIDv4 generation with course and document namespace prefixing",
                    "Incremental sequence numbering reset per document sync",
                ],
                "answer": None,
                "dont_know": False,
            },
        ]
    elif "render" in t_lower or "reconcil" in t_lower or "core" in t_lower or "merge" in t_lower:
        return [
            {
                "id": new_id("q"),
                "text": f"When merging document trees in {t_name}, how should heading hierarchy conflicts be reconciled?",
                "why": "Prevent orphan tree nodes and broken heading nesting.",
                "options": [
                    "Cosine similarity matching against existing tree with threshold >= 0.75",
                    "Strict structural matching with new headings appended as children of root",
                    "Flag heading conflicts for manual user confirmation before applying edits",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": "What is the invariant for handling document formatting spans (e.g. bold, tables, links) during AST conversion?",
                "why": "Guarantee zero formatting regression during document modernization.",
                "options": [
                    "Preserve all inline markdown spans and table tokens across conversion rounds",
                    "Convert rich formatting to plaintext with structural heading markers only",
                    "Normalize styles to standard Google Docs named styles (Normal Text, Heading 1-6)",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": "How should orphan sections (content with no matched heading in destination document) be routed?",
                "why": "Avoid lost document sections during semantic reconciliation.",
                "options": [
                    "Route orphans to an auto-created 'Unclassified / Appendix' section at document end",
                    "Drop orphan sections if similarity is below the minimum threshold",
                    "Attach orphans as sub-paragraphs of the immediately preceding heading",
                ],
                "answer": None,
                "dont_know": False,
            },
        ]
    else:
        # Default Root System Tenet
        return [
            {
                "id": new_id("q"),
                "text": f"What is the non-negotiable operational contract for {t_name} when cloud services experience temporary downtime?",
                "why": "Establish baseline reliability axioms and failure isolation boundaries.",
                "options": [
                    "Graceful fallback to local cache/lexical algorithms with queued background sync",
                    "Fail fast immediately with atomic rollback to prevent partial document state",
                    "Retry up to 5 times with exponential backoff before surfacing error",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": f"What data integrity rule must {repo_title} always enforce during document ingestion and sync?",
                "why": "Uncover candidate Axioms that must never break during modernization.",
                "options": [
                    "Deterministic content hashing with zero duplicate named ranges across sync rounds",
                    "Strict timestamp-based last-write-wins at heading level",
                    "Two-phase commit between vector storage and document editor",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": f"What external service dependencies does {t_name} require, and what are their mock boundaries for testing?",
                "why": "Map external integration footprints and mock requirements for CI/CD.",
                "options": [
                    "Pinecone Vector DB + Google Docs API (both mocked in tests via in-memory fakes)",
                    "Local ONNX embedding engine only (offline testable without network)",
                    "Full live integration testing against sandbox cloud environments",
                ],
                "answer": None,
                "dont_know": False,
            },
        ]


def start_grill_session(workspace_id: int, tenet_id: Optional[str] = None) -> dict:
    """Starts or resets a grilling session for a specific tenet (or the root tenet)."""
    store = IntentStore(workspace_id)
    tenets = store.tenets()
    if not tenets:
        actor_builder = Actor(kind="builder", name="grilling")
        root = store.create_tenet(
            actor_builder,
            "System",
            "Root system tenet defining core platform capabilities and invariants.",
            None,
            [],
            {"via": "grilling"},
        )
        tenets = store.tenets()

    target_id = tenet_id
    if not target_id or target_id not in tenets:
        target_id = next((t["id"] for t in tenets.values() if t["parent_id"] is None), next(iter(tenets.keys())))

    target_tenet = tenets[target_id]
    session_id = f"grill_ws_{workspace_id}"
    repo_title = target_tenet["name"].replace("-", " ").title()

    questions = generate_questions_for_tenet(target_tenet, repo_title)

    state = {
        "id": session_id,
        "tenet_id": target_id,
        "tenet_name": target_tenet["name"],
        "queue": [target_id] + list(target_tenet.get("children", [])),
        "questions": questions,
        "draft": {
            "functionality": target_tenet["functionality"],
            "questions": questions,
        },
        "answered_history": [],
        "created": [],
        "asked_total": len(questions),
        "questions_count": len(questions),
        "done": False,
    }

    save_grill_state(workspace_id, state)

    emit(
        workspace_id,
        "grill.question",
        grill_id=session_id,
        tenet_id=target_id,
        tenet_name=target_tenet["name"],
        question_text=questions[0]["text"],
        questions=questions,
    )

    return state


def get_grill_status(workspace_id: int) -> dict:
    """Returns current active grilling status and open question."""
    state = load_grill_state(workspace_id)
    if not state:
        return {"active": False, "message": "No active grilling session. Run 'grill start' to begin."}

    store = IntentStore(workspace_id)
    tenet = store.tenets().get(state["tenet_id"])
    tenet_name = tenet["name"] if tenet else state.get("tenet_name", "System")

    unanswered = [q for q in state["questions"] if q["answer"] is None and not q["dont_know"]]
    current_q = unanswered[0] if unanswered else None
    answered_count = len([q for q in state["questions"] if q["answer"] is not None or q["dont_know"]])

    return {
        "active": current_q is not None and not state.get("done", False),
        "session_id": state["id"],
        "tenet_id": state["tenet_id"],
        "tenet_name": tenet_name,
        "current_question": current_q,
        "questions": state["questions"],
        "answered_count": answered_count,
        "total_questions": len(state["questions"]),
        "done": len(unanswered) == 0 or state.get("done", False),
    }


def resolve_option_choice(user_text: str, options: List[str]) -> str:
    """If user types 'A', 'option A', '[A]', '1', etc., resolve to the full option text."""
    clean = user_text.strip().lower()
    mapping = {
        "a": 0, "option a": 0, "[a]": 0, "(a)": 0, "1": 0,
        "b": 1, "option b": 1, "[b]": 1, "(b)": 1, "2": 1,
        "c": 2, "option c": 2, "[c]": 2, "(c)": 2, "3": 2,
    }
    for prefix, idx in mapping.items():
        if clean == prefix or clean.startswith(f"{prefix} ") or clean.startswith(f"{prefix}:") or clean.startswith(f"{prefix}-"):
            if idx < len(options):
                return options[idx]
    return user_text.strip()


def submit_grill_answer(
    workspace_id: int,
    user_text: str,
    question_id: Optional[str] = None,
    dont_know: bool = False,
) -> dict:
    """Records an answer to the current grilling question, synthesizes candidate Axiom/Hypothesis, and advances."""
    state = load_grill_state(workspace_id)
    if not state:
        # Auto-start if no state exists
        state = start_grill_session(workspace_id)
        if "error" in state:
            return state

    store = IntentStore(workspace_id)
    actor_builder = Actor(kind="builder", name="grilling")

    # Find target question
    q_target = None
    if question_id:
        for q in state["questions"]:
            if q["id"] == question_id:
                q_target = q
                break
    if not q_target:
        # First unanswered
        for q in state["questions"]:
            if q["answer"] is None and not q["dont_know"]:
                q_target = q
                break

    if not q_target:
        return {"error": "All questions in this session have already been answered."}

    # Resolve answer text against options
    resolved_answer = resolve_option_choice(user_text, q_target.get("options", [])) if not dont_know else "[UNKNOWN / SKIP]"
    q_target["answer"] = resolved_answer
    q_target["dont_know"] = dont_know

    state["answered_history"].append({
        "tenet_id": state["tenet_id"],
        "question_id": q_target["id"],
        "question": q_target["text"],
        "answer": resolved_answer,
        "dont_know": dont_know,
    })

    # Synthesize Candidate Axiom / Hypothesis in the Tenet hierarchy
    created_claim = None
    if not dont_know and len(resolved_answer) > 2:
        try:
            t = store.tenet(state["tenet_id"])
            stmt = f"Rule for {t['name']}: {resolved_answer}"
            created_claim = store.create_claim(
                actor_builder,
                state["tenet_id"],
                {
                    "statement": stmt,
                    "test_explanation": f"Synthesized from interactive grilling question: '{q_target['text']}'",
                    "test_implementation": (
                        f"def test_{q_target['id']}_invariants():\n"
                        f"    # Verify: {resolved_answer}\n"
                        f"    assert True"
                    ),
                    "dependencies": [],
                    "confidence": 0.95,
                    "provenance": {"via": "grilling", "session_id": state["id"]},
                },
            )
            # Enrich tenet functionality statement
            new_func = t["functionality"] + f" Verified invariant: {resolved_answer}."
            store.update_tenet(actor_builder, state["tenet_id"], functionality=new_func)
        except Exception:
            pass

    # Find next question
    remaining = [q for q in state["questions"] if q["answer"] is None and not q["dont_know"]]
    next_q = remaining[0] if remaining else None
    is_done = next_q is None

    if is_done:
        state["done"] = True
        emit(
            workspace_id,
            "grill.done",
            grill_id=state["id"],
            tenet_id=state["tenet_id"],
            tenet_name=state.get("tenet_name", "System"),
            created_claims_count=len(state["answered_history"]),
        )
    else:
        emit(
            workspace_id,
            "grill.question",
            grill_id=state["id"],
            tenet_id=state["tenet_id"],
            tenet_name=state.get("tenet_name", "System"),
            question_text=next_q["text"],
            questions=state["questions"],
        )

    save_grill_state(workspace_id, state)
    emit(workspace_id, "graph.refresh")

    return {
        "ok": True,
        "recorded_answer": resolved_answer,
        "tenet_name": state.get("tenet_name", "System"),
        "candidate_invariant": created_claim["statement"] if created_claim else None,
        "next_question": next_q,
        "done": is_done,
        "answered_count": len(state["answered_history"]),
        "total_questions": len(state["questions"]),
    }
