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

def run_all_tests():
    print("=== RUNNING FULL BACKEND VERIFICATION SUITE ===")

    # 1. Root
    r0 = client.get("/")
    assert r0.status_code == 200, f"Root failed: {r0.text}"
    print("  [1/8] Root / -> 200 OK")

    # 2. Chat with Agent 2 (handling Swagger default dummy strings)
    r1 = client.post("/api/chat", json={"message": "string", "selected_node_ids": ["string"]})
    assert r1.status_code == 200, f"Chat failed: {r1.text}"
    print("  [2/8] POST /api/chat -> 200 OK (Dummy payload safely handled)")

    # 3. Live Token Reduction Dual Benchmark
    r2 = client.post("/api/chat/compare", json={"message": "How does session auth work in the monolith?"})
    assert r2.status_code == 200, f"Compare failed: {r2.text}"
    d2 = r2.json()
    print(f"  [3/8] POST /api/chat/compare -> 200 OK ({d2['percentage_saved']}% tokens saved, {d2['tokens_saved']} tokens)")

    # 4. Invariant Test Generation
    r3 = client.post("/api/generate-tests", json={"node_id": "payment_gateway_processor", "framework": "pytest"})
    assert r3.status_code == 200, f"Test Gen failed: {r3.text}"
    d3 = r3.json()
    print(f"  [4/8] POST /api/generate-tests -> 200 OK ({len(d3['invariants_covered'])} invariants covered)")

    # 5. Automated Invariant Verification Runner
    r4 = client.post("/api/run-tests", json={"node_id": "auth_flow_validate_session"})
    assert r4.status_code == 200, f"Run Tests failed: {r4.text}"
    d4 = r4.json()
    print(f"  [5/8] POST /api/run-tests -> 200 OK ({d4['pass_rate']} passed, {d4['passed']}/{d4['total_tests_run']} tests)")

    # 6. Intent Extraction (Agent 1 & Agent 2 Bridge)
    snippet = "def calculate_discount(price, code):\n    if price < 0: raise ValueError()\n    return price * 0.9"
    r5 = client.post("/api/extract-intent", json={"code_snippet": snippet, "file_path": "src/sales/promo.py", "language": "python"})
    assert r5.status_code == 200, f"Extract Intent failed: {r5.text}"
    d5 = r5.json()
    print(f"  [6/8] POST /api/extract-intent -> 200 OK (Node: {d5['node']['node_id']})")

    # 7. Intent Graph for Visualizer
    r6 = client.get("/api/graph")
    assert r6.status_code == 200, f"Graph failed: {r6.text}"
    d6 = r6.json()
    print(f"  [7/8] GET /api/graph -> 200 OK ({len(d6['nodes'])} nodes, {len(d6['edges'])} edges)")

    # 8. Blast Radius Impact Analysis
    r7 = client.get("/api/nodes/auth_flow_validate_session/blast-radius")
    assert r7.status_code == 200, f"Blast Radius failed: {r7.text}"
    d7 = r7.json()
    print(f"  [8/8] GET /api/nodes/{...}/blast-radius -> 200 OK ({d7['total_downstream_blast_radius']} downstream affected)")

    print("\n>>> ALL 8 BACKEND ENDPOINTS PASSED WITH 100% SUCCESS! <<<")

if __name__ == "__main__":
    run_all_tests()

