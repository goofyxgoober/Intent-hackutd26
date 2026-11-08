"""The Functional Intent Graph (CONTEXT.md §5) for a connected GitHub repo.

Built from what the sync already stored: the codebase snapshot (files and import edges),
file annotations (what each file is for), and the Tenet hierarchy (the claims that constrain a file).
No LLM call is needed, so the graph appears as soon as the first sync finishes and stays live.
"""
import posixpath
from typing import Dict, List

from . import codebase
from .intent.store import AXIOM, IntentStore

MAX_NODES = 120
CHARS_PER_TOKEN = 4


def _name(path: str) -> str:
    stem = posixpath.splitext(posixpath.basename(path))[0]
    return stem.replace("_", " ").replace("-", " ").strip().title() or path


def _purpose(annotation) -> str:
    summary = annotation.get("summary") if isinstance(annotation, dict) else None
    if isinstance(summary, dict):
        return summary.get("purpose") or ""
    return summary if isinstance(summary, str) else ""


def build_graph(store: IntentStore, full_name: str) -> dict:
    """IntentGraphPayload: {repo_name, nodes[], edges[]}. Empty until the repo has been synced once."""
    snap = store.imports()
    if not snap:
        return {"repo_name": full_name, "nodes": [], "edges": []}

    sizes = {f["path"]: f.get("size", 0) for f in snap["files"]}
    source_paths = [p for p in sizes if codebase.language(p)]
    degree: Dict[str, int] = {p: 0 for p in source_paths}
    for e in snap["edges"]:
        for end in (e["source"], e["target"]):
            if end in degree:
                degree[end] += 1
    keep = set(sorted(source_paths, key=lambda p: (-degree[p], p))[:MAX_NODES])

    claims_by_file: Dict[str, List[dict]] = {}
    claims = store.claims()
    for t in store.tenets().values():
        mine = [c for c in claims.values() if c["tenet_id"] == t["id"]]
        for link in t.get("code_links", []):
            claims_by_file.setdefault(link["path"], []).extend(mine)

    edges = [
        {"source": e["source"], "target": e["target"], "relation": "imports"}
        for e in snap["edges"]
        if e["source"] in keep and e["target"] in keep and e["source"] != e["target"]
    ]
    downstream: Dict[str, List[str]] = {}
    for e in edges:
        downstream.setdefault(e["source"], []).append(e["target"])

    nodes = []
    for path in sorted(keep):
        claim_list = claims_by_file.get(path, [])
        axioms = [c for c in claim_list if c["status"] == AXIOM]
        hypotheses = [c for c in claim_list if c["status"] != AXIOM]
        purpose = _purpose(store.get_annotation(path))
        parts = path.split("/")
        is_test = any(p in ("tests", "test", "__tests__") for p in parts) or posixpath.basename(path).startswith(("test_", "conftest"))
        nodes.append({
            "node_id": path,
            "name": _name(path),
            "source_file": path,
            "intent_summary": purpose or f"{_name(path)}: not annotated yet.",
            "inputs": {},
            "outputs": {},
            "business_invariants": [c["statement"] for c in axioms + hypotheses],
            "downstream_dependencies": downstream.get(path, []),
            "meta": {
                "kind": "test" if is_test else "flow",
                "status": f"◆{len(axioms)} ◇{len(hypotheses)}" if claim_list else None,
                "boundary": "/".join(parts[:-1]) or "root",
                "raw_tokens": max(1, sizes.get(path, 0) // CHARS_PER_TOKEN),
            },
        })
    for n in nodes:
        if n["meta"]["status"] is None:
            del n["meta"]["status"]
    return {"repo_name": full_name, "nodes": nodes, "edges": edges}
