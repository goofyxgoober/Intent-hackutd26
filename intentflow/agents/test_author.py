"""Test Author agent: crafts test recipes for Hypotheses and generates probes for Axioms."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..annotations import AnnotationIndex
from ..llm import Nemotron
from ..models import Actor, Claim, EngineError, Status
from ..store import Store


class TestSections(BaseModel):
    test_explanation: str = Field(description="Plain language: what behavior is checked and why it matters")
    test_impl: str = Field(
        description=(
            "Complete recipe containing ENV/SETUP, FIXTURES, INVOKE, ASSERT, EXPECTED, TEARDOWN, "
            "PASS WHEN, FAIL WHEN, INCONCLUSIVE WHEN (and ORDER, LOCALIZE for integration tests)."
        )
    )
    fixtures: List[str] = Field(default_factory=list)
    exercises: List[str] = Field(default_factory=list, description="Child/referenced claims exercised in order")


class ProbeHypotheses(BaseModel):
    probes: List[str] = Field(description="3-5 boundary or edge-case hypotheses, plus the original claim statement")


class TestAuthor:
    __test__ = False
    def __init__(self, store: Store, annotations: AnnotationIndex, llm: Optional[Nemotron] = None):
        self.store = store
        self.annotations = annotations
        self.llm = llm or Nemotron()

    async def author(self, claim_id: str) -> Claim:
        """Authors test explanation and test_impl for a Hypothesis only."""
        c = self.store.get_claim(claim_id)
        if c.status == Status.AXIOM:
            raise EngineError(
                "AXIOM_LOCKED",
                f"Claim {claim_id} is a locked Axiom. Cannot re-author tests on an Axiom (Rule 1).",
                hint="Demote the Axiom first to edit it.",
            )

        t = self.store.get_tenet(c.tenet_id)

        # Build context
        if t.code_links:
            # Leaf claim: provide raw source of linked file
            file_path = t.code_links[0].file
            raw_code = self.annotations.raw(file_path)[:6000]
            context = f"Leaf Tenet: {t.name}\nCode context from {file_path}:\n```\n{raw_code}\n```"
        else:
            # Higher-level integration claim: assemble child/dependency recipes
            dep_recipes = []
            for did in c.dependencies:
                dep_claim = self.store.find_claim(did)
                if dep_claim:
                    dep_recipes.append(
                        f"Child Claim {did}: {dep_claim.statement}\nRecipe:\n{dep_claim.test_impl[:400]}"
                    )
            context = "Higher-level Integration Tenet: " + t.name + "\n" + "\n---\n".join(dep_recipes)

        sys_prompt = (
            "You are the Test Author. Write test recipes that another agent will execute with NO guessing.\n"
            "Requirements:\n"
            "- Tests run against the ORIGINAL code, read-only. Never propose modifying legacy code.\n"
            "- Output MUST contain exact recipe labeled sections: ENV/SETUP, FIXTURES, INVOKE, ASSERT, EXPECTED, "
            "TEARDOWN, PASS WHEN, FAIL WHEN, INCONCLUSIVE WHEN.\n"
            "- For higher-level claims, include ORDER and LOCALIZE."
        )
        user_prompt = (
            f"Tenet: {t.name}\n"
            f"Functionality: {t.functionality}\n"
            f"Claim Statement: {c.statement}\n\n"
            f"Context:\n{context}\n\n"
            "Generate test_explanation and test_impl."
        )

        sections: TestSections = await self.llm.structured(
            "deep",
            sys_prompt,
            user_prompt,
            TestSections,
            agent="test_author",
            thinking=True,
            medium_effort=True,
        )

        c.test_explanation = sections.test_explanation
        c.test_implementation = sections.test_impl
        return self.store.put_claim(c, Actor.BUILDER)

    async def probe_axiom(self, claim_id: str) -> List[Claim]:
        """Axiom Under Question (spec 11.6): generates probing hypotheses without modifying the Axiom."""
        axiom = self.store.get_claim(claim_id)
        if axiom.status != Status.AXIOM:
            raise EngineError("VALIDATION", f"Claim {claim_id} is not an Axiom")

        sys_prompt = (
            "You are the Test Author probing an Axiom under question. Generate 3-5 edge-case or boundary "
            "assertions plus repeat the original assertion verbatim."
        )
        user_prompt = (
            f"Axiom to probe: {axiom.statement}\n"
            f"Existing recipe: {axiom.test_impl}\n\n"
            "Generate probing hypotheses."
        )

        result: ProbeHypotheses = await self.llm.structured(
            "deep",
            sys_prompt,
            user_prompt,
            ProbeHypotheses,
            agent="test_author",
            thinking=True,
            medium_effort=True,
        )

        created = []
        for probe_stmt in result.probes:
            # Create as Hypothesis claims
            hyp = self.store.create_claim(
                tenet_id=axiom.tenet_id,
                statement=probe_stmt,
                actor=Actor.BUILDER,
                status=Status.HYPOTHESIS,
                test_explanation=f"Probing test for Axiom {axiom.id}: {probe_stmt}",
                test_impl=axiom.test_impl,  # baseline recipe
                dependencies=axiom.dependencies,
                confidence=0.2,
                provenance={"via": "probe_axiom", "probed_axiom_id": axiom.id},
            )
            created.append(hyp)

        return created
