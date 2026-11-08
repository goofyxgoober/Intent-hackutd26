"""Commit the intent folder to the user's repo on its own branch (spec sections 6, 18).

Layout in the repo:
  .intentflow/tenets/<root>/<child>/.../tenet.json   nested folders mirror ownership
  .intentflow/claims/<tenet_id>/<claim_id>.json
  .intentflow/links/, history/, spec/, changelog/, annotations/
  .intentflow/.gitignore                              ignores results/ (reproducible)
"""
import json
import re
from typing import Dict

from fastapi import HTTPException

from ..github_client import gh
from .store import IntentStore


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "tenet"


def render_folder(store: IntentStore) -> Dict[str, str]:
    files: Dict[str, str] = {".gitignore": "results/\n"}
    tenets = store.tenets()

    def folder(tid: str) -> str:
        chain = [tid] + store.ancestors(tenets, tid)
        return "/".join(f"{_slug(tenets[t]['name'])}--{t}" for t in reversed(chain))

    for t in tenets.values():
        files[f"tenets/{folder(t['id'])}/tenet.json"] = json.dumps(t, indent=2)
    for sub in ("claims", "links", "history", "spec", "changelog", "annotations"):
        base = store.root / sub
        for f in sorted(base.rglob("*")):
            if f.is_file() and not f.name.endswith(".tmp"):
                files[f"{sub}/{f.relative_to(base).as_posix()}"] = f.read_text()
    return files


async def export_to_branch(token: str, full_name: str, default_branch: str, branch: str,
                           folder: str, store: IntentStore) -> dict:
    info = await gh(token, "GET", f"/repos/{full_name}")
    if not (info.get("permissions") or {}).get("push"):
        raise HTTPException(403, f"Your GitHub account can't push to {full_name}")
    if branch == default_branch:
        raise HTTPException(422, "Intent exports never write to the default branch")

    ref = await gh(token, "GET", f"/repos/{full_name}/git/ref/heads/{branch}", allow_404=True)
    if ref is None:
        base = await gh(token, "GET", f"/repos/{full_name}/git/ref/heads/{default_branch}")
        await gh(token, "POST", f"/repos/{full_name}/git/refs",
                 json={"ref": f"refs/heads/{branch}", "sha": base["object"]["sha"]})
        ref = {"object": {"sha": base["object"]["sha"]}}
    parent_sha = ref["object"]["sha"]
    parent = await gh(token, "GET", f"/repos/{full_name}/git/commits/{parent_sha}")

    files = render_folder(store)
    folder_tree = await gh(token, "POST", f"/repos/{full_name}/git/trees", json={
        "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in sorted(files.items())],
    })
    # Swapping the whole folder in one entry also removes files that no longer exist.
    root_tree = await gh(token, "POST", f"/repos/{full_name}/git/trees", json={
        "base_tree": parent["tree"]["sha"],
        "tree": [{"path": folder, "mode": "040000", "type": "tree", "sha": folder_tree["sha"]}],
    })
    if root_tree["sha"] == parent["tree"]["sha"]:
        return {"branch": branch, "commit_sha": parent_sha, "files": len(files), "changed": False}
    commit = await gh(token, "POST", f"/repos/{full_name}/git/commits", json={
        "message": f"Update IntentFlow intent folder ({len(store.tenets())} tenets)",
        "tree": root_tree["sha"],
        "parents": [parent_sha],
    })
    await gh(token, "PATCH", f"/repos/{full_name}/git/refs/heads/{branch}", json={"sha": commit["sha"]})
    return {"branch": branch, "commit_sha": commit["sha"], "files": len(files), "changed": True}
