"""Integration tests for Two-Mode Terminal (Section 10.3)."""
import ast
import asyncio
from pathlib import Path
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.copilot.api.routes import router
from app.intent.store import IntentStore
from app.main import app
import app.chat_router as top_chat_router
import app.copilot.chat_router as copilot_chat_router
from app import events, db, sessions
from app.actors import Actor
from intentflow.llm import FakeNemotron
from intentflow.models import (
    CandidateReviewItem,
    CandidateReviewResult,
    PromptVerdict,
    QueryAnswerPayload,
    RouterResult,
)


@pytest.fixture
def chat_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "test.db"))

    # Workspace 1 setup
    wid = 1
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users (id, github_id, login, created_at, last_login) VALUES (1, 1, 'test_user', 0.0, 0.0)")
        conn.execute("INSERT OR REPLACE INTO repos (id, user_id, full_name, default_branch, last_synced_sha, connected_at) VALUES (1, 1, 'acme/legacy', 'main', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 0.0)")

    store = IntentStore(wid)
    store.root.mkdir(parents=True, exist_ok=True)

    repo_dir = data_dir / "workspaces" / str(wid) / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    payments_file = repo_dir / "src" / "payments" / "charge.py"
    payments_file.parent.mkdir(parents=True, exist_ok=True)
    payments_file.write_text("def charge(amount):\n    if amount <= 0: raise ValueError()\n    return True\n")

    # Tenets
    actor = Actor("user", "test_user")
    actor.user_id = 1

    root_t = store.create_tenet(actor, name="Root Architecture", functionality="Core system root", parent_id=None, cross_cutting=[], provenance={})
    pay_t = store.create_tenet(actor, name="Payment Subsystem", functionality="Processes charges and refunds", parent_id=root_t["id"], cross_cutting=[], provenance={})
    engine_actor = Actor("engine", "annotator")
    store.set_links(engine_actor, pay_t["id"], [{"path": "src/payments/charge.py"}])

    # Annotation
    store.put_annotation(engine_actor, "src/payments/charge.py", {
        "purpose": "Handles credit card charging",
        "responsibilities": ["charge cards", "validate amounts"],
        "invariants": ["amount > 0"],
    })

    sess_id = sessions.create_session("tok", {"id": 1, "login": "test_user"}, 1)

    return {
        "wid": wid,
        "store": store,
        "repo_dir": repo_dir,
        "root_tenet_id": root_t["id"],
        "pay_tenet_id": pay_t["id"],
        "session_id": sess_id,
    }


def test_1_selected_tenet_generation(chat_env, monkeypatch):
    """1. Selected tenet + 'draft 3 invariants for this' => hypotheses created on THAT tenet; provenance decision_source=jev_llm."""
    client = TestClient(app)
    wid = chat_env["wid"]
    pay_tid = chat_env["pay_tenet_id"]
    store = chat_env["store"]

    fake_llm = FakeNemotron()
    # 1. Jev route call
    fake_llm.queue_response("fast", RouterResult(
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=0.92,
        reason="user wants invariants",
        requested_count=3,
    ))
    # 2. Generator generate candidates call
    gen_tier = getattr(settings, "nemotron_tier_generator", "deep")
    fake_llm.queue_response(gen_tier, {
        "candidates": [
            {"statement": "Amount must always be strictly positive", "test_explanation": "Test charge(-1)"},
            {"statement": "Payment returns boolean True on success", "test_explanation": "Assert charge(10) is True"},
        ]
    })
    # 3. Jev candidate review call
    fake_llm.queue_response("fast", CandidateReviewResult(
        results=[
            CandidateReviewItem(index=0, testable=True),
            CandidateReviewItem(index=1, testable=True),
        ]
    ))

    # Monkeypatch FakeNemotron in chat router
    orig_route_chat = top_chat_router.route_chat

    async def patched_route_chat(*args, **kwargs):
        kwargs["llm"] = fake_llm
        return await orig_route_chat(*args, **kwargs)

    monkeypatch.setattr(copilot_chat_router, "route_chat", patched_route_chat)
    monkeypatch.setattr(top_chat_router, "route_chat", patched_route_chat)

    res = client.post("/api/chat", json={
        "message": "draft 3 invariants for this",
        "workspace_id": wid,
        "selected_tenet_id": pay_tid,
        "allow_generation": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["route"]["verdict"] == "hypothesis_generation"
    assert data["route"]["approved"] is True
    assert data["generation"]["status"] == "completed"
    assert len(data["generation"]["claims_created"]) == 2

    # Verify claim in store
    claims = store.claims()
    assert len(claims) == 2
    for cid, c in claims.items():
        assert c["tenet_id"] == pay_tid
        assert c["provenance"]["decision_source"] == "jev_llm"


def test_2_query_mode_read_only(chat_env, monkeypatch):
    """2. 'what does the payment module do?' => query block, no claims created, changelog unchanged."""
    client = TestClient(app)
    wid = chat_env["wid"]
    store = chat_env["store"]

    fake_llm = FakeNemotron()
    fake_llm.queue_response("fast", RouterResult(
        verdict=PromptVerdict.QUERY,
        confidence=0.95,
        reason="informational query",
    ))
    fake_llm.queue_response("fast", QueryAnswerPayload(
        answer="The payment module processes charges [[file:src/payments/charge.py:1-3]].",
        confidence=0.9,
    ))

    orig_route_chat = top_chat_router.route_chat

    async def patched_route_chat(*args, **kwargs):
        kwargs["llm"] = fake_llm
        return await orig_route_chat(*args, **kwargs)

    monkeypatch.setattr(copilot_chat_router, "route_chat", patched_route_chat)
    monkeypatch.setattr(top_chat_router, "route_chat", patched_route_chat)

    clog_before = store.read_changelog()
    claims_before = len(store.claims())

    res = client.post("/api/chat", json={
        "message": "what does the payment module do?",
        "workspace_id": wid,
        "allow_generation": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["route"]["verdict"] == "query"
    assert data["query"] is not None
    assert "[[file:src/payments/charge.py:1-3]]" in data["query"]["answer"]
    assert len(store.claims()) == claims_before
    assert len(store.read_changelog()) == len(clog_before)


def test_3_query_with_and_without_selected_tenet(chat_env, monkeypatch):
    """3. Same message with and without selected_tenet_id for a query => both answer; selection only biases."""
    client = TestClient(app)
    wid = chat_env["wid"]
    pay_tid = chat_env["pay_tenet_id"]

    fake_llm = FakeNemotron(default_responses=[
        RouterResult(verdict=PromptVerdict.QUERY, confidence=0.9, reason="query"),
        QueryAnswerPayload(answer="Overview answer [[file:src/payments/charge.py]]", confidence=0.85),
    ])

    orig_route_chat = top_chat_router.route_chat

    async def patched_route_chat(*args, **kwargs):
        kwargs["llm"] = fake_llm
        return await orig_route_chat(*args, **kwargs)

    monkeypatch.setattr(copilot_chat_router, "route_chat", patched_route_chat)
    monkeypatch.setattr(top_chat_router, "route_chat", patched_route_chat)

    # 1. Without selected tenet
    res1 = client.post("/api/chat", json={
        "message": "How do payments work?",
        "workspace_id": wid,
        "selected_tenet_id": None,
    })
    assert res1.status_code == 200
    assert res1.json()["query"]["answer"] != ""

    # 2. With selected tenet
    res2 = client.post("/api/chat", json={
        "message": "How do payments work?",
        "workspace_id": wid,
        "selected_tenet_id": pay_tid,
    })
    assert res2.status_code == 200
    assert res2.json()["query"]["answer"] != ""


def test_4_axiom_request_refusal(chat_env, monkeypatch):
    """4. Axiom request => refusal; neither trigger called."""
    client = TestClient(app)
    wid = chat_env["wid"]

    trigger_called = False
    from intentflow import triggers

    async def mock_trigger_q(*args, **kwargs):
        nonlocal trigger_called
        trigger_called = True

    async def mock_trigger_g(*args, **kwargs):
        nonlocal trigger_called
        trigger_called = True

    monkeypatch.setattr(triggers, "trigger_query", mock_trigger_q)
    monkeypatch.setattr(triggers, "trigger_hypothesis_generation", mock_trigger_g)

    res = client.post("/api/chat", json={
        "message": "Make this claim an axiom right now",
        "workspace_id": wid,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["route"]["verdict"] == "axiom_modification_request"
    assert "Axioms are human-only" in data["content"]
    assert not trigger_called


def test_5_chat_and_ask_endpoint_parity(chat_env, monkeypatch):
    """5. Both /api/chat and /api/repos/{repo}/ask produce identical routing for the same input."""
    client = TestClient(app)
    wid = chat_env["wid"]

    fake_llm = FakeNemotron(default_responses=[
        RouterResult(verdict=PromptVerdict.QUERY, confidence=0.88, reason="query parity"),
        QueryAnswerPayload(answer="Identical query response", confidence=0.9),
        RouterResult(verdict=PromptVerdict.QUERY, confidence=0.88, reason="query parity"),
        QueryAnswerPayload(answer="Identical query response", confidence=0.9),
    ])

    orig_route_chat = top_chat_router.route_chat

    async def patched_route_chat(*args, **kwargs):
        kwargs["llm"] = fake_llm
        return await orig_route_chat(*args, **kwargs)

    monkeypatch.setattr(copilot_chat_router, "route_chat", patched_route_chat)
    monkeypatch.setattr(top_chat_router, "route_chat", patched_route_chat)

    res_chat = client.post("/api/chat", json={
        "message": "Where is charge.py located?",
        "workspace_id": wid,
    })
    res_ask = client.post("/api/repos/acme/legacy/ask", json={
        "question": "Where is charge.py located?",
        "workspace_id": wid,
    })

    assert res_chat.status_code == 200
    assert res_ask.status_code == 200
    chat_data = res_chat.json()
    ask_data = res_ask.json()

    assert chat_data["route"]["verdict"] == ask_data["route"]["verdict"]
    assert chat_data["route"]["confidence"] == ask_data["route"]["confidence"]


def test_6_progress_events_stage_order(chat_env, monkeypatch):
    """6. terminal.progress events arrive in stage order for generation and for queries."""
    wid = chat_env["wid"]
    pay_tid = chat_env["pay_tenet_id"]

    emitted_stages = []

    def mock_emit(workspace_id, event, **data):
        if event == "terminal.progress":
            emitted_stages.append((data.get("kind"), data.get("stage")))

    monkeypatch.setattr(events, "emit", mock_emit)

    fake_llm = FakeNemotron()
    # For generation:
    gen_tier = getattr(settings, "nemotron_tier_generator", "deep")
    fake_llm.queue_response(gen_tier, {
        "candidates": [{"statement": "Sample invariant", "test_explanation": "Test explanation"}]
    })
    fake_llm.queue_response("fast", CandidateReviewResult(
        results=[CandidateReviewItem(index=0, testable=True)]
    ))
    # For query:
    fake_llm.queue_response("fast", QueryAnswerPayload(answer="Answer with progress", confidence=0.9))

    # Test generation progress
    from intentflow.agents.hypothesis_generator import HypothesisGenerator
    from intentflow.models import JevDecision

    decision = JevDecision(
        decision_id="jd_test_prog",
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=1.0,
        source="explicit_user",
        approved=True,
        target_tenet_id=pay_tid,
    )
    gen = HypothesisGenerator(workspace=None, store=chat_env["store"], repo_dir=chat_env["repo_dir"], llm=fake_llm)
    asyncio.run(gen.generate(decision))

    gen_stages = [s for k, s in emitted_stages if k == "generation"]
    assert gen_stages == ["context", "generating", "validating", "reviewing", "saving"]

    # Test query progress
    emitted_stages.clear()
    from intentflow.agents.query_agent import CodebaseQueryEngine
    engine = CodebaseQueryEngine(workspace=None, store=chat_env["store"], repo_dir=chat_env["repo_dir"], llm=fake_llm)
    asyncio.run(engine.execute_query(message="Tell me about charge"))

    query_stages = [s for k, s in emitted_stages if k == "query"]
    assert query_stages == ["planning", "retrieving", "answering"]


def test_7_generation_timeout_behavior(chat_env, monkeypatch):
    """7. CHAT_GENERATION_TIMEOUT_SECONDS=1 with a slow fake => GENERATION_TIMEOUT, zero claims."""
    wid = chat_env["wid"]
    pay_tid = chat_env["pay_tenet_id"]
    store = chat_env["store"]

    monkeypatch.setattr(settings, "chat_generation_timeout_seconds", 0.01)

    class SlowNemotron(FakeNemotron):
        async def structured(self, tier, system, prompt, schema, **kwargs):
            await asyncio.sleep(0.05)
            return await super().structured(tier, system, prompt, schema, **kwargs)

    gen_tier = getattr(settings, "nemotron_tier_generator", "deep")
    slow_llm = SlowNemotron(default_responses=[
        {"candidates": [{"statement": "Slow invariant", "test_explanation": "Test"}]},
        CandidateReviewResult(results=[CandidateReviewItem(index=0, testable=True)]),
    ])

    from intentflow.agents.hypothesis_generator import HypothesisGenerator
    from intentflow.models import JevDecision

    decision = JevDecision(
        decision_id="jd_slow",
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=1.0,
        source="explicit_user",
        approved=True,
        target_tenet_id=pay_tid,
    )
    gen = HypothesisGenerator(workspace=None, store=store, repo_dir=chat_env["repo_dir"], llm=slow_llm)
    res = asyncio.run(gen.generate(decision))

    assert res.status == "failed"
    assert res.error_code == "GENERATION_TIMEOUT"
    assert len(res.claims_created) == 0


def test_8_workspace_query_endpoint(chat_env, monkeypatch):
    """8. POST /api/workspaces/{id}/query returns the same query block shape."""
    client = TestClient(app)
    wid = chat_env["wid"]

    fake_llm = FakeNemotron(default_responses=[
        QueryAnswerPayload(answer="Workspace query response [[file:src/payments/charge.py]]", confidence=0.88),
    ])

    from intentflow import triggers
    orig_trigger_q = triggers.trigger_query

    async def patched_trigger_q(*args, **kwargs):
        kwargs["llm"] = fake_llm
        return await orig_trigger_q(*args, **kwargs)

    monkeypatch.setattr(triggers, "trigger_query", patched_trigger_q)

    # Actor header or dev session
    client.cookies.set(settings.session_cookie, chat_env["session_id"])
    res = client.post(f"/api/workspaces/{wid}/query", json={
        "message": "Where is charge logic?",
    })
    assert res.status_code == 200
    data = res.json()
    assert "query" in data
    assert "answer" in data["query"]
    assert "citations" in data["query"]
    assert "usage" in data["query"]


def test_9_ast_triggers_and_query_agent():
    """9. AST test: triggers.py functions are called only from chat_router.py and the REST handlers; query_agent.py imports no store write APIs."""
    repo_root = Path(__file__).resolve().parents[2]
    backend_app = repo_root / "backend" / "app"
    intentflow_dir = repo_root / "intentflow"

    allowed_trigger_callers = {
        "chat_router.py",
        "routes.py",
        "verify_terminal_flow.py",
        "verify_hypothesis_flow.py",
    }

    trigger_functions = {"trigger_query", "trigger_hypothesis_generation"}

    # 1. Verify callers of triggers.py
    for py_file in list(backend_app.rglob("*.py")) + list(intentflow_dir.rglob("*.py")):
        if "tests" in py_file.parts or "scripts" in py_file.parts:
            continue
        code = py_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(code, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name in trigger_functions:
                    assert py_file.name in allowed_trigger_callers, (
                        f"Unauthorized caller of {func_name} in {py_file}"
                    )

    # 2. Verify query_agent.py imports no store write APIs
    query_agent_file = intentflow_dir / "agents" / "query_agent.py"
    qa_code = query_agent_file.read_text(encoding="utf-8")
    qa_tree = ast.parse(qa_code, filename=str(query_agent_file))

    forbidden_writes = {
        "create_claim", "update_claim", "update_hypothesis", "edit_axiom",
        "delete_tenet", "create_tenet", "update_tenet", "move_tenet",
        "promote", "demote", "scrap", "remake",
    }
    for node in ast.walk(qa_tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name not in forbidden_writes, (
                    f"query_agent.py illegally imports store write API: {alias.name}"
                )


def test_10_backward_compatibility():
    """10. Backward compatibility: existing test_copilot.py tests still pass unmodified for requests without workspace_id."""
    client = TestClient(app)
    res = client.post("/api/chat", json={"message": "ping without workspace", "selected_node_ids": []})
    assert res.status_code == 200
    data = res.json()
    assert "content" in data
    assert "token_metrics" in data
    assert data.get("route") is None
