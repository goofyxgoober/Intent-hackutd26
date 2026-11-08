"""IntentFlow rules engine: non-negotiable rules, gates, impact analysis, and status changes."""
import time
from typing import Any, Dict, List, Optional, Set

from .models import (
    Actor,
    Claim,
    EngineError,
    PendingConfirmation,
    PermissionDenied,
    Status,
    Tenet,
    Verdict,
    new_id,
)
from .store import Store


class UserAuthority:
    """Proof that a real user clicked something. Minted ONLY by the verified UI auth layer."""

    _MINT = object()

    def __init__(self, user_id: str, _mint: Any = None):
        if _mint is not UserAuthority._MINT:
            raise PermissionDenied("UserAuthority can only be minted by the UI auth layer")
        self.user_id = user_id

    @classmethod
    def from_verified_jwt(cls, user_id: str) -> "UserAuthority":
        return cls(user_id, cls._MINT)


class IntentEngine:
    def __init__(self, store: Store):
        self.store = store

    # ------------------------------------------------------------------ Tree & Footprint Helpers

    def _subtree(self, tenet_id: str) -> Set[str]:
        """Ownership descendants plus referenced tenets."""
        tenets = {t.id: t for t in self.store.all_tenets()}
        visited: Set[str] = set()

        def dfs(curr: str):
            if curr in visited or curr not in tenets:
                return
            visited.add(curr)
            t = tenets[curr]
            for child in t.children:
                dfs(child)
            for ref in t.references:
                dfs(ref)

        dfs(tenet_id)
        return visited

    def check_reference_cycles(self, from_id: str, to_id: str) -> None:
        """Rule 9: Reference cycles across ownership and references are rejected."""
        tenets = {t.id: t for t in self.store.all_tenets()}
        if to_id not in tenets:
            raise EngineError("NOT_FOUND", f"Target tenet {to_id} does not exist")
        if from_id == to_id:
            raise EngineError("CYCLE_DETECTED", f"Self-reference on {from_id} rejected")

        # Check if to_id can reach from_id via children or references
        visited: Set[str] = set()

        def can_reach(curr: str, target: str) -> bool:
            if curr == target:
                return True
            if curr in visited or curr not in tenets:
                return False
            visited.add(curr)
            t = tenets[curr]
            for neighbor in set(t.children) | set(t.references):
                if can_reach(neighbor, target):
                    return True
            return False

        if can_reach(to_id, from_id):
            raise EngineError("CYCLE_DETECTED", f"Reference from {from_id} to {to_id} would create a cycle")

    def add_reference(self, tenet_id: str, target_id: str, actor: Actor) -> Tenet:
        t = self.store.get_tenet(tenet_id)
        self.check_reference_cycles(tenet_id, target_id)
        if target_id not in t.references:
            t.references.append(target_id)
            self.store.put_tenet(t, actor)
        return t

    def reparent(self, tenet_id: str, new_parent_id: Optional[str], actor: Actor) -> Tenet:
        t = self.store.get_tenet(tenet_id)
        if new_parent_id:
            # Check ownership cycle
            descendants = self._subtree(tenet_id)
            if new_parent_id in descendants:
                raise EngineError("CYCLE_DETECTED", f"Cannot move {tenet_id} under its own descendant {new_parent_id}")
            parent = self.store.get_tenet(new_parent_id)
            if tenet_id not in parent.children:
                parent.children.append(tenet_id)
                self.store.put_tenet(parent, actor)

        # Remove from old parent
        if t.parent_id:
            old_parent = self.store.find_tenet(t.parent_id)
            if old_parent and tenet_id in old_parent.children:
                old_parent.children.remove(tenet_id)
                self.store.put_tenet(old_parent, actor)

        t.parent_id = new_parent_id
        t.level = (self.store.get_tenet(new_parent_id).level + 1) if new_parent_id else 0
        return self.store.put_tenet(t, actor)

    # ------------------------------------------------------------------ Gates

    def deps_ready(self, c: Claim) -> List[str]:
        """Rule 8: Bottom-up promotion. Returns blocker claim IDs (empty = ready)."""
        blockers = []
        for did in c.dependencies:
            d = self.store.find_claim(did)
            if d is None or d.status == Status.SCRAPPED:
                blockers.append(did)
                continue
            if d.status == Status.AXIOM:
                continue
            if self.store.latest_verdict(d) != Verdict.PASS:
                blockers.append(did)
        return blockers

    def promotion_gate(self, c: Claim, override: bool = False) -> None:
        """Enforces Rule 7 and Rule 8 for promotion."""
        if c.status != Status.HYPOTHESIS:
            raise EngineError("VALIDATION", f"Claim {c.id} is {c.status.value}, not a hypothesis")

        # Rule 6 & 7: Needs a passing result bound to current wording unless overridden
        v = self.store.latest_verdict(c)
        if v != Verdict.PASS and not override:
            raise EngineError("NOT_VERIFIED", f"Claim {c.id} latest verdict is {v.value}; passing test required")

        # Rule 8: Bottom-up rule always blocks if dependencies are not ready
        blockers = self.deps_ready(c)
        if blockers:
            raise EngineError(
                "DEPENDENCY_NOT_READY",
                f"Cannot promote {c.id}; dependencies are not ready",
                data={"blockers": blockers},
                hint="Verify and promote child/referenced claims first (bottom-up rule)",
            )

    # ------------------------------------------------------------------ Impact Analysis

    def impact(self, claim_id: str) -> Dict[str, Any]:
        """Rule 12: Demotion shows its cost first."""
        c = self.store.get_claim(claim_id)
        t = self.store.get_tenet(c.tenet_id)
        claims = self.store.all_claims()
        tenets = {x.id: x for x in self.store.all_tenets()}

        # Dependents: claims that list claim_id in dependencies
        dependents = [x.id for x in claims if claim_id in x.dependencies]

        # Tenets that reference t.id
        ref_by = [x.id for x in tenets.values() if t.id in x.references]

        # Ancestor tenets
        ancestors = []
        curr = t.parent_id
        while curr and curr in tenets:
            ancestors.append(curr)
            curr = tenets[curr].parent_id

        # Linked files across subtree
        subtree_ids = self._subtree(t.id)
        linked_files = sorted(list({
            l.file for tid in subtree_ids if tid in tenets for l in tenets[tid].code_links
        }))

        # Results that go stale
        stale_results = [cid for cid in [claim_id, *dependents] if self.store.has_results(cid)]

        return {
            "claim_id": claim_id,
            "tenet_id": t.id,
            "dependent_claims": dependents,
            "referencing_tenets": ref_by,
            "ancestor_tenets": ancestors,
            "linked_files": linked_files,
            "results_that_go_stale": stale_results,
            "provisional_spec_sections": [t.id, *ancestors],
        }

    # ------------------------------------------------------------------ Two-Phase Status Change

    def request_status_change(self, claim_id: str, target: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Called by chatbot or UI to initiate a status change without modifying state."""
        c = self.store.get_claim(claim_id)
        target_status = Status(target.lower())

        if target_status == Status.AXIOM:
            if c.status != Status.HYPOTHESIS:
                raise EngineError("VALIDATION", f"Claim {claim_id} is not a hypothesis")
            # Verify gate with override=True to check if structure and dependencies allow it
            self.promotion_gate(c, override=True)
            verified = self.store.latest_verdict(c) == Verdict.PASS
        elif target_status == Status.HYPOTHESIS:
            if c.status != Status.AXIOM:
                raise EngineError("VALIDATION", f"Claim {claim_id} is not an axiom")
            verified = None
        else:
            raise EngineError("VALIDATION", f"Target status {target} not supported for request_status_change")

        pid = new_id("p")
        imp = self.impact(claim_id)
        self.store.put_pending({
            "id": pid,
            "claim_id": claim_id,
            "target": target_status.value,
            "claim_hash": c.content_hash(),
            "verified": verified,
            "impact": imp,
            "expires": time.time() + 900,
            "requires_reason": target_status == Status.HYPOTHESIS,
        })

        return {
            "confirmation_id": pid,
            "claim_id": claim_id,
            "target": target_status.value,
            "impact": imp,
            "verified": verified,
        }

    def confirm(self, pid: str, choice: str, reason: Optional[str], auth: UserAuthority) -> Dict[str, Any]:
        """User button click in UI that executes the promotion or demotion (Rule 2)."""
        p = self.store.get_pending(pid)
        if not p or p.expires < time.time():
            raise EngineError("STALE_CONFIRMATION", "Confirmation expired or invalid")

        c = self.store.get_claim(p.claim_id)
        if c.content_hash() != p.claim_hash:
            raise EngineError("STALE_CONFIRMATION", "Claim was modified since confirmation was requested")

        target_status = p.target
        if target_status == Status.AXIOM:
            override = (choice == "accept_unverified")
            self.promotion_gate(c, override=override)
            # Snapshot
            self.store.snapshot("promoted", {
                "claim_id": c.id,
                "user_id": auth.user_id,
                "override": override,
                "claim": c.model_dump(),
            })
            c.status = Status.AXIOM
            if override:
                c.unverified = True
                c.accepted_without_verification = True
            else:
                c.unverified = False
                c.accepted_without_verification = False
            c.flagged = False
            c.flag_reason = None
            c.base_flag = None
            self.store.put_claim(c, Actor.USER)
            self.store.changelog({
                "actor": "user",
                "user_id": auth.user_id,
                "action": "promote",
                "claim_id": c.id,
                "override": override,
            })
        elif target_status == Status.HYPOTHESIS:
            if not reason:
                raise EngineError("VALIDATION", "Reason is required for demotion")
            # Snapshot prior version to history
            self.store.snapshot("demoted", {
                "claim_id": c.id,
                "user_id": auth.user_id,
                "reason": reason,
                "claim": c.model_dump(),
            })
            c.status = Status.HYPOTHESIS
            self.store.put_claim(c, Actor.USER)

            # Stale its own results
            self.store.mark_results_stale(c.id)

            # Rule 8 & 12: Mark dependents as resting on an unlocked base and stale their results
            # Dependents STAY Axioms (spec section 8)
            claims = self.store.all_claims()
            dependents = [x for x in claims if c.id in x.dependencies]
            for dep in dependents:
                self.store.engine_flag(dep.id, flagged=True, base_flag="unlocked_base")
                self.store.mark_results_stale(dep.id)

            self.store.changelog({
                "actor": "user",
                "user_id": auth.user_id,
                "action": "demote",
                "claim_id": c.id,
                "reason": reason,
            })

        self.store.del_pending(pid)
        return {"status": "ok", "claim_id": c.id, "new_status": c.status.value}

    # ------------------------------------------------------------------ Direct User Edit of Axiom

    def edit_axiom_by_hand(
        self,
        claim_id: str,
        fields: Dict[str, Any],
        reason: str,
        ack_warning: bool,
        auth: UserAuthority,
    ) -> Claim:
        """Section 11.8: Direct user edit of an Axiom by hand after warning."""
        c = self.store.get_claim(claim_id)
        if c.status != Status.AXIOM:
            raise EngineError("VALIDATION", f"Claim {claim_id} is not an Axiom")

        if not ack_warning:
            imp = self.impact(claim_id)
            raise EngineError(
                "WARNING_REQUIRED",
                "Axiom edit requires acknowledging the impact warning",
                data=imp,
            )

        if not reason:
            raise EngineError("VALIDATION", "Reason is required when hand-editing an Axiom")

        # Snapshot prior version
        self.store.snapshot("hand_edit", {
            "claim_id": c.id,
            "user_id": auth.user_id,
            "reason": reason,
            "prior_claim": c.model_dump(),
        })

        # Apply user fields
        if "statement" in fields and fields["statement"]:
            c.statement = fields["statement"]
        if "test_explanation" in fields:
            c.test_explanation = fields["test_explanation"]
        if "test_implementation" in fields:
            c.test_implementation = fields["test_implementation"]
        elif "test_impl" in fields:
            c.test_implementation = fields["test_impl"]
        if "dependencies" in fields:
            c.dependencies = fields["dependencies"]

        c.unverified = True  # Flagged unverified until test passes against new wording
        self.store.put_claim(c, Actor.USER)

        # Hash change automatically marks existing results stale.
        # Mark dependents as resting on a changed base
        claims = self.store.all_claims()
        for dep in claims:
            if c.id in dep.dependencies:
                self.store.engine_flag(dep.id, flagged=True, base_flag="changed_base")
                self.store.mark_results_stale(dep.id)

        self.store.changelog({
            "actor": "user",
            "user_id": auth.user_id,
            "action": "edit_axiom_by_hand",
            "claim_id": c.id,
            "reason": reason,
        })
        return c

    # ------------------------------------------------------------------ Rollup & Badges

    def rollup(self, tenet_id: str) -> Dict[str, Any]:
        """Compute verdict rollup and badge metrics for a Tenet (spec 5, 14.1)."""
        tenet = self.store.get_tenet(tenet_id)
        claims = [c for c in self.store.all_claims() if c.tenet_id == tenet_id]

        axiom_count = sum(1 for c in claims if c.status == Status.AXIOM)
        hypothesis_count = sum(1 for c in claims if c.status == Status.HYPOTHESIS)

        has_flagged_axioms = any(c.status == Status.AXIOM and c.flagged for c in claims)
        has_unlocked_base = any(c.base_flag == "unlocked_base" for c in claims)
        low_confidence = any(c.confidence < 0.25 for c in claims) or tenet.proposed_unreviewed

        # Rollup verdict
        verdicts = [self.store.latest_verdict(c) for c in claims]
        if Verdict.FAIL in verdicts:
            rollup_verdict = Verdict.FAIL
        elif Verdict.STALE in verdicts:
            rollup_verdict = Verdict.STALE
        elif Verdict.INCONCLUSIVE in verdicts:
            rollup_verdict = Verdict.INCONCLUSIVE
        elif verdicts and all(v == Verdict.PASS for v in verdicts):
            rollup_verdict = Verdict.PASS
        elif Verdict.PASS in verdicts:
            rollup_verdict = Verdict.PASS
        else:
            rollup_verdict = Verdict.NONE

        return {
            "tenet_id": tenet_id,
            "axiom_count": axiom_count,
            "hypothesis_count": hypothesis_count,
            "verdict": rollup_verdict.value,
            "has_flagged_axioms": has_flagged_axioms,
            "has_unlocked_base": has_unlocked_base,
            "low_confidence": low_confidence,
            "proposed_unreviewed": tenet.proposed_unreviewed,
        }

    # ------------------------------------------------------------------ Axiom Failure Rule 4

    def handle_test_verdict(self, claim_id: str, run_verdict: Verdict, detail: str = "") -> None:
        """Rule 4: A failing test on an Axiom raises a flag, NEVER a change in status."""
        c = self.store.get_claim(claim_id)
        if c.status == Status.AXIOM:
            if run_verdict == Verdict.FAIL:
                self.store.engine_flag(
                    c.id,
                    flagged=True,
                    flag_reason=f"Test failure against legacy code: {detail[:200]}",
                )
            elif run_verdict == Verdict.PASS and not c.base_flag:
                # If was unverified after hand edit and test passed, clear unverified flag
                if c.unverified:
                    c.unverified = False
                    self.store.put_claim(c, Actor.USER)
                    self.store.engine_flag(c.id, flagged=False, flag_reason=None)
