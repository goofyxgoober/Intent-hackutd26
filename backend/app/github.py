"""Read-only views of the user's GitHub repositories (no database needed)."""
import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import require_session
from .github_client import gh
from .sessions import Session

router = APIRouter(prefix="/api/github", tags=["github"])

MAX_FILE_BYTES = 1_000_000


@router.get("/repos")
async def list_repos(session: Session = Depends(require_session)) -> "list[dict]":
    """Repositories the signed-in user can access, for picking one to connect."""
    repos = await gh(
        session.access_token, "GET", "/user/repos", params={"per_page": 100, "sort": "updated"}
    )
    return [
        {
            "id": r["id"],
            "full_name": r["full_name"],
            "private": r["private"],
            "default_branch": r["default_branch"],
            "language": r.get("language"),
            "updated_at": r["updated_at"],
            "can_push": r.get("permissions", {}).get("push", False),
        }
        for r in repos
    ]


@router.get("/repos/{owner}/{repo}/tree")
async def repo_tree(
    owner: str, repo: str, ref: Optional[str] = None, session: Session = Depends(require_session)
) -> dict:
    """Every file path in the repo at `ref` (default branch if omitted)."""
    if ref is None:
        ref = (await gh(session.access_token, "GET", f"/repos/{owner}/{repo}"))["default_branch"]
    tree = await gh(
        session.access_token, "GET", f"/repos/{owner}/{repo}/git/trees/{ref}", params={"recursive": "1"}
    )
    files = [
        {"path": t["path"], "size": t.get("size", 0), "sha": t["sha"]}
        for t in tree.get("tree", [])
        if t["type"] == "blob"
    ]
    return {"ref": ref, "sha": tree["sha"], "truncated": tree.get("truncated", False), "files": files}


@router.get("/repos/{owner}/{repo}/file")
async def repo_file(
    owner: str, repo: str, path: str, ref: Optional[str] = None,
    session: Session = Depends(require_session),
) -> dict:
    """Contents of one text file."""
    params = {"ref": ref} if ref else None
    item = await gh(session.access_token, "GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)
    if isinstance(item, list) or item.get("type") != "file":
        raise HTTPException(400, f"{path} is a directory, not a file")
    if item.get("size", 0) > MAX_FILE_BYTES or not item.get("content"):
        raise HTTPException(413, f"{path} is too large to view here (over 1 MB)")
    raw = base64.b64decode(item["content"])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, f"{path} is a binary file")
    return {"path": item["path"], "sha": item["sha"], "size": item["size"], "content": text}


@router.get("/repos/{owner}/{repo}/commits")
async def repo_commits(
    owner: str, repo: str, ref: Optional[str] = None, limit: int = 20,
    session: Session = Depends(require_session),
) -> "list[dict]":
    params = {"per_page": max(1, min(limit, 100))}
    if ref:
        params["sha"] = ref
    commits = await gh(session.access_token, "GET", f"/repos/{owner}/{repo}/commits", params=params)
    return [
        {
            "sha": c["sha"],
            "message": c["commit"]["message"].split("\n", 1)[0],
            "author": (c.get("author") or {}).get("login") or c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
        }
        for c in commits
    ]
