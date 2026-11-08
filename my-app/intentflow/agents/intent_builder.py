"""Intent Builder (grilling agent): top-down grilling state machine and tree construction."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..annotations import AnnotationIndex
from ..engine import IntentEngine
from ..llm import Nemotron
from ..models import (
    Actor,
    Claim,
    CodeLink,
    EngineError,
    Status,
    Tenet,
    new_id,
)
from ..store import Store


class GQuestion(BaseModel):
    id: str
    text: str
    why: str
    options: List[str] = Field(default_factory=list)
    answer: Optional[str] = None
    dont_know: bool = False


class ChildProposal(BaseModel):
    name: str
    summary: str
    is_leaf: bool
    code_paths: List[str] = Field(default_factory=list)


class HypProposal(BaseModel):
    statement: str = Field(description="ONE testable assertion")


class RefProposal(BaseModel):
    tenet_id: str
    reason: str


class DraftOut(BaseModel):
    functionality: str = Field(description="One precise paragraph: what this Tenet does, from code.")
    questions: List[GQuestion] = Field(default_factory=list, max_length=3)


class FinalOut(BaseModel):
    functionality: str
    children: List[ChildProposal] = Field(default_factory=list)
    hypotheses: List[HypProposal] = Field(default_factory=list)
    references: List[RefProposal] = Field(default_factory=list)
    open_unknowns: List[str] = Field(default_factory=list)


class GrillState(BaseModel):
    id: str
    tenet_id: str
    queue: List[str] = Field(default_factory=list)
    questions: List[GQuestion] = Field(default_factory=list)
    draft: Dict[str, Any] = Field(default_factory=dict)
    answered_history: List[Dict[str, Any]] = Field(default_factory=list)
    created: List[Dict[str, Any]] = Field(default_factory=list)
    asked_total: int = 0
    done: bool = False


class IntentBuilder:
    def __init__(self, engine: IntentEngine, store: Store, annotations: AnnotationIndex, llm: Optional[Nemotron] = None):
        self.engine = engine
        self.store = store
        self.annotations = annotations
        self.llm = llm or Nemotron()

    def _state_path(self, session_id: str) -> Path:
        return self.store.root / ".sessions" / f"{session_id}.json"

    def save_state(self, state: GrillState) -> None:
        p = self._state_path(state.id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state.model_dump(), indent=2), encoding="utf-8")

    def load_state(self, session_id: str) -> Optional[GrillState]:
        p = self._state_path(session_id)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return GrillState.model_validate(data)

    async def start_grilling(self, session_id: str, tenet_id: Optional[str] = None, purpose_hint: Optional[str] = None) -> GrillState:
        """Start or resume grilling at root or given Tenet."""
        state = self.load_state(session_id)
        if state and not state.done:
            return state

        # If no tenet_id provided, ensure root tenet exists
        tenets = self.store.all_tenets()
        root = next((t for t in tenets if t.parent_id is None), None)
        if root is None:
            root_id = new_id("t")
            root = Tenet(
                id=root_id,
                name="System",
                level=0,
                functionality=purpose_hint or "Overall system purpose and primary capabilities.",
                provenance={"via": "grilling", "session_id": session_id},
            )
            self.store.put_tenet(root, Actor.BUILDER)

        target_id = tenet_id or root.id
        state = GrillState(
            id=session_id,
            tenet_id=target_id,
            queue=[target_id],
            questions=[],
            draft={},
            created=[],
        )
        self.save_state(state)
        return await self.advance(state)

    async def advance(self, state: GrillState) -> GrillState:
        """Advance BFS queue to next tenet needing questions or auto-finalize."""
        auto_nodes = 0
        while state.queue and auto_nodes < 4:
            curr_id = state.queue.pop(0)
            state.tenet_id = curr_id
            t = self.store.find_tenet(curr_id)
            if not t:
                continue

            # Context assembly for draft
            file_summaries = self.annotations.file_summaries()
            map_str = "\n".join(f"- {p}: {s}" for p, s in list(file_summaries.items())[:15])
            existing_axioms = [
                c.statement for c in self.store.all_claims()
                if c.tenet_id == curr_id and c.status == Status.AXIOM
            ]
            axiom_str = ("\nExisting locked Axioms (facts):\n" + "\n".join(f"- {a}" for a in existing_axioms)) if existing_axioms else ""

            sys_prompt = (
                "You are the Intent Builder for IntentFlow. Infer what a legacy codebase is for and confirm it.\n"
                "Rules:\n"
                "- Base every statement on provided code annotations. Never invent behavior.\n"
                "- Write functionality paragraph concisely.\n"
                "- Ask at most 3 confirm-or-correct questions. If code is clear, ask 0 questions."
            )
            user_prompt = (
                f"Tenet: {t.name} (level {t.level})\n"
                f"Current functionality: {t.functionality}\n"
                f"{axiom_str}\n\n"
                f"Codebase map:\n{map_str}\n\n"
                "Draft functionality and targeted questions (max 3) to confirm or correct."
            )

            draft: DraftOut = await self.llm.structured(
                "deep",
                sys_prompt,
                user_prompt,
                DraftOut,
                agent="intent_builder",
                thinking=True,
                medium_effort=True,
            )

            state.draft = draft.model_dump()
            if draft.questions:
                for q in draft.questions:
                    if not q.id:
                        q.id = new_id("q")
                state.questions = draft.questions
                state.asked_total += len(draft.questions)
                self.save_state(state)
                return state
            else:
                # No questions needed, finalize immediately
                await self._finalize_tenet(state, t, answers=[])
                auto_nodes += 1

        if not state.queue:
            state.done = True

        self.save_state(state)
        return state

    async def submit_answer(self, session_id: str, question_id: str, user_text: str, dont_know: bool = False) -> GrillState:
        """Rule 3: Store and relay user answer verbatim."""
        state = self.load_state(session_id)
        if not state:
            raise EngineError("NOT_FOUND", f"Session {session_id} not found")

        q_found = False
        for q in state.questions:
            if q.id == question_id:
                # Store verbatim text
                q.answer = user_text
                q.dont_know = dont_know
                state.answered_history.append({
                    "tenet_id": state.tenet_id,
                    "question_id": question_id,
                    "question": q.text,
                    "answer": user_text,  # Byte-identical to what user typed
                    "dont_know": dont_know,
                })
                q_found = True
                break

        if not q_found:
            raise EngineError("NOT_FOUND", f"Question {question_id} not found in open questions")

        # Check if all open questions for current tenet are answered
        remaining = [q for q in state.questions if q.answer is None and not q.dont_know]
        if remaining:
            self.save_state(state)
            return state

        # All questions answered -> Finalize
        t = self.store.get_tenet(state.tenet_id)
        await self._finalize_tenet(state, t, answers=state.questions)
        state.questions = []
        return await self.advance(state)

    async def _finalize_tenet(self, state: GrillState, t: Tenet, answers: List[GQuestion]) -> None:
        """Call Nemotron to finalize Tenet, children, hypotheses, references, and apply writes."""
        ans_str = "\n".join(
            f"Q: {q.text}\nA: {'[UNKNOWN]' if q.dont_know else q.answer}" for q in answers
        )

        sys_prompt = (
            "Given the draft and user answers, finalize this Tenet.\n"
            "- Update functionality to reflect corrections. 'Don't know' answers go to open_unknowns.\n"
            "- Split into children ONLY if multiple sub-features or behaviors exist. Mark leaf=true when mapped to one code behavior.\n"
            "- Propose hypotheses: one testable assertion each."
        )
        user_prompt = (
            f"Tenet: {t.name}\n"
            f"Draft functionality: {state.draft.get('functionality', t.functionality)}\n"
            f"User answers:\n{ans_str or 'None'}\n\n"
            "Finalize functionality, children, hypotheses, references, and open unknowns."
        )

        final: FinalOut = await self.llm.structured(
            "deep",
            sys_prompt,
            user_prompt,
            FinalOut,
            agent="intent_builder",
            thinking=True,
            medium_effort=True,
        )

        # Apply updates to Tenet
        t.functionality = final.functionality or t.functionality
        t.open_unknowns = list(set(t.open_unknowns + final.open_unknowns))

        # Handle References
        for ref in final.references:
            if self.store.find_tenet(ref.tenet_id):
                try:
                    self.engine.check_reference_cycles(t.id, ref.tenet_id)
                    if ref.tenet_id not in t.references:
                        t.references.append(ref.tenet_id)
                except EngineError:
                    pass

        # Handle Children
        for ch in final.children:
            child_id = new_id("t")
            code_links = []
            if ch.is_leaf and ch.code_paths:
                for cp in ch.code_paths:
                    chunks = self.annotations.chunks(cp)
                    chash = chunks[0]["chunk_hash"] if chunks else None
                    code_links.append(CodeLink(file=cp, chunk_hash=chash, confidence="high"))

            child_tenet = Tenet(
                id=child_id,
                name=ch.name,
                parent_id=t.id,
                level=t.level + 1,
                functionality=ch.summary,
                code_links=code_links,
                provenance={"via": "grilling", "session_id": state.id},
            )
            self.store.put_tenet(child_tenet, Actor.BUILDER)
            t.children.append(child_id)
            state.created.append({"tenet_id": child_id, "name": ch.name, "leaf": ch.is_leaf})
            if not ch.is_leaf:
                state.queue.append(child_id)

        self.store.put_tenet(t, Actor.BUILDER)

        # Handle Hypotheses (atomic assertions)
        for hyp in final.hypotheses:
            if hyp.statement.strip():
                # Atomicity check: split multiple sentences / rules
                parts = [p.strip() for p in hyp.statement.split(";") if p.strip()]
                for p in parts:
                    conf = 0.15 if t.open_unknowns else 0.3
                    self.store.create_claim(
                        tenet_id=t.id,
                        statement=p,
                        actor=Actor.BUILDER,
                        status=Status.HYPOTHESIS,
                        confidence=conf,
                        provenance={"via": "intent_builder", "session_id": state.id},
                    )
