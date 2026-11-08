"""Integration test suite verifying frontend-backend contracts and API wiring."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_and_health():
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "online"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_frontend_graph_api():
    """Verify /api/graph returns the full Functional Intent Graph required by Dashboard and GraphCanvas."""
    res = client.get("/api/graph")
    assert res.status_code == 200
    data = res.json()
    assert "repo_name" in data
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) >= 5

    # Check node schema
    first = data["nodes"][0]
    assert "node_id" in first
    assert "name" in first
    assert "source_file" in first
    assert "intent_summary" in first
    assert "business_invariants" in first
    assert isinstance(first["business_invariants"], list)


def test_frontend_ask_api_bare_and_full_repo():
    """Verify POST /api/repos/{repo}/ask works for both demo (bare) and full owner/name repos."""
    # Demo bare repo name
    res_bare = client.post("/api/repos/legacy-monolith-app/ask", json={
        "question": "How does session token validation work?",
        "context": "Node: auth_flow_validate_session"
    })
    assert res_bare.status_code == 200
    data_bare = res_bare.json()
    assert "answer" in data_bare
    assert len(data_bare["answer"]) > 0

    # Full repo path with owner
    res_full = client.post("/api/repos/vishjit/legacy-monolith-app/ask", json={
        "question": "What happens if token expires?",
        "context": "auth_flow_validate_session"
    })
    assert res_full.status_code == 200
    data_full = res_full.json()
    assert "answer" in data_full
    assert len(data_full["answer"]) > 0


def test_frontend_generate_tests_api():
    """Verify POST /api/repos/{repo}/nodes/{id}/tests generates deterministic tests for the frontend inspector/terminal."""
    res = client.post("/api/repos/legacy-monolith-app/nodes/auth_flow_validate_session/tests")
    assert res.status_code == 200
    data = res.json()
    assert data["node_id"] == "auth_flow_validate_session"
    assert "tests" in data
    assert len(data["tests"]) >= 1

    first_test = data["tests"][0]
    assert "name" in first_test
    assert "code" in first_test
    assert "invariant" in first_test
    assert "def test_" in first_test["code"]


def test_frontend_websocket_streams():
    """Verify WebSockets send the initial graph snapshot and status frame."""
    # 1. Single repo stream
    with client.websocket_connect("/api/repos/legacy-monolith-app/graph") as ws:
        msg1 = ws.receive_json()
        assert msg1["type"] == "snapshot"
        assert len(msg1["graph"]["nodes"]) >= 5
        msg2 = ws.receive_json()
        assert msg2["type"] == "status"
        assert msg2["stage"] == 1

    # 2. Direct graph stream
    with client.websocket_connect("/api/graph") as ws:
        msg1 = ws.receive_json()
        assert msg1["type"] == "snapshot"
        assert len(msg1["graph"]["nodes"]) >= 5
        msg2 = ws.receive_json()
        assert msg2["type"] == "status"
        assert msg2["stage"] == 1


def test_auth_me_unauthenticated():
    """Verify /auth/me returns 401 when no user session cookie is provided, which frontend treats as null."""
    res = client.get("/auth/me")
    assert res.status_code == 401
    assert res.json()["detail"] == "Not authenticated"


def test_chat_session_lifecycle():
    """Verify the copilot chat API creates sessions and persists message history."""
    # Step 1: Send message
    res = client.post("/api/chat", json={
        "message": "What invariants apply to payment processing?",
        "selected_node_ids": ["payment_gateway_processor"]
    })
    assert res.status_code == 200
    data = res.json()
    session_id = data["session_id"]
    assert session_id is not None
    assert "content" in data
    assert "token_metrics" in data

    # Step 2: Retrieve messages
    res_msgs = client.get(f"/api/sessions/{session_id}/messages")
    assert res_msgs.status_code == 200
    msgs = res_msgs.json()
    assert len(msgs) >= 2
    assert any(m["role"] == "user" for m in msgs)
    assert any(m["role"] == "assistant" for m in msgs)


def test_node_details_and_blast_radius():
    """Verify node inspection and blast-radius APIs."""
    # Node details
    res_node = client.get("/api/nodes/auth_flow_validate_session")
    assert res_node.status_code == 200
    node = res_node.json()
    assert node["node_id"] == "auth_flow_validate_session"
    assert len(node["business_invariants"]) > 0

    # Blast radius
    res_blast = client.get("/api/nodes/auth_flow_validate_session/blast-radius")
    assert res_blast.status_code == 200
    blast = res_blast.json()
    assert "source_node" in blast
    assert "direct_dependencies" in blast
    assert "total_downstream_blast_radius" in blast
    assert blast["total_downstream_blast_radius"] >= 1


def test_session_persistence_across_memory_wipe():
    """Verify that user sessions persist in SQLite and survive memory cache flushes (e.g. server reloads)."""
    from app import db, sessions
    from app.config import settings

    # 1. Create a user and session
    user = {"id": 9999, "login": "test-resilient-user", "avatar_url": "https://example.com/avatar.png"}
    user_id = db.upsert_user(user["id"], user["login"])
    sid = sessions.create_session("dev_test_token", user, user_id)

    # Verify session is retrievable
    s1 = sessions.get_session(sid)
    assert s1 is not None
    assert s1.user["login"] == "test-resilient-user"

    # 2. Simulate server reload / process restart by clearing the in-memory dict
    sessions._sessions.clear()
    assert sid not in sessions._sessions

    # 3. get_session must rehydrate from SQLite
    s2 = sessions.get_session(sid)
    assert s2 is not None
    assert s2.user["login"] == "test-resilient-user"
    assert s2.user_id == user_id

    # 4. HTTP client with session cookie must succeed on /auth/me
    auth_client = TestClient(app, cookies={settings.session_cookie: sid})
    res = auth_client.get("/auth/me")
    assert res.status_code == 200
    assert res.json()["login"] == "test-resilient-user"

    # 5. Connect repo and access workspace tree
    res_conn = auth_client.post("/api/repos/test-owner/test-repo/connect")
    assert res_conn.status_code == 200
    ws_id = res_conn.json()["id"]

    # Clear memory again to simulate reload during pipeline execution
    sessions._sessions.clear()

    # Workspace tree must remain accessible
    res_tree = auth_client.get(f"/api/workspaces/{ws_id}/tree")
    assert res_tree.status_code == 200
    assert "tenets" in res_tree.json()

