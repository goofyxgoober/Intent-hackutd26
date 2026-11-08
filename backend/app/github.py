import httpx
from fastapi import APIRouter, Depends, HTTPException

from .auth import GITHUB_API, require_session
from .sessions import Session

router = APIRouter(prefix="/api/github", tags=["github"])


@router.get("/repos")
async def list_repos(session: Session = Depends(require_session)) -> list[dict]:
    """Repositories the signed-in user can access, for picking one to sync."""
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(
            f"{GITHUB_API}/user/repos",
            params={"per_page": 100, "sort": "updated"},
            headers={
                "Authorization": f"Bearer {session.access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
    if not res.is_success:
        raise HTTPException(res.status_code, "GitHub request failed")
    return [
        {
            "id": r["id"],
            "full_name": r["full_name"],
            "private": r["private"],
            "default_branch": r["default_branch"],
            "language": r.get("language"),
            "updated_at": r["updated_at"],
        }
        for r in res.json()
    ]
