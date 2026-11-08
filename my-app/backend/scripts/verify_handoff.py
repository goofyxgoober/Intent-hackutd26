import sys
from pathlib import Path

# Ensure my-app/backend is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
for p in [str(_BACKEND_DIR), str(_REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def verify_all():
    print("=== 1. VERIFYING BOGUS SESSION_ID RETURNS 404 ===")
    r_bogus = client.post("/api/chat", json={
        "message": "hello",
        "session_id": "bogus-uuid-does-not-exist"
    })
    print(f"Status: {r_bogus.status_code}")
    assert r_bogus.status_code == 404, f"Expected 404, got {r_bogus.status_code}: {r_bogus.text}"
    print("  -> PASS: Bogus session_id correctly returns 404!\n")

    print("=== 2. VERIFYING GET /api/sessions AND GET /api/sessions/{id}/messages ===")
    r_sessions = client.get("/api/sessions")
    print(f"GET /api/sessions status: {r_sessions.status_code}")
    assert r_sessions.status_code == 200
    sessions = r_sessions.json()
    print(f"Found {len(sessions)} session(s) in meta.db:")
    for s in sessions[:3]:
        print(f"  Session ID: {s['id']} | Title: {s['title'][:30]}... | Msg Count: {s['message_count']}")

    if sessions:
        sid = sessions[0]["id"]
        r_msgs = client.get(f"/api/sessions/{sid}/messages")
        assert r_msgs.status_code == 200
        msgs = r_msgs.json()
        print(f"\nLoaded {len(msgs)} messages from messages.db for session {sid}:")
        for m in msgs[:4]:
            print(f"  seq={m['seq']} role={m['role']} text={m['content'][:45]}...")
    print("  -> PASS: Session and message listing verified!\n")

    print("=== 3. VERIFYING CONTEXT RETRIEVAL ON FOLLOW-UP ('What depends on it?') ===")
    # Turn 1: Ask about payment processing
    r_turn1 = client.post("/api/chat", json={
        "message": "What business invariants protect payment processing?"
    })
    assert r_turn1.status_code == 200, f"Turn 1 failed: {r_turn1.text}"
    data_turn1 = r_turn1.json()
    new_session_id = data_turn1["session_id"]
    print(f"Turn 1 completed! Created session_id: {new_session_id}")
    print(f"Retrieved in Turn 1: {data_turn1['retrieved_items']}")

    # Turn 2: Unpinned follow-up with pronoun "it"
    r_turn2 = client.post("/api/chat", json={
        "session_id": new_session_id,
        "message": "What depends on it?"
    })
    assert r_turn2.status_code == 200, f"Turn 2 failed: {r_turn2.text}"
    data_turn2 = r_turn2.json()
    print(f"\nTurn 2 ('What depends on it?') completed!")
    print(f"Retrieved in Turn 2: {data_turn2['retrieved_items']}")
    print(f"Agent Steps:\n  " + "\n  ".join(data_turn2["agent_steps"]))
    print(f"Response preview:\n{data_turn2['content'][:250]}...")

    # Assert payment node was correctly retrieved in Turn 2!
    retrieved_str = " ".join(data_turn2["retrieved_items"]).lower()
    assert "payment" in retrieved_str, f"Expected payment node in Turn 2 retrieval, got: {data_turn2['retrieved_items']}"
    print("\n  -> PASS: Follow-up successfully retrieved payment_gateway_processor!")

    print("\n=======================================================")
    print(">>> ALL HANDOFF VERIFICATION CHECKS PASSED 100%! <<<")
    print("=======================================================")

if __name__ == "__main__":
    verify_all()

