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


def test_rich_ast_annotation_generation():
    """Verify that generate_annotations_for_file extracts real AST classes, methods, and chunk comments."""
    from app.pipeline import generate_annotations_for_file

    sample_code = '''
"""Vector similarity client for Pinecone indexes."""
from typing import List
import numpy as np

def content_hash(text: str) -> str:
    """Deterministic 8-character hash."""
    return "abcdef12"

class VectorDBManager:
    """Manages Pinecone index operations."""
    def __init__(self, index_name: str):
        self.index_name = index_name

    def query_similar_paragraph(self, vector: List[float], top_k: int = 5):
        """Query Pinecone for matching document paragraphs."""
        return []
'''
    annot = generate_annotations_for_file("src/services/pinecone_client.py", sample_code)
    summary = annot["summary"]

    assert "Vector similarity client" in summary["purpose"]
    assert any("query_similar_paragraph" in r for r in summary["responsibilities"])
    assert any("content_hash" in r for r in summary["responsibilities"])
    assert "numpy" in summary["dependencies"]
    assert len(annot["chunks"]) >= 2
    assert any("VectorDBManager" in c["comment"] for c in annot["chunks"])


def test_interactive_grilling_and_chatbot_flow():
    """Verify interactive tenet grilling via direct API endpoints and the chatbot /ask bridge."""
    from app import db, sessions
    from app.config import settings

    # Setup authenticated client
    user = {"id": 8888, "login": "grill-tester", "avatar_url": "https://example.com/avatar.png"}
    user_id = db.upsert_user(user["id"], user["login"])
    sid = sessions.create_session("dev_token", user, user_id)
    auth_client = TestClient(app, cookies={settings.session_cookie: sid})

    # Connect repository
    r_conn = auth_client.post("/api/repos/test-team/superdoc-repo/connect")
    assert r_conn.status_code == 200

    # Start grilling session
    r_start = auth_client.post("/api/repos/test-team/superdoc-repo/grill/start")
    assert r_start.status_code == 200
    grill_data = r_start.json()
    assert grill_data["questions_count"] == 3
    first_q = grill_data["questions"][0]
    assert "text" in first_q
    assert len(first_q["options"]) >= 2

    # Check status endpoint
    r_status = auth_client.get("/api/repos/test-team/superdoc-repo/grill")
    assert r_status.status_code == 200
    status_data = r_status.json()
    assert status_data["active"] is True
    assert status_data["total_questions"] == 3

    # Answer question 1 via option choice "A"
    r_ans = auth_client.post("/api/repos/test-team/superdoc-repo/grill/answer", json={
        "answer": "A",
        "question_id": first_q["id"]
    })
    assert r_ans.status_code == 200
    ans_data = r_ans.json()
    assert ans_data["ok"] is True
    assert ans_data["candidate_invariant"] is not None
    assert ans_data["next_question"] is not None
    assert ans_data["answered_count"] == 1

    # Chatbot interaction: answering question 2 via POST /api/repos/{repo}/ask
    r_chat = client.post("/api/repos/test-team/superdoc-repo/ask", json={
        "question": "Option B"
    })
    assert r_chat.status_code == 200
    chat_resp = r_chat.json()
    assert "Answer Recorded" in chat_resp["answer"] or "Question" in chat_resp["answer"]


def test_tenet_and_node_modification():
    """Verify modification of tenets, claims, and codebase intent nodes."""
    from app import db, sessions
    from app.config import settings

    user = {"id": 9999, "login": "mod-tester", "avatar_url": "https://example.com/avatar.png"}
    user_id = db.upsert_user(user["id"], user["login"])
    sid = sessions.create_session("dev_token", user, user_id)
    auth_client = TestClient(app, cookies={settings.session_cookie: sid})

    # Connect repo and run initial pipeline
    r_conn = auth_client.post("/api/repos/mod-org/mod-repo/connect")
    assert r_conn.status_code == 200
    ws_id = r_conn.json()["id"]

    # Read tree
    tree_res = auth_client.get(f"/api/workspaces/{ws_id}/tree")
    assert tree_res.status_code == 200
    tree = tree_res.json()
    root_id = tree["root_id"]

    if root_id:
        # Test modifying tenet name and open unknowns
        mod_res = auth_client.patch(f"/api/workspaces/{ws_id}/tenets/{root_id}", json={
            "name": "Modified Root Tenet",
            "functionality": "Updated functionality statement",
            "open_unknowns": ["Does session token expire after 15m or 1h?"]
        })
        assert mod_res.status_code == 200
        data = mod_res.json()
        assert data["name"] == "Modified Root Tenet"
        assert data["functionality"] == "Updated functionality statement"
        assert "Does session token expire after 15m or 1h?" in data["open_unknowns"]

        # Test adding a claim to this tenet
        claim_res = auth_client.post(f"/api/workspaces/{ws_id}/tenets/{root_id}/claims", json={
            "statement": "Charges over $10,000 must flag as FRAUD_HOLD",
            "test_explanation": "Prevents large unauthorized payments",
            "test_implementation": "INVOKE billing. ASSERT charge_status == FRAUD_HOLD",
            "confidence": 0.85
        })
        assert claim_res.status_code == 201
        claim_id = claim_res.json()["id"]

        # Test modifying the hypothesis
        hyp_res = auth_client.patch(f"/api/workspaces/{ws_id}/claims/{claim_id}", json={
            "statement": "Charges strictly over $10,000 enter FRAUD_HOLD",
            "confidence": 0.95
        })
        assert hyp_res.status_code == 200
        assert hyp_res.json()["confidence"] == 0.95
        assert hyp_res.json()["statement"] == "Charges strictly over $10,000 enter FRAUD_HOLD"

    # Test modifying an IntentNode in the graph
    node_res = client.post("/api/graph/nodes", json={
        "node_id": "auth_flow_validate_session",
        "name": "Updated Validate Session",
        "source_file": "src/legacy/auth/session.py",
        "intent_summary": "Cryptographic HMAC check with IP binding",
        "business_invariants": [
            "Expired session tokens immediately reject with 401 Unauthorized.",
            "IP mismatch triggers immediate session revocation."
        ],
        "inputs": {"auth_header": "Bearer token"},
        "outputs": {"user_context": "Hydrated user principal"}
    })
    assert node_res.status_code == 200
    node_data = node_res.json()
    assert node_data["name"] == "Updated Validate Session"
    assert len(node_data["business_invariants"]) == 2



