"""Tests for the 4-step pipeline:

1. Pull code to workspace disk.
2. Check diffs from the most recent commit.
3. Make respective codebase requirements / files (annotations, tenets, claims, spec).
4. Start tenet grilling process.
"""
from pathlib import Path
import pytest
from app.config import settings
from .test_intent import c, gh, url, REPO, BASE_SHA, HEAD_SHA


def test_initial_sync_executes_pipeline_and_starts_grilling(c):
    # Initial sync triggers the full pipeline
    batch = c.post(f"/api/repos/{REPO}/sync").json()
    assert batch["initial"] is True
    assert batch["head"] == BASE_SHA

    # 1. Pull code: files extracted to workspace repo directory
    workspace_repo_dir = Path(settings.data_dir) / "workspaces" / str(c.wid) / "repo"
    assert workspace_repo_dir.exists()
    assert (workspace_repo_dir / "src/auth/session.py").exists()
    assert (workspace_repo_dir / "web/src/app.ts").exists()

    # 2. Check diffs from most recent commit
    assert "files" in batch

    # 3. Make respective codebase requirements / files
    tree = c.get(url(c, "/tree")).json()
    tenets = tree["tenets"]
    claims = tree["claims"]

    # Root system tenet created
    root = next((t for t in tenets if t["parent_id"] is None), None)
    assert root is not None
    assert "System" in root["name"]

    # Subsystem tenets created with code links
    assert len(tenets) > 1
    leaf_tenets = [t for t in tenets if t["is_leaf"]]
    assert len(leaf_tenets) > 0
    assert any(len(t["code_links"]) > 0 for t in leaf_tenets)

    # Requirement claims created
    assert len(claims) > 0

    # Annotations created
    annot = c.get(url(c, "/annotations"), params={"path": "src/auth/session.py"}).json()
    assert "summary" in annot
    assert "chunks" in annot

    # Codebase view carries annotations directly
    codebase_view = c.get(url(c, "/codebase")).json()
    auth_file = next(f for f in codebase_view["files"] if f["path"] == "src/auth/session.py")
    assert auth_file["annotated"] is True
    assert auth_file["annotation"] is not None
    assert "purpose" in auth_file["annotation"]

    # Spec compiled
    spec_file = Path(settings.data_dir) / "workspaces" / str(c.wid) / "intent" / "spec" / "compiled.json"
    assert spec_file.exists()
    import json
    spec_data = json.loads(spec_file.read_text())
    assert "sections" in spec_data
    assert any(len(s.get("code_links", [])) > 0 for s in spec_data["sections"])
    assert any(len(s.get("annotations", [])) > 0 for s in spec_data["sections"])

    # 4. Start tenet grilling process
    session_file = Path(settings.data_dir) / "workspaces" / str(c.wid) / "intent" / ".sessions" / f"grill_ws_{c.wid}.json"
    assert session_file.exists()

    grill_batch_info = batch.get("grill")
    assert grill_batch_info is not None
    assert grill_batch_info["questions_count"] == 3
    assert grill_batch_info["tenet_id"] == root["id"]


def test_explicit_pipeline_endpoint(c, gh):
    gh.head = HEAD_SHA
    # Call explicit pipeline endpoint
    res = c.post(f"/api/repos/{REPO}/pipeline").json()
    assert res["status"] == "success"

    # Step 1: Pulled code
    assert res["pulled_code"]["files_extracted"] > 0
    assert res["pulled_code"]["head"] == HEAD_SHA

    # Step 2: Diffs from most recent commit
    assert "diff" in res
    assert "files" in res["diff"]

    # Step 3: Requirements
    assert res["requirements"]["spec_compiled"] is True
    assert res["requirements"]["tenets_created"] >= 1

    # Step 4: Grilling
    assert res["grill"]["questions_count"] == 3
    assert len(res["grill"]["questions"]) == 3
    first_q = res["grill"]["questions"][0]
    assert "text" in first_q
    assert "why" in first_q


def test_workspace_pipeline_endpoint(c, gh):
    gh.head = HEAD_SHA
    res = c.post(url(c, "/pipeline")).json()
    assert res["status"] == "success"
    assert res["pulled_code"]["files_extracted"] > 0
    assert res["requirements"]["spec_compiled"] is True
    assert res["grill"]["questions_count"] == 3
