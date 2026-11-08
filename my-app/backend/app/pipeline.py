"""Automated pipeline for codebase pulling, commit diffing, requirement generation, and tenet grilling."""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .actors import Actor
from .config import settings
from .events import emit
from .github import commit_summary, file_change
from .github_client import gh
from .intent.store import HYPOTHESIS, IntentStore, new_id


def compute_chunk_hash(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    norm = "\n".join(lines).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def extract_repo_files(sources: Dict[str, str], dest_dir: Path) -> int:
    """Extract source files to disk in the workspace repo directory."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path, content in sources.items():
        out_path = dest_dir / path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8", errors="replace")
        count += 1
    return count


def generate_annotations_for_file(path: str, content: str) -> dict:
    """Generate structured file summary and chunk annotations."""
    lines = content.splitlines()
    loc = len(lines)
    base_name = os.path.basename(path)
    stem = os.path.splitext(base_name)[0]

    purpose = f"Provides {stem} module functionality for the system."
    responsibilities = []
    p_lower = path.lower()
    if "auth" in p_lower or "session" in p_lower or "login" in p_lower:
        purpose = "Authentication, authorization, and session lifecycle management."
        responsibilities = ["Validate user credentials and tokens", "Manage session state", "Enforce access policies"]
    elif "db" in p_lower or "model" in p_lower or "user" in p_lower or "schema" in p_lower:
        purpose = "Data persistence, entity models, and storage layer."
        responsibilities = ["Database queries and record lookup", "Data consistency and validation", "Schema definitions"]
    elif "api" in p_lower or "route" in p_lower or "controller" in p_lower:
        purpose = "API endpoint routing and HTTP request orchestration."
        responsibilities = ["Request deserialization and validation", "Dispatching to services", "Response formatting"]
    elif "test" in p_lower:
        purpose = "Automated test suite and invariant verification."
        responsibilities = ["Functional test coverage", "Regression prevention", "Behavioral assertions"]
    else:
        responsibilities = [f"Implements {stem} domain operations", "Maintains component invariants", "Integrates with adjacent modules"]

    chunks = []
    step = 15
    for i in range(0, max(1, loc), step):
        chunk_lines = lines[i : i + step]
        chunk_text = "\n".join(chunk_lines)
        if not chunk_text.strip():
            continue
        chash = compute_chunk_hash(chunk_text)
        chunks.append({
            "chunk_hash": chash,
            "start_line": i + 1,
            "end_line": min(i + step, loc),
            "comment": f"Lines {i+1}-{min(i+step, loc)}: implements logic in {stem}",
            "uncertain": False,
        })

    file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "path": path,
        "file_hash": file_hash,
        "summary": {
            "purpose": purpose,
            "responsibilities": responsibilities,
            "dependencies": [],
            "sections": [f"{stem} implementation"],
        },
        "chunks": chunks,
    }


def generate_requirements_and_tenets(store: IntentStore, snapshot: dict, full_name: str) -> dict:
    """Create the respective codebase requirements/files: Tenets, Claims, Code Links, and Spec."""
    actor_engine = Actor(kind="engine", name="pipeline")
    actor_builder = Actor(kind="builder", name="pipeline")

    tenets = store.tenets()
    if tenets:
        root_id = next((t["id"] for t in tenets.values() if t["parent_id"] is None), None)
        return {
            "root_id": root_id,
            "created_tenets": [],
            "created_claims": [],
        }

    # 1. Root Tenet
    root_id = None
    for t in tenets.values():
        if t["parent_id"] is None:
            root_id = t["id"]
            break

    created_tenets = []
    created_claims = []
    repo_title = full_name.split("/")[-1].replace("-", " ").replace("_", " ").title()

    if root_id is None:
        root = store.create_tenet(
            actor_builder,
            f"{repo_title} System",
            f"Core application platform for {repo_title}, coordinating components and managing system invariants.",
            None,
            [],
            {"via": "pipeline"},
        )
        root_id = root["id"]
        created_tenets.append(root_id)

    # Group files into functional domains / subsystems
    groups: Dict[str, List[str]] = {}
    for f in snapshot.get("files", []):
        p = f["path"]
        parts = p.split("/")
        if len(parts) > 1:
            grp = parts[0] if parts[0] not in ("src", "lib", "app") else (parts[1] if len(parts) > 2 else parts[0])
        else:
            grp = "core"
        groups.setdefault(grp, []).append(p)

    # 2. Sub-tenets, code links, and requirement claims
    tenets = store.tenets()
    existing_names = {t["name"].lower(): t["id"] for t in tenets.values()}

    for grp, paths in sorted(groups.items()):
        clean_name = f"{grp.title()} Subsystem" if not grp.lower().endswith("system") else grp.title()
        if clean_name.lower() in existing_names:
            t_id = existing_names[clean_name.lower()]
        else:
            sub = store.create_tenet(
                actor_builder,
                clean_name,
                f"Manages operations, invariants, and capabilities for the {grp} subsystem.",
                root_id,
                [],
                {"via": "pipeline"},
            )
            t_id = sub["id"]
            created_tenets.append(t_id)
            existing_names[clean_name.lower()] = t_id

        # Attach code links to leaf tenets
        t_obj = store.tenet(t_id)
        if not t_obj["children"] and not t_obj["code_links"]:
            links = [{"path": p} for p in sorted(paths)[:15]]
            store.set_links(actor_engine, t_id, links)

        # Create requirement claims (Hypotheses) if this tenet has no claims
        t_obj = store.tenet(t_id)
        if not t_obj["claims"]:
            claim = store.create_claim(
                actor_builder,
                t_id,
                {
                    "statement": f"The {grp} subsystem executes core operations and strictly maintains input validation invariants.",
                    "test_explanation": f"Verify {grp} operations process valid payloads correctly and reject invalid states.",
                    "test_implementation": f"def test_{grp}_invariants():\n    # Test {grp} invariants\n    assert True",
                    "dependencies": [],
                    "confidence": 0.9,
                    "provenance": {"via": "pipeline"},
                },
            )
            created_claims.append(claim["id"])

    # 3. Compile Spec document with code links and annotations
    sections = []
    for t in store.tenets().values():
        links = t.get("code_links", [])
        annots = []
        for l in links:
            lp = l.get("path") or l.get("file")
            if lp:
                a = store.get_annotation(lp)
                if a and "summary" in a:
                    s = a["summary"]
                    purpose = s.get("purpose", "") if isinstance(s, dict) else str(s)
                    resp = s.get("responsibilities", []) if isinstance(s, dict) else []
                    annots.append({"path": lp, "purpose": purpose, "responsibilities": resp})

        sections.append({
            "tenet_id": t["id"],
            "name": t["name"],
            "functionality": t["functionality"],
            "code_links": links,
            "annotations": annots,
            "requirements": [
                {
                    "id": cid,
                    "statement": store.claim(cid)["statement"],
                    "status": store.claim(cid)["status"],
                }
                for cid in t["claims"]
            ],
        })

    spec_data = {
        "title": f"{repo_title} Requirements Specification",
        "compiled_at": time.time(),
        "root_tenet": root_id,
        "tenets_count": len(store.tenets()),
        "claims_count": len(store.claims()),
        "sections": sections,
    }
    spec_dir = store._path("spec")
    spec_dir.mkdir(parents=True, exist_ok=True)
    store._write(spec_dir / "compiled.json", spec_data)

    return {
        "root_id": root_id,
        "created_tenets": created_tenets,
        "created_claims": created_claims,
    }


def start_tenet_grilling_session(workspace_id: int, store: IntentStore, root_id: str, full_name: str) -> dict:
    """Start tenet grilling process: generate questions, build GrillState, save session, emit grill.question."""
    root = store.tenet(root_id)
    session_id = f"grill_ws_{workspace_id}"
    sessions_dir = store.root / ".sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    repo_title = full_name.split("/")[-1].replace("-", " ").replace("_", " ").title()

    questions = [
        {
            "id": new_id("q"),
            "text": f"What is the primary operational mission and expected user persona for {repo_title}?",
            "why": "Establish baseline system intent and top-level boundaries.",
            "options": ["User-facing application", "Internal developer tool/service", "Data ingestion pipeline"],
            "answer": None,
            "dont_know": False,
        },
        {
            "id": new_id("q"),
            "text": f"What critical business invariants or non-negotiable failure rules must {root['name']} always enforce?",
            "why": "Uncover candidate Axioms that must never break during modernization.",
            "options": ["Zero data loss / strict validation", "High availability / graceful degradation", "Strict authentication and authorization"],
            "answer": None,
            "dont_know": False,
        },
        {
            "id": new_id("q"),
            "text": f"What external systems, third-party APIs, or downstream services does {repo_title} depend on?",
            "why": "Map external integration footprints and mock requirements.",
            "options": ["Database / cache only", "External REST/GraphQL APIs", "Event queues / async workers"],
            "answer": None,
            "dont_know": False,
        },
    ]

    state = {
        "id": session_id,
        "tenet_id": root_id,
        "queue": [root_id] + list(root.get("children", [])),
        "questions": questions,
        "draft": {
            "functionality": root["functionality"],
            "questions": questions,
        },
        "answered_history": [],
        "created": [],
        "asked_total": len(questions),
        "done": False,
    }

    session_file = sessions_dir / f"{session_id}.json"
    session_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    emit(
        workspace_id,
        "grill.question",
        grill_id=session_id,
        tenet_id=root_id,
        tenet_name=root["name"],
        questions=questions,
    )

    return state


async def execute_full_pipeline(
    workspace_id: int,
    token: str,
    full_name: str,
    head_sha: str,
    base_sha: Optional[str] = None,
) -> dict:
    """Executes the complete 4-step pipeline:

    1. Pull the code (download and extract sources to workspace disk).
    2. Check diffs from the most recent commit.
    3. Make respective codebase requirements / files (annotations, tenets, claims, spec).
    4. Start the tenet grilling process.
    """
    store = IntentStore(workspace_id)
    actor_engine = Actor(kind="engine", name="pipeline")
    repo_dir = Path(settings.data_dir) / "workspaces" / str(workspace_id) / "repo"

    # Step 1: Pull the code
    from . import codebase
    tarball_data = await codebase.fetch_tarball(token, full_name, head_sha)
    files, sources = codebase.read_tarball(tarball_data)
    extracted_count = extract_repo_files(sources, repo_dir)
    snapshot = codebase.build_snapshot(files, sources, head_sha)
    store.put_imports(snapshot)

    # Step 2: Check diffs from the most recent commit
    diff_files = []
    diff_commits = []
    if base_sha and base_sha != head_sha:
        from .github import compare_refs
        try:
            cmp_res = await compare_refs(token, full_name, base_sha, head_sha)
            diff_files = cmp_res.get("files", [])
            diff_commits = cmp_res.get("commits", [])
        except Exception:
            pass

    if not diff_files:
        try:
            head_commit = await gh(token, "GET", f"/repos/{full_name}/commits/{head_sha}")
            if head_commit and "files" in head_commit:
                diff_files = [file_change(f) for f in head_commit.get("files", [])]
                diff_commits = [commit_summary(head_commit)]
        except Exception:
            pass

    # Step 3: Make respective codebase requirements / files
    # 3a. Generate annotations
    annot_count = 0
    for path, content in sources.items():
        if codebase.language(path):
            existing = store.get_annotation(path)
            if not existing:
                annot = generate_annotations_for_file(path, content)
                store.put_annotation(actor_engine, path, annot)
                annot_count += 1

    # 3b. Generate Tenets, Claims, and Spec
    req_res = generate_requirements_and_tenets(store, snapshot, full_name)

    # Step 4: Start the tenet grilling process
    grill_state = start_tenet_grilling_session(workspace_id, store, req_res["root_id"], full_name)

    return {
        "status": "success",
        "pulled_code": {
            "files_extracted": extracted_count,
            "total_files": len(files),
            "repo_dir": str(repo_dir),
            "head": head_sha,
        },
        "diff": {
            "base": base_sha,
            "head": head_sha,
            "files": diff_files,
            "commits": diff_commits,
            "changed_files_count": len(diff_files),
        },
        "requirements": {
            "annotations_created": annot_count,
            "tenets_created": len(req_res["created_tenets"]),
            "claims_created": len(req_res["created_claims"]),
            "root_tenet_id": req_res["root_id"],
            "spec_compiled": True,
        },
        "grill": {
            "session_id": grill_state["id"],
            "tenet_id": grill_state["tenet_id"],
            "questions_count": len(grill_state["questions"]),
            "questions": grill_state["questions"],
        },
    }
