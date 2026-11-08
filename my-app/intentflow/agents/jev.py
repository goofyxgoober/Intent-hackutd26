"""Jev (change reviewer): type-safe classifier routing git changes to the intent tree."""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from ..engine import IntentEngine
from ..llm import Nemotron
from ..models import Actor, Claim, EngineError, Status, Tenet, new_id
from ..store import Store


class JevVerdict(BaseModel):
    verdict: Literal["no_disruption", "update_existing", "new_branch", "axiom_conflict"]
    confidence: Literal["low", "medium", "high"]
    reason: str = Field(max_length=300)
    tenet_ids: List[str] = Field(default_factory=list)
    claim_ids: List[str] = Field(default_factory=list)


class JevClassifier:
    def __init__(self, engine: IntentEngine, store: Store, llm: Optional[Nemotron] = None):
        self.engine = engine
        self.store = store
        self.llm = llm or Nemotron()

    def validate_ids(self, verdict: JevVerdict) -> bool:
        """Validate all referenced IDs exist in the store (spec 10.6)."""
        tenets = {t.id for t in self.store.all_tenets()}
        claims = {c.id for c in self.store.all_claims()}

        for tid in verdict.tenet_ids:
            if tid not in tenets:
                return False
        for cid in verdict.claim_ids:
            if cid not in claims:
                return False
        return True

    async def review_diff(
        self,
        diff_text: str,
        commit_range: str = "HEAD~1..HEAD",
        commit_msg: str = "",
    ) -> JevVerdict:
        """Review git diff against Axiom tree and route according to spec Section 12."""
        tenets = self.store.all_tenets()
        claims = self.store.all_claims()
        axioms = [c for c in claims if c.status == Status.AXIOM]

        tree_summary = "\n".join(
            f"Tenet {t.id} ({t.name}): {t.functionality[:80]}" for t in tenets[:20]
        )
        axiom_summary = "\n".join(
            f"Axiom {a.id} on Tenet {a.tenet_id}: {a.statement[:80]}" for a in axioms[:20]
        )

        sys_prompt = (
            "You are Jev, a type-safe classifier reviewing git commits against an intent tree.\n"
            "Verdicts:\n"
            "- no_disruption: No behavior change or intent modification\n"
            "- update_existing: Alters behavior covered by existing hypotheses\n"
            "- new_branch: New behavior not covered anywhere in tree\n"
            "- axiom_conflict: Contradicts an existing locked Axiom. NEVER alter axioms!\n"
            "Only return IDs that exist in the context."
        )
        user_prompt = (
            f"Commit: {commit_range} ({commit_msg})\n"
            f"Diff:\n```\n{diff_text[:6000]}\n```\n\n"
            f"Tree Context:\n{tree_summary}\n\n"
            f"Axioms Context:\n{axiom_summary}\n\n"
            "Classify this change."
        )

        # First attempt
        verdict: JevVerdict = await self.llm.structured(
            "deep",
            sys_prompt,
            user_prompt,
            JevVerdict,
            agent="jev",
            thinking=True,
            medium_effort=True,
        )

        if not self.validate_ids(verdict):
            # Retry once with correction
            user_prompt_retry = user_prompt + "\n\nNOTE: You named IDs that do not exist. Only use real IDs."
            verdict = await self.llm.structured(
                "deep",
                sys_prompt,
                user_prompt_retry,
                JevVerdict,
                agent="jev",
                thinking=True,
                medium_effort=True,
            )
            if not self.validate_ids(verdict):
                # Fall back to low confidence in review inbox
                verdict.confidence = "low"
                verdict.tenet_ids = [t for t in verdict.tenet_ids if self.store.find_tenet(t)]
                verdict.claim_ids = [c for c in verdict.claim_ids if self.store.find_claim(c)]

        # Apply downstream effects (Section 12)
        if verdict.verdict == "axiom_conflict":
            for cid in verdict.claim_ids:
                c = self.store.find_claim(cid)
                if c and c.status == Status.AXIOM:
                    self.store.engine_flag(
                        c.id,
                        flagged=True,
                        flag_reason=f"Jev detected conflict in commit {commit_range}: {verdict.reason}",
                    )
        elif verdict.verdict == "new_branch":
            parent = tenets[0].id if tenets else None
            new_t = Tenet(
                id=new_id("t"),
                name="New Branch Feature",
                parent_id=parent,
                functionality=f"Proposed new feature from commit {commit_range}: {verdict.reason}",
                proposed_unreviewed=True,
                provenance={"via": "jev", "commit_range": commit_range},
            )
            self.store.put_tenet(new_t, Actor.ENGINE)
            verdict.tenet_ids.append(new_t.id)

        self.store.changelog({
            "actor": "jev",
            "verdict": verdict.model_dump(),
            "commit_range": commit_range,
        })
        return verdict
