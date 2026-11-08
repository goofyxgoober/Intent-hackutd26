"""Remake Agent: scrap-and-remake with failure memory and rejected interpretations list."""
import difflib
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..annotations import AnnotationIndex
from ..llm import Nemotron
from ..models import Actor, Claim, EngineError, Status
from ..store import Store


class RemakeOutput(BaseModel):
    replacement_hypotheses: List[str] = Field(
        description="Hypotheses that explicitly differ from all rejected interpretations"
    )
    rationale: str = Field(description="Why this interpretation differs and fixes the failure")


class RemakeAgent:
    def __init__(self, store: Store, annotations: AnnotationIndex, llm: Optional[Nemotron] = None):
        self.store = store
        self.annotations = annotations
        self.llm = llm or Nemotron()

    def scrap_hypothesis(self, claim_id: str, reason: str, rejected_interpretation: Optional[str] = None) -> Claim:
        """Rule 1 & 7: Only Hypotheses may be scrapped. Axioms must be demoted first."""
        c = self.store.get_claim(claim_id)
        if c.status == Status.AXIOM:
            raise EngineError(
                "AXIOM_LOCKED",
                f"Cannot scrap Axiom {claim_id}. Demote the Axiom to a Hypothesis first.",
            )

        rejected = rejected_interpretation or c.statement
        self.store.add_rejected_interpretation(c.tenet_id, rejected, reason=reason)
        c.status = Status.SCRAPPED
        return self.store.put_claim(c, Actor.BUILDER)

    async def remake(
        self,
        tenet_id: str,
        scrapped_claim_id: Optional[str] = None,
        localization_level: str = "leaf",
        retry_cap: int = 2,
    ) -> List[Claim]:
        """Remake hypotheses using failure memory (rejected-interpretations list) (spec 10.5 & 11.4)."""
        tenet = self.store.get_tenet(tenet_id)
        rejected_list = self.store.rejected_interpretations(tenet_id)
        rejected_texts = [r["text"] for r in rejected_list]

        rejected_str = "\n".join(f"- {t}" for t in rejected_texts)

        sys_prompt = (
            "You are the Remake Agent. Generate replacement hypotheses that explicitly DIFFER from the rejected "
            "interpretations list. Base your proposals on the code and annotations, localized to the failure."
        )
        user_prompt = (
            f"Tenet: {tenet.name}\n"
            f"Functionality: {tenet.functionality}\n"
            f"Localization Level: {localization_level}\n\n"
            f"Rejected Interpretations (DO NOT REPEAT THESE):\n{rejected_str or 'None'}\n\n"
            "Propose replacement hypotheses."
        )

        for attempt in range(retry_cap):
            out: RemakeOutput = await self.llm.structured(
                "deep",
                sys_prompt,
                user_prompt,
                RemakeOutput,
                agent="remake",
                thinking=True,
                medium_effort=True,
            )

            # Enforce that every proposed hypothesis differs from rejected interpretations
            valid = True
            for stmt in out.replacement_hypotheses:
                for rej in rejected_texts:
                    ratio = difflib.SequenceMatcher(None, stmt.lower(), rej.lower()).ratio()
                    if ratio >= 0.85:
                        valid = False
                        break
                if not valid:
                    break

            if valid or attempt == retry_cap - 1:
                created = []
                for stmt in out.replacement_hypotheses:
                    c = self.store.create_claim(
                        tenet_id=tenet.id,
                        statement=stmt,
                        actor=Actor.BUILDER,
                        status=Status.HYPOTHESIS,
                        confidence=0.3,
                        provenance={
                            "via": "remake",
                            "rationale": out.rationale,
                            "scrapped_claim_id": scrapped_claim_id,
                        },
                    )
                    created.append(c)
                return created

        return []
