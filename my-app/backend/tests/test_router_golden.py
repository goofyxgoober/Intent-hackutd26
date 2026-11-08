"""Golden test suite for Jev Router (§10.4, Appendix A)."""
import json
from pathlib import Path
import pytest

from app.config import settings
from app.intent.store import IntentStore
from app.actors import Actor
from intentflow.agents import jev
from intentflow.llm import FakeNemotron, Nemotron
from intentflow.models import (
    PromptVerdict,
    QueryPlan,
    RouterResult,
)


GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "jev_router_cases.json"


@pytest.fixture
def golden_cases():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def test_store(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    store = IntentStore(10)
    store.root.mkdir(parents=True, exist_ok=True)
    actor = Actor("user", "golden_user")
    eng = Actor("engine", "annotator")

    root = store.create_tenet(actor, name="System Root", functionality="Root system", parent_id=None, cross_cutting=[], provenance={})
    pay = store.create_tenet(actor, name="Payment Module", functionality="Processes charges and refunds", parent_id=root["id"], cross_cutting=[], provenance={})
    auth = store.create_tenet(actor, name="Auth Subsystem", functionality="Session and JWT validation", parent_id=root["id"], cross_cutting=[], provenance={})

    store.set_links(eng, pay["id"], [{"path": "src/payments/charge.py"}])
    store.set_links(eng, auth["id"], [{"path": "src/auth/session.py"}])

    return store, root["id"], pay["id"], auth["id"]


def test_golden_gate_rules(golden_cases, test_store):
    """Verifies that deterministic gate correctly maps all 27 cases to their expected outcomes."""
    store, root_id, pay_id, auth_id = test_store

    approved_count = 0
    must_not_generate_approved = 0

    for case in golden_cases:
        prompt = case["prompt"]
        selected = pay_id if case["selected_tenet"] else None
        if case["id"] == 27:
            selected = root_id

        # Slash command overrides
        if prompt.startswith("/ask"):
            decision = jev.decide_prompt(
                store=store,
                route=RouterResult(verdict=PromptVerdict.QUERY, confidence=1.0, reason="explicit"),
                selected_tenet_id=selected,
                message=prompt,
            )
            assert decision.verdict == PromptVerdict.QUERY
            assert not decision.approved
            continue

        if prompt.startswith("/hypothesize"):
            verdict = PromptVerdict.HYPOTHESIS_GENERATION
            gate_reason = "tenet_not_selected" if not selected else None
            approved = selected is not None
            decision = jev.decide_prompt(
                store=store,
                route=RouterResult(verdict=verdict, confidence=1.0, reason="explicit"),
                selected_tenet_id=selected,
                message=prompt,
            )
            if not selected:
                assert not decision.approved
                assert decision.gate_reason == "tenet_not_selected"
            else:
                assert decision.approved
            continue

        # Simulating router verdict matching expected_verdict
        exp_verdict = PromptVerdict(case["expected_verdict"])
        route_res = RouterResult(
            verdict=exp_verdict,
            confidence=0.9,
            reason="golden case",
            requested_count=case.get("expected_count"),
        )

        decision = jev.decide_prompt(
            store=store,
            route=route_res,
            selected_tenet_id=selected,
            message=prompt,
        )

        # Gate outcome checks
        exp_outcome = case["expected_outcome"]
        if exp_outcome == "generate":
            assert decision.approved, f"Case {case['id']} expected generate but got {decision.gate_reason}"
            assert decision.target_tenet_id == selected
            if case.get("expected_count"):
                assert decision.requested_count == case["expected_count"]
            approved_count += 1
        elif exp_outcome == "blocked_tenet_not_selected":
            assert not decision.approved
            assert decision.gate_reason == "tenet_not_selected"
        elif exp_outcome in ("refusal", "no_generation"):
            assert not decision.approved
            if exp_outcome == "refusal":
                assert decision.verdict == PromptVerdict.AXIOM_MODIFICATION_REQUEST
        elif exp_outcome == "answer":
            assert not decision.approved
            assert decision.gate_reason == "not_generation"

    assert must_not_generate_approved == 0


@pytest.mark.live
@pytest.mark.asyncio
async def test_golden_router_live(golden_cases, test_store):
    """Live Nemotron evaluation over Golden cases (§10.4). Requires LIVE_EVAL=1 or Nemotron access."""
    store, root_id, pay_id, auth_id = test_store
    llm = Nemotron()

    # Exclude 8 few-shot examples from scoring per Appendix A
    few_shot_ids = {1, 2, 6, 8, 15, 17, 24, 25}
    eval_cases = [c for c in golden_cases if c["id"] not in few_shot_ids and not c["prompt"].startswith("/")]

    correct_verdicts = 0
    must_not_generate_approved = 0

    tenets_data = list(store.tenets().values())

    for case in eval_cases:
        selected = pay_id if case["selected_tenet"] else None
        if case["id"] == 27:
            selected = root_id

        route_res = await jev.route_prompt(
            workspace=None,
            message=case["prompt"],
            history=[],
            selected_tenet_id=selected,
            outline="<outline>src/payments/charge.py: Payment processing</outline>",
            tenets_data=tenets_data,
            llm=llm,
        )

        if route_res.verdict.value == case["expected_verdict"]:
            correct_verdicts += 1

        decision = jev.decide_prompt(
            store=store,
            route=route_res,
            selected_tenet_id=selected,
            message=case["prompt"],
        )

        if case["expected_outcome"] != "generate" and decision.approved:
            must_not_generate_approved += 1

    accuracy = correct_verdicts / len(eval_cases)
    assert accuracy >= 0.90, f"Router accuracy {accuracy:.2f} < 0.90"
    assert must_not_generate_approved == 0, f"{must_not_generate_approved} must_not_generate cases approved"
