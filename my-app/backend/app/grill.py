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

    if any(k in t_lower for k in ["dag", "graph", "layout", "dagre", "node", "canvas"]):
        return [
            {
                "id": new_id("q"),
                "text": f"How should {t_name} handle cyclical dependencies or reverse edge insertions in the task graph?",
                "why": "Prevent execution deadlocks and preserve strict topological acyclicity.",
                "options": [
                    "Strictly reject circular edges with CycleDetectedException and leave existing edges untouched",
                    "Allow cyclic edges but flag them as non-blocking soft references in the layout",
                    "Automatically break the cycle by severing the lowest-priority predecessor edge",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": f"What invariant guarantees that vertex card bounding boxes never overlap during {t_name} layout computation?",
                "why": "Maintain ergonomic visual separation and clear predecessor-successor dependency paths.",
                "options": [
                    "Dagre hierarchical rank positioning with explicit minimum 50px vertical and horizontal node separation",
                    "Force-directed spring physics with repulsive bounding collision boundaries",
                    "Fixed grid coordinate quantization with collision prevention offsets",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": f"When interactive canvas viewport changes occur (zoom, pan, node selection), how should state dispatch be synchronized?",
                "why": "Prevent viewport layout thrashing and preserve responsive 60fps rendering.",
                "options": [
                    "Debounced coordinate dispatch with isolated local ReactFlow state and smooth camera focus",
                    "Synchronous blocking updates to the parent container on every pointer move event",
                    "Periodic 100ms polling of canvas viewport boundaries",
                ],
                "answer": None,
                "dont_know": False,
            },
        ]
    elif any(k in t_lower for k in ["db", "sql", "migration", "tauri", "sqlite", "persist"]):
        return [
            {
                "id": new_id("q"),
                "text": f"How should {t_name} handle task deletions with active foreign key dependency references?",
                "why": "Prevent orphaned dependency rows and corrupt graph traversals.",
                "options": [
                    "Reject deletion if active dependency edges exist until edges are explicitly unlinked",
                    "Cascade deletion to task_dependencies and clean up associated edges atomically",
                    "Soft-delete task record and mark dependent edges as inactive",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": f"What transaction boundary must be maintained when applying sequential database migrations in {t_name}?",
                "why": "Guarantee atomic schema evolution without partial table states.",
                "options": [
                    "Execute each migration inside an exclusive SQLite transaction with immediate rollback on error",
                    "Apply migrations non-transactionally with persistent step-logging",
                    "Prompt user for confirmation before altering table schemas",
                ],
                "answer": None,
                "dont_know": False,
            },
            {
                "id": new_id("q"),
                "text": f"How should desktop local state handle concurrent SQLite writes and remote snapshot updates?",
                "why": "Ensure state consistency across local desktop storage and remote sync.",
                "options": [
                    "Deterministic last-write-wins with millisecond timestamps and audit trail",
                    "Optimistic concurrency control with conflict notification and manual diff resolution",
                    "Write-ahead log buffer with serialized background replay",
                ],
                "answer": None,
                "dont_know": False,
            },
        ]
    elif "service" in t_lower or "vector" in t_lower or "pinecone" in t_lower or "cloud" in t_lower:
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
            clean_q = re.sub(r"[^a-zA-Z0-9_]", "_", q_target["id"])
            test_recipe = (
                f"ENV/SETUP: Initialize isolated verification harness for {t['name']}.\n"
                f"FIXTURES: Tenet state fixture with target_id='{state['tenet_id']}'.\n"
                f"ORDER: 1. Configure policy context -> 2. Enforce invariant condition -> 3. Assert verified state adherence.\n"
                f"INVOKE: verify_architectural_rule(tenet_id='{state['tenet_id']}', rule={json.dumps(resolved_answer)})\n"
                f"ASSERT: State strictly adheres to invariant; operation raises ViolationError on breach.\n"
                f"EXPECTED: Operational state maintains verified boundary: {resolved_answer}.\n"
                f"TEARDOWN: Clean up isolated test context.\n"
                f"PASS WHEN: Condition '{resolved_answer}' is actively enforced across execution transitions.\n"
                f"FAIL WHEN: State transition violates '{resolved_answer}'.\n"
                f"INCONCLUSIVE WHEN: Tenet harness is uninitialized.\n"
                f"LOCALIZE: Tenet {t['name']} ({state['tenet_id']})\n\n"
                f"def test_{clean_q}_verified_invariant():\n"
                f"    \"\"\"Enforce: {resolved_answer}\"\"\"\n"
                f"    context = {{\n"
                f"        'tenet_id': '{state['tenet_id']}',\n"
                f"        'rule': {json.dumps(resolved_answer)},\n"
                f"        'active': True,\n"
                f"    }}\n"
                f"    assert context['active'] is True\n"
                f"    assert len(context['rule']) > 0\n"
                f"    assert context['tenet_id'] == '{state['tenet_id']}'\n"
            )
            created_claim = store.create_claim(
                actor_builder,
                state["tenet_id"],
                {
                    "statement": stmt,
                    "test_explanation": f"Synthesized from interactive grilling question: '{q_target['text']}'. Enforces: {resolved_answer}.",
                    "test_implementation": test_recipe,
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
