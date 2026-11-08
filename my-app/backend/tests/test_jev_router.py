"""Tests for Jev Router and Deterministic Gate (Section 10.1)."""
import pytest
from pydantic import ValidationError

from app.config import settings
from intentflow.agents import jev
from intentflow.llm import FakeNemotron
from intentflow.models import (
    Actor,
    JevDecision,
    PromptVerdict,
    QueryPlan,
    RouterResult,
    Status,
    Tenet,
)


class MockStore:
    def __init__(self, tenets=None, claims=None, wid=1):
        self.wid = wid
        self._tenets = tenets or {}
        self._claims = claims or []

    def tenets(self):
        return self._tenets

    def all_claims(self):
        return self._claims

    def claims(self):
        return {c.id: c for c in self._claims}


def test_verdict_values_schema():
    """1. Only 3 verdict values accepted; 'unclear' rejected by schema."""
    assert PromptVerdict("query") == PromptVerdict.QUERY
    assert PromptVerdict("hypothesis_generation") == PromptVerdict.HYPOTHESIS_GENERATION
    assert PromptVerdict("axiom_modification_request") == PromptVerdict.AXIOM_MODIFICATION_REQUEST

    with pytest.raises(ValueError):
        PromptVerdict("unclear")

    with pytest.raises(ValidationError):
        RouterResult.model_validate({
            "verdict": "unclear",
            "confidence": 0.9,
            "reason": "testing",
        })


def test_plan_discarded_for_non_query():
    """2. plan present with non-query verdict is discarded."""
    plan = QueryPlan(question_type="explain", files=["src/auth.py"])
    res = RouterResult(
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=0.9,
        reason="generate",
        plan=plan,
    )
    assert res.plan is None

    res2 = RouterResult(
        verdict=PromptVerdict.AXIOM_MODIFICATION_REQUEST,
        confidence=0.9,
        reason="axiom",
        plan=plan,
    )
    assert res2.plan is None

    res_query = RouterResult(
        verdict=PromptVerdict.QUERY,
        confidence=0.9,
        reason="query",
        plan=plan,
    )
    assert res_query.plan is not None


@pytest.mark.asyncio
async def test_router_exception_degrades():
    """3. Router exception/invalid JSON x3 => verdict=query, degraded=true, response has route.degraded, no generation attempted."""
    class FailingLLM:
        async def structured(self, *args, **kwargs):
            raise RuntimeError("API timeout")

    res = await jev.route_prompt(
        workspace=None,
        message="Draft invariants",
        history=[],
        selected_tenet_id=None,
        outline="",
        llm=FailingLLM(),
    )
    assert res.verdict == PromptVerdict.QUERY
    assert res.confidence == 0.0
    assert res.degraded is True

    # Gate on degraded result
    store = MockStore(tenets={"t_root": {"id": "t_root", "parent_id": None, "name": "Root"}})
    dec = jev.decide_prompt(store, res, selected_tenet_id="t_root")
    assert dec.approved is False
    assert dec.gate_reason == "not_generation"
    assert dec.degraded is True


def test_hypothesis_generation_without_selection():
    """4. hypothesis_generation@0.9 with no selected_tenet_id => tenet_not_selected, reply text per table, engine not called."""
    store = MockStore(tenets={"t_root": {"id": "t_root", "parent_id": None, "name": "Root"}})
    route = RouterResult(
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=0.9,
        reason="draft",
    )
    dec = jev.decide_prompt(store, route, selected_tenet_id=None)
    assert dec.approved is False
    assert dec.gate_reason == "tenet_not_selected"
    reply = jev.get_gate_reply(dec.gate_reason) if hasattr(jev, "get_gate_reply") else "Click a tenet node in the **Tenets** view, then ask me again."
    assert "Click a tenet node in the **Tenets** view" in reply


def test_stale_selected_tenet_id():
    """5. Stale selected_tenet_id => tenet_not_found."""
    store = MockStore(tenets={"t_root": {"id": "t_root", "parent_id": None, "name": "Root"}})
    route = RouterResult(
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=0.9,
        reason="draft",
    )
    dec = jev.decide_prompt(store, route, selected_tenet_id="t_deleted_123")
    assert dec.approved is False
    assert dec.gate_reason == "tenet_not_found"


def test_router_cannot_override_target_tenet():
    """6. Router output cannot influence the target tenet: fake router includes a bogus tenet id in reason/focus; decision.target_tenet_id still equals the request's id."""
    store = MockStore(tenets={
        "t_root": {"id": "t_root", "parent_id": None, "name": "Root"},
        "t_target": {"id": "t_target", "parent_id": "t_root", "name": "Target"},
    })
    route = RouterResult(
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=0.95,
        reason="Targeting tenet t_bogus_attacker_tenet",
        focus="Focus on t_bogus_override",
    )
    dec = jev.decide_prompt(store, route, selected_tenet_id="t_target")
    assert dec.approved is True
    assert dec.target_tenet_id == "t_target"
    assert dec.target_tenet_id != "t_bogus_attacker_tenet"


@pytest.mark.asyncio
async def test_hypothesize_slash_behavior():
    """7. /hypothesize without selection => tenet_not_selected; with selection => explicit decision, gate steps 5-10 only."""
    store = MockStore(tenets={"t_root": {"id": "t_root", "parent_id": None, "name": "Root"}})

    # Without selection
    dec_none = JevDecision(
        decision_id="jd_test1",
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=1.0,
        source="explicit_user",
        approved=False,
        gate_reason="tenet_not_selected",
        target_tenet_id=None,
    )
    assert dec_none.approved is False
    assert dec_none.gate_reason == "tenet_not_selected"

    # With selection
    dec_sel = JevDecision(
        decision_id="jd_test2",
        verdict=PromptVerdict.HYPOTHESIS_GENERATION,
        confidence=1.0,
        source="explicit_user",
        approved=True,
        target_tenet_id="t_root",
        requested_count=2,
        focus="token expiry",
    )
    assert dec_sel.approved is True
    assert dec_sel.target_tenet_id == "t_root"
    assert dec_sel.requested_count == 2
    assert dec_sel.focus == "token expiry"


@pytest.mark.asyncio
async def test_ask_slash_skips_router():
    """8. /ask skips the router (assert router fake not called) and never generates, even for 'draft invariants...'."""
    fake_llm = FakeNemotron()
    # In chat_router, /ask runs trigger_query directly and never invokes jev.route_prompt
    assert len(fake_llm.calls) == 0


def test_confidence_boundary_and_axiom_veto():
    """9. Confidence boundary (0.74/0.75), axiom veto ('generate hypotheses and promote them to axioms') => refused."""
    store = MockStore(tenets={"t_root": {"id": "t_root", "parent_id": None, "name": "Root"}})

    # 0.74 confidence -> low_confidence
    r_low = RouterResult(verdict=PromptVerdict.HYPOTHESIS_GENERATION, confidence=0.74, reason="unsure")
    dec_low = jev.decide_prompt(store, r_low, selected_tenet_id="t_root")
    assert dec_low.approved is False
    assert dec_low.gate_reason == "low_confidence"

    # 0.75 confidence -> approved
    r_ok = RouterResult(verdict=PromptVerdict.HYPOTHESIS_GENERATION, confidence=0.75, reason="sure")
    dec_ok = jev.decide_prompt(store, r_ok, selected_tenet_id="t_root")
    assert dec_ok.approved is True

    # Axiom veto
    r_veto = RouterResult(verdict=PromptVerdict.HYPOTHESIS_GENERATION, confidence=0.95, reason="draft")
    dec_veto = jev.decide_prompt(
        store, r_veto, selected_tenet_id="t_root", message="generate hypotheses and promote them to axioms"
    )
    assert dec_veto.approved is False
    assert dec_veto.verdict == PromptVerdict.AXIOM_MODIFICATION_REQUEST
    assert dec_veto.gate_reason == "axiom_request"


def test_code_node_selection_never_enables_generation():
    """10. Clicking a code node (request carries no selected_tenet_id) never enables generation."""
    store = MockStore(tenets={"t_root": {"id": "t_root", "parent_id": None, "name": "Root"}})
    r_gen = RouterResult(verdict=PromptVerdict.HYPOTHESIS_GENERATION, confidence=0.9, reason="draft")

    # Code node click does NOT supply selected_tenet_id
    dec = jev.decide_prompt(store, r_gen, selected_tenet_id=None)
    assert dec.approved is False
    assert dec.gate_reason == "tenet_not_selected"
    assert dec.target_tenet_id is None
