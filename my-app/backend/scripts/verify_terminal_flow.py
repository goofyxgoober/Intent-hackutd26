#!/usr/bin/env python3
"""Verification script for Two-Mode Terminal flow (§10.6).

Covers:
1. Query with citations
2. Generation without selection (blocked tenet_not_selected)
3. Generation with selection
4. /ask override (forced query)
5. Axiom refusal (human-only)
6. Forged decision prevention (Rule 15 capability token check)
7. Read-only proof for queries (byte-identical store snapshot)
"""
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
_REPO_ROOT = _BACKEND_DIR.parent
for p in [str(_BACKEND_DIR), str(_REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient
from app.config import settings
from app.main import app
from app.intent.store import IntentStore
from app.actors import Actor
from app import db, sessions
import app.copilot.chat_router as chat_router
import app.chat_router as top_chat_router
from intentflow.llm import FakeNemotron
from intentflow.models import (
    CandidateReviewItem,
    CandidateReviewResult,
    EngineError,
    JevDecision,
    PromptVerdict,
    QueryAnswerPayload,
    RouterResult,
)


def run_verification():
    passed = 0
    failed = 0

    def record_step(name: str, success: bool, detail: str = ""):
        nonlocal passed, failed
        if success:
            passed += 1
            print(f"  [PASS] {name} {detail}")
        else:
            failed += 1
            print(f"  [FAIL] {name} {detail}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        settings.data_dir = str(data_dir)
        settings.database_path = str(tmp_path / "test.db")

        wid = 1
        db.init_db()
        with db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO users (id, github_id, login, created_at, last_login) VALUES (1, 1, 'test_user', 0.0, 0.0)")
            conn.execute("INSERT OR REPLACE INTO repos (id, user_id, full_name, default_branch, last_synced_sha, connected_at) VALUES (1, 1, 'acme/legacy', 'main', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 0.0)")

        store = IntentStore(wid)
        store.root.mkdir(parents=True, exist_ok=True)

        repo_dir = data_dir / "workspaces" / str(wid) / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        charge_py = repo_dir / "src" / "payments" / "charge.py"
        charge_py.parent.mkdir(parents=True, exist_ok=True)
        charge_py.write_text("def charge(amount):\n    if amount <= 0: raise ValueError()\n    return True\n")

        actor = Actor("user", "test_user")
        actor.user_id = 1
        eng_actor = Actor("engine", "annotator")

        root_t = store.create_tenet(actor, name="Root Architecture", functionality="Core system root", parent_id=None, cross_cutting=[], provenance={})
        pay_t = store.create_tenet(actor, name="Payment Subsystem", functionality="Processes charges and refunds", parent_id=root_t["id"], cross_cutting=[], provenance={})
        store.set_links(eng_actor, pay_t["id"], [{"path": "src/payments/charge.py"}])
        store.put_annotation(eng_actor, "src/payments/charge.py", {
            "purpose": "Processes credit card transactions",
            "responsibilities": ["charge cards", "validate positive amounts"],
            "invariants": ["amount > 0"],
        })

        client = TestClient(app)

        print("=== Two-Mode Terminal Verification Flow (§10.6) ===")

        # ------------------------------------------------------------------ Step 1: Query with citations
        fake_llm = FakeNemotron(default_responses=[
            RouterResult(verdict=PromptVerdict.QUERY, confidence=0.93, reason="query"),
            QueryAnswerPayload(
                answer="Payment processes charges [[file:src/payments/charge.py:1-3]] under [[tenet:" + pay_t["id"] + "]].",
                confidence=0.9,
            ),
        ])

        orig_route_chat = top_chat_router.route_chat

        async def patched_route_chat(*args, **kwargs):
            kwargs["llm"] = fake_llm
            return await orig_route_chat(*args, **kwargs)

        chat_router.route_chat = patched_route_chat
        top_chat_router.route_chat = patched_route_chat

        res1 = client.post("/api/chat", json={
            "message": "What does payment do?",
            "workspace_id": wid,
        })
        s1_ok = (
            res1.status_code == 200
            and res1.json().get("route", {}).get("verdict") == "query"
            and len(res1.json().get("query", {}).get("citations", [])) >= 1
            and "usage" in res1.json().get("query", {})
        )
        record_step("1. Query with citations", s1_ok, f"(citations={len(res1.json().get('query', {}).get('citations', []))})")

        # ------------------------------------------------------------------ Step 2: Generation without selection (blocked)
        fake_llm.queue_response("fast", RouterResult(
            verdict=PromptVerdict.HYPOTHESIS_GENERATION,
            confidence=0.92,
            reason="wants generation",
            requested_count=3,
        ))
        res2 = client.post("/api/chat", json={
            "message": "draft invariants for payments",
            "workspace_id": wid,
            "selected_tenet_id": None,
        })
        d2 = res2.json()
        s2_ok = (
            res2.status_code == 200
            and d2.get("route", {}).get("verdict") == "hypothesis_generation"
            and d2.get("route", {}).get("approved") is False
            and d2.get("route", {}).get("gate_reason") == "tenet_not_selected"
            and "Click a tenet node" in d2.get("content", "")
        )
        record_step("2. Generation without selection (blocked)", s2_ok, f"(gate_reason={d2.get('route', {}).get('gate_reason')})")

        # ------------------------------------------------------------------ Step 3: Generation with selection
        gen_tier = getattr(settings, "nemotron_tier_generator", "deep")
        fake_llm.queue_response("fast", RouterResult(
            verdict=PromptVerdict.HYPOTHESIS_GENERATION,
            confidence=0.95,
            reason="generate for selected tenet",
            requested_count=2,
        ))
        fake_llm.queue_response(gen_tier, {
            "candidates": [
                {"statement": "Amount must always be strictly positive", "test_explanation": "Test charge(-1)"},
                {"statement": "Successful charge returns True", "test_explanation": "Test charge(10)"},
            ]
        })
        fake_llm.queue_response("fast", CandidateReviewResult(results=[
            CandidateReviewItem(index=0, testable=True),
            CandidateReviewItem(index=1, testable=True),
        ]))
        res3 = client.post("/api/chat", json={
            "message": "draft 2 invariants for this",
            "workspace_id": wid,
            "selected_tenet_id": pay_t["id"],
            "allow_generation": True,
        })
        d3 = res3.json()
        s3_ok = (
            res3.status_code == 200
            and d3.get("route", {}).get("approved") is True
            and d3.get("generation", {}).get("status") == "completed"
            and len(d3.get("generation", {}).get("claims_created", [])) == 2
        )
        record_step("3. Generation with selection", s3_ok, f"(claims={len(d3.get('generation', {}).get('claims_created', []))})")

        # ------------------------------------------------------------------ Step 4: /ask override
        fake_llm.queue_response("fast", QueryAnswerPayload(
            answer="Answer via forced /ask [[file:src/payments/charge.py]].",
            confidence=0.9,
        ))
        res4 = client.post("/api/chat", json={
            "message": "/ask draft invariants for payments",
            "workspace_id": wid,
            "selected_tenet_id": pay_t["id"],
        })
        d4 = res4.json()
        s4_ok = (
            res4.status_code == 200
            and d4.get("route", {}).get("verdict") == "query"
            and d4.get("route", {}).get("source") == "explicit_user"
            and d4.get("query") is not None
        )
        record_step("4. /ask override", s4_ok, f"(verdict={d4.get('route', {}).get('verdict')})")

        # ------------------------------------------------------------------ Step 5: Axiom refusal
        res5 = client.post("/api/chat", json={
            "message": "Make this an axiom right now",
            "workspace_id": wid,
            "selected_tenet_id": pay_t["id"],
        })
        d5 = res5.json()
        s5_ok = (
            res5.status_code == 200
            and d5.get("route", {}).get("verdict") == "axiom_modification_request"
            and "Axioms are human-only" in d5.get("content", "")
        )
        record_step("5. Axiom refusal", s5_ok, f"(verdict={d5.get('route', {}).get('verdict')})")

        # ------------------------------------------------------------------ Step 6: Forged decision prevention (Rule 15)
        from intentflow.agents.hypothesis_generator import HypothesisGenerator
        forged_decision = JevDecision(
            decision_id="jd_forged",
            verdict=PromptVerdict.HYPOTHESIS_GENERATION,
            confidence=0.95,
            source="jev_llm",
            approved=False,  # NOT approved!
            gate_reason="tenet_not_selected",
            target_tenet_id=pay_t["id"],
        )
        generator = HypothesisGenerator(workspace=None, store=store, repo_dir=repo_dir, llm=fake_llm)
        import asyncio
        s6_ok = False
        try:
            asyncio.run(generator.generate(forged_decision))
        except (EngineError, Exception) as ee:
            s6_ok = "Decision does not authorize generation" in str(ee) or getattr(ee, "code", "") == "FORBIDDEN"

        record_step("6. Forged decision prevention (Rule 15)", s6_ok, "(capability token assertion passed)")

        # ------------------------------------------------------------------ Step 7: Read-only proof for queries
        snapshot_before = {}
        for p in store.root.rglob("*"):
            if p.is_file() and ".queries" not in p.parts:
                snapshot_before[str(p.relative_to(store.root))] = p.read_bytes()

        # Run multiple queries
        for q_idx in range(5):
            fake_llm.queue_response("fast", RouterResult(verdict=PromptVerdict.QUERY, confidence=0.9, reason="query"))
            fake_llm.queue_response("fast", QueryAnswerPayload(answer=f"Answer {q_idx}", confidence=0.85))
            client.post("/api/chat", json={"message": f"Query {q_idx}", "workspace_id": wid})

        snapshot_after = {}
        for p in store.root.rglob("*"):
            if p.is_file() and ".queries" not in p.parts:
                snapshot_after[str(p.relative_to(store.root))] = p.read_bytes()

        s7_ok = (snapshot_before == snapshot_after)
        record_step("7. Read-only proof for queries", s7_ok, f"(snapshot files={len(snapshot_after)})")

    print(f"\nSummary: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)
    else:
        print("ALL FLOW VERIFICATION STEPS PASSED SUCCESSFULLY!")
        sys.exit(0)


if __name__ == "__main__":
    run_verification()
