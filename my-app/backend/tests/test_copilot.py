"""Pytest test suite for Agent 2 Copilot & Invariant Test Orchestrator."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_endpoint():
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "service" in data


def test_chat_with_agent_handles_dummy_swagger():
    res = client.post("/api/chat", json={"message": "string", "selected_node_ids": ["string"]})
    assert res.status_code == 200
    data = res.json()
    assert "content" in data
    assert "token_metrics" in data
    assert "session_id" in data


def test_dual_benchmark_compare():
    res = client.post("/api/chat/compare", json={"message": "How does session auth work in the monolith?"})
    assert res.status_code == 200
    data = res.json()
    assert data["percentage_saved"] > 70.0
    assert data["tokens_saved"] > 0
    assert "raw_bot" in data
    assert "intent_bot" in data


def test_generate_deterministic_tests():
    res = client.post("/api/generate-tests", json={"node_id": "payment_gateway_processor", "framework": "pytest"})
    assert res.status_code == 200
    data = res.json()
    assert data["node_id"] == "payment_gateway_processor"
    assert len(data["invariants_covered"]) >= 2
    assert "def test_" in data["test_code"]


def test_run_invariant_tests():
    res = client.post("/api/run-tests", json={"node_id": "auth_flow_validate_session"})
    assert res.status_code == 200
    data = res.json()
    assert data["overall_status"] in ("PASSED", "FAILED")
    assert data["total_tests_run"] > 0


def test_extract_intent_from_code():
    snippet = "def calculate_discount(price, code):\n    if price < 0: raise ValueError()\n    return price * 0.9"
    res = client.post("/api/extract-intent", json={
        "code_snippet": snippet,
        "file_path": "src/sales/promo.py",
        "language": "python"
    })
    assert res.status_code == 200
    data = res.json()
    assert "node" in data
    assert data["node"]["node_id"] == "flow_calculate_discount"


def test_graph_and_blast_radius():
    r_graph = client.get("/api/graph")
    assert r_graph.status_code == 200
    graph = r_graph.json()
    assert len(graph["nodes"]) >= 5

    r_blast = client.get("/api/nodes/auth_flow_validate_session/blast-radius")
    assert r_blast.status_code == 200
    blast = r_blast.json()
    assert "total_downstream_blast_radius" in blast
    assert blast["total_downstream_blast_radius"] > 0


def test_session_persistence_and_messages():
    # 1. Invalid session -> 404
    r_bogus = client.post("/api/chat", json={
        "message": "hello",
        "session_id": "bogus-uuid-does-not-exist"
    })
    assert r_bogus.status_code == 404

    # 2. Start a new chat session
    r_chat = client.post("/api/chat", json={"message": "What invariants protect the system?"})
    assert r_chat.status_code == 200
    session_id = r_chat.json()["session_id"]

    # 3. List sessions
    r_list = client.get("/api/sessions")
    assert r_list.status_code == 200
    sessions = r_list.json()
    assert any(s["id"] == session_id for s in sessions)

    # 4. Load messages for that session
    r_msgs = client.get(f"/api/sessions/{session_id}/messages")
    assert r_msgs.status_code == 200
    msgs = r_msgs.json()
    assert len(msgs) >= 2


def test_pronoun_context_retrieval_followup():
    # Turn 1
    r_turn1 = client.post("/api/chat", json={
        "message": "What business invariants protect payment processing?"
    })
    assert r_turn1.status_code == 200
    data1 = r_turn1.json()
    session_id = data1["session_id"]

    # Turn 2: Unpinned pronoun "it"
    r_turn2 = client.post("/api/chat", json={
        "session_id": session_id,
        "message": "What depends on it?"
    })
    assert r_turn2.status_code == 200
    data2 = r_turn2.json()
    retrieved = " ".join(data2["retrieved_items"]).lower()
    assert "payment" in retrieved


def test_frontend_ui_bridge_contracts():
    repo = "test-owner/test-repo"

    # 1. POST /api/repos/:repo/ask
    r_ask = client.post(f"/api/repos/{repo}/ask", json={
        "question": "What is the auth flow?",
        "context": "Context from graph"
    })
    assert r_ask.status_code == 200
    assert "answer" in r_ask.json()

    # 2. POST /api/repos/:repo/nodes/:id/tests
    r_tests = client.post(f"/api/repos/{repo}/nodes/payment_gateway_processor/tests")
    assert r_tests.status_code == 200
    tests_data = r_tests.json()
    assert tests_data["node_id"] == "payment_gateway_processor"
    assert len(tests_data["tests"]) >= 2

    # 3. GET /api/repos/:repo/graph
    # A GitHub repo (owner/name) is the signed-in user's own data: no session, no graph.
    assert client.get(f"/api/repos/{repo}/graph").status_code == 401
    # The demo graph is served at /api/graph ("/api/repos/<name>/graph" belongs to the connected-repo router).
    r_graph = client.get("/api/graph")
    assert r_graph.status_code == 200
    assert "nodes" in r_graph.json()
