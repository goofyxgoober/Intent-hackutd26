"""Spec Compiler: compiles the Tenet hierarchy and Axioms into a requirements spec (spec 15)."""
import time
from typing import Any, Dict, List, Tuple
from pydantic import BaseModel, Field

from .models import Actor, Status, Verdict
from .store import Store


class SpecSection(BaseModel):
    title: str
    tenet_id: str
    functionality: str
    requirements: List[Dict[str, Any]] = Field(default_factory=list)
    subsections: List["SpecSection"] = Field(default_factory=list)


class CompiledSpec(BaseModel):
    markdown: str
    readiness: Dict[str, Any]
    sections: List[Dict[str, Any]]
    known_unknowns: List[str]
    deviations: List[Dict[str, Any]]


class SpecCompiler:
    def __init__(self, store: Store):
        self.store = store

    def compile(self, include_hypotheses: bool = True) -> CompiledSpec:
        tenets = {t.id: t for t in self.store.all_tenets()}
        claims = self.store.all_claims()

        # Find roots
        roots = [t for t in tenets.values() if t.parent_id is None]
        if not roots and tenets:
            roots = [min(tenets.values(), key=lambda x: x.level)]

        # Collect claims by tenet
        claims_by_tenet: Dict[str, List[Any]] = {}
        for c in claims:
            claims_by_tenet.setdefault(c.tenet_id, []).append(c)

        # Readiness metrics
        total_claims = len(claims)
        axiom_count = sum(1 for c in claims if c.status == Status.AXIOM)
        verified_axioms = sum(1 for c in claims if c.status == Status.AXIOM and not c.unverified)
        axiom_share = (axiom_count / total_claims) if total_claims > 0 else 0.0
        open_conflicts = sum(1 for c in claims if c.flagged)

        readiness = {
            "total_claims": total_claims,
            "axiom_count": axiom_count,
            "verified_axioms": verified_axioms,
            "axiom_share": round(axiom_share, 3),
            "open_conflicts": open_conflicts,
            "ready": (axiom_share >= 0.7 and open_conflicts == 0),
        }

        # Known unknowns
        known_unknowns = []
        for t in tenets.values():
            for uk in t.open_unknowns:
                known_unknowns.append(f"[{t.name}] {uk}")

        # Deviations / decisions
        deviations = []
        for c in claims:
            if c.accepted_without_verification:
                deviations.append({
                    "claim_id": c.id,
                    "type": "unverified_axiom",
                    "note": f"Axiom accepted without test verification: {c.statement}",
                })

        # Render Markdown
        lines: List[str] = [
            "# System Specification (IntentFlow Compiled Spec)",
            "",
            f"*Compiled at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}*",
            f"*Readiness: {readiness['axiom_share']*100:.1f}% Axiom coverage ({'SPEC READY' if readiness['ready'] else 'PROVISIONAL'})*",
            "",
            "## 1. Overview and Hierarchy",
            "",
        ]

        def render_tenet(t, depth=2) -> List[Dict[str, Any]]:
            header_prefix = "#" * depth
            sec_dict: Dict[str, Any] = {
                "title": t.name,
                "tenet_id": t.id,
                "functionality": t.functionality,
                "code_links": [],
                "annotations": [],
                "requirements": [],
                "subsections": [],
            }
            lines.append(f"{header_prefix} {t.name}")
            lines.append("")
            lines.append(f"> {t.functionality}")
            lines.append("")

            # Implementation Code & Annotations
            if getattr(t, "code_links", None):
                lines.append("**Implementation Code & Annotations:**")
                for link in t.code_links:
                    path = getattr(link, "file", None) or getattr(link, "path", None)
                    if not path and isinstance(link, dict):
                        path = link.get("file") or link.get("path")
                    if not path:
                        continue
                    start_l = getattr(link, "start_line", None) if not isinstance(link, dict) else link.get("start_line")
                    end_l = getattr(link, "end_line", None) if not isinstance(link, dict) else link.get("end_line")
                    range_str = f" (lines {start_l}-{end_l})" if start_l and end_l else ""
                    sec_dict["code_links"].append({"file": path, "start_line": start_l, "end_line": end_l})

                    annot = self.store.get_annotation(path) if hasattr(self.store, "get_annotation") else None
                    if annot and "summary" in annot:
                        summary = annot["summary"]
                        purpose = summary.get("purpose", "") if isinstance(summary, dict) else str(summary)
                        responsibilities = summary.get("responsibilities", []) if isinstance(summary, dict) else []
                        sec_dict["annotations"].append({"file": path, "purpose": purpose, "responsibilities": responsibilities})
                        lines.append(f"- `{path}`{range_str}: {purpose}")
                        if responsibilities:
                            lines.append(f"  - *Core responsibilities:* {', '.join(responsibilities[:3])}")
                    else:
                        lines.append(f"- `{path}`{range_str}")
                lines.append("")

            t_claims = claims_by_tenet.get(t.id, [])
            # Axioms first
            axioms = [c for c in t_claims if c.status == Status.AXIOM]
            if axioms:
                lines.append(f"**Verified Requirements (Axioms):**")
                for ax in axioms:
                    badge = " [UNVERIFIED OVERRIDE]" if ax.unverified else ""
                    lines.append(f"- **[REQ-{ax.id}]** {ax.statement}{badge}")
                    if ax.test_explanation:
                        lines.append(f"  - *Acceptance criterion:* {ax.test_explanation}")
                    sec_dict["requirements"].append({
                        "id": ax.id,
                        "status": "axiom",
                        "statement": ax.statement,
                        "criterion": ax.test_explanation,
                        "unverified": ax.unverified,
                    })
                lines.append("")

            # Hypotheses
            if include_hypotheses:
                hyps = [c for c in t_claims if c.status == Status.HYPOTHESIS]
                if hyps:
                    lines.append(f"*Provisional Requirements (Hypotheses):*")
                    for h in hyps:
                        lines.append(f"- *[PROV-{h.id}]* {h.statement} (confidence: {h.confidence:.2f})")
                        sec_dict["requirements"].append({
                            "id": h.id,
                            "status": "hypothesis",
                            "statement": h.statement,
                            "confidence": h.confidence,
                        })
                    lines.append("")

            # Children
            for child_id in t.children:
                child_tenet = tenets.get(child_id)
                if child_tenet:
                    child_sec = render_tenet(child_tenet, depth=depth + 1)
                    sec_dict["subsections"].append(child_sec)

            return sec_dict

        sections: List[Dict[str, Any]] = []
        for root in roots:
            sections.append(render_tenet(root, depth=2))

        # Known unknowns section
        if known_unknowns:
            lines.append("## Known Unknowns and Gaps")
            lines.append("")
            for uk in known_unknowns:
                lines.append(f"- {uk}")
            lines.append("")

        # Deviations section
        if deviations:
            lines.append("## Decisions and Deviations")
            lines.append("")
            for dev in deviations:
                lines.append(f"- {dev['note']}")
            lines.append("")

        markdown_text = "\n".join(lines)
        self.store.put_spec(markdown_text, sections, Actor.ENGINE)

        return CompiledSpec(
            markdown=markdown_text,
            readiness=readiness,
            sections=sections,
            known_unknowns=known_unknowns,
            deviations=deviations,
        )
