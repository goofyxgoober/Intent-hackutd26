"""Read-only views of the user's GitHub repositories (no database needed)."""
import base64
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from .auth import require_session
from .github_client import gh
from .sessions import Session

router = APIRouter(prefix="/api/github", tags=["github"])

MAX_FILE_BYTES = 1_000_000
MAX_DIFF_BYTES = 5_000_000
# Branch names, tags and SHAs. Git forbids ".." in ref names, which also keeps
# a ref from walking to another API path.
_REF = re.compile(r"^[A-Za-z0-9._/\-]{1,250}$")


def check_ref(ref: str) -> str:
    if not _REF.match(ref) or ".." in ref or ref.startswith("/"):
        raise HTTPException(422, f"Not a valid branch, tag or commit: {ref!r}")
    return ref


def check_path(path: str) -> str:
    parts = path.split("/")
    if not path or path.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise HTTPException(422, f"Not a valid file path: {path!r}")
    return path


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _ranges(lines: "list[int]") -> "list[list[int]]":
    out: "list[list[int]]" = []
    for n in lines:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def changed_lines(patch: Optional[str]) -> dict:
    """Line numbers a patch touches: `added` in the new file, `removed` in the old one."""
    added: "list[int]" = []
    removed: "list[int]" = []
    old = new = 0
    for line in (patch or "").split("\n"):
        m = _HUNK.match(line)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
        elif line.startswith("+"):
            added.append(new)
            new += 1
        elif line.startswith("-"):
            removed.append(old)
            old += 1
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        elif old or new:
            old += 1
            new += 1
    return {"added": _ranges(added), "removed": _ranges(removed)}


def file_change(f: dict) -> dict:
    """One changed file from a GitHub commit or compare response."""
    changes = f.get("changes", f.get("additions", 0) + f.get("deletions", 0))
    return {
        "path": f["filename"],
        "previous_path": f.get("previous_filename"),
        "status": f["status"],
        "additions": f.get("additions", 0),
        "deletions": f.get("deletions", 0),
        "patch": f.get("patch"),
        "changed_lines": changed_lines(f.get("patch")),
        # GitHub drops the patch for very large or binary files; fetch /diff instead.
        "patch_truncated": f.get("patch") is None and changes > 0,
    }


def commit_summary(c: dict) -> dict:
    author = c.get("author") or {}
    return {
        "sha": c["sha"],
        "message": c["commit"]["message"].split("\n", 1)[0],
        "author": author.get("login") or c["commit"]["author"]["name"],
        "avatar_url": author.get("avatar_url"),
        "date": c["commit"]["author"]["date"],
        "html_url": c.get("html_url"),
    }


async def list_commits(
    token: str, full_name: str, ref: Optional[str] = None, path: Optional[str] = None, limit: int = 20
) -> "list[dict]":
    params: dict = {"per_page": max(1, min(limit, 100))}
    if ref:
        params["sha"] = check_ref(ref)
    if path:
        params["path"] = check_path(path)
    commits = await gh(token, "GET", f"/repos/{full_name}/commits", params=params)
    return [commit_summary(c) for c in commits]


async def compare_refs(token: str, full_name: str, base: str, head: str) -> dict:
    cmp = await gh(token, "GET", f"/repos/{full_name}/compare/{check_ref(base)}...{check_ref(head)}")
    files = [file_change(f) for f in cmp.get("files", [])]
    return {
        "base": base,
        "head": head,
        "status": cmp.get("status"),
        "ahead_by": cmp.get("ahead_by", 0),
        "behind_by": cmp.get("behind_by", 0),
        "commits": [commit_summary(c) for c in cmp.get("commits", [])],
        # GitHub's compare API lists at most 300 files.
        "truncated": len(files) >= 300,
        "files": files,
    }


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


@router.get("/repos/{owner}/{repo}/branches")
async def list_branches(owner: str, repo: str, session: Session = Depends(require_session)) -> "list[dict]":
    branches = await gh(
        session.access_token, "GET", f"/repos/{owner}/{repo}/branches", params={"per_page": 100}
    )
    return [{"name": b["name"], "sha": b["commit"]["sha"]} for b in branches]


@router.get("/repos/{owner}/{repo}/tree")
async def repo_tree(
    owner: str, repo: str, ref: Optional[str] = None, session: Session = Depends(require_session)
) -> dict:
    """Every file path in the repo at `ref` (default branch if omitted)."""
    if ref is None:
        ref = (await gh(session.access_token, "GET", f"/repos/{owner}/{repo}"))["default_branch"]
    tree = await gh(
        session.access_token, "GET", f"/repos/{owner}/{repo}/git/trees/{check_ref(ref)}",
        params={"recursive": "1"},
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
    params = {"ref": check_ref(ref)} if ref else None
    item = await gh(
        session.access_token, "GET", f"/repos/{owner}/{repo}/contents/{check_path(path)}", params=params
    )
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
    owner: str, repo: str, ref: Optional[str] = None, path: Optional[str] = None, limit: int = 20,
    session: Session = Depends(require_session),
) -> "list[dict]":
    """Commit history, newest first. Pass `path` for the history of one file."""
    return await list_commits(session.access_token, f"{owner}/{repo}", ref, path, limit)


@router.get("/repos/{owner}/{repo}/commits/{sha}")
async def commit_detail(
    owner: str, repo: str, sha: str, session: Session = Depends(require_session)
) -> dict:
    """One commit with every file it changed and each file's diff."""
    c = await gh(session.access_token, "GET", f"/repos/{owner}/{repo}/commits/{check_ref(sha)}")
    return {
        **commit_summary(c),
        "full_message": c["commit"]["message"],
        "parents": [p["sha"] for p in c.get("parents", [])],
        "stats": c.get("stats", {}),
        "files": [file_change(f) for f in c.get("files", [])],
    }


@router.get("/repos/{owner}/{repo}/compare")
async def compare(
    owner: str, repo: str, base: str, head: str, session: Session = Depends(require_session)
) -> dict:
    """Commits and file diffs between any two branches, tags or commits."""
    return await compare_refs(session.access_token, f"{owner}/{repo}", base, head)


@router.get("/repos/{owner}/{repo}/diff", response_class=PlainTextResponse)
async def raw_diff(
    owner: str, repo: str, sha: Optional[str] = None, base: Optional[str] = None,
    head: Optional[str] = None, session: Session = Depends(require_session),
) -> PlainTextResponse:
    """Full unified diff, including files GitHub leaves out of the JSON. Use `sha`, or `base` and `head`."""
    if sha:
        path = f"/repos/{owner}/{repo}/commits/{check_ref(sha)}"
    elif base and head:
        path = f"/repos/{owner}/{repo}/compare/{check_ref(base)}...{check_ref(head)}"
    else:
        raise HTTPException(422, "Pass either sha, or both base and head")
    text = await gh(session.access_token, "GET", path, raw_diff=True)
    if len(text.encode()) > MAX_DIFF_BYTES:
        raise HTTPException(413, "Diff is larger than 5 MB")
    return PlainTextResponse(text)
