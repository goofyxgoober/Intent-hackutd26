"""Thin async wrapper around the GitHub REST API."""
from typing import Any, Optional

import httpx
from fastapi import HTTPException

GITHUB_API = "https://api.github.com"
GITHUB_WEB = "https://github.com"

# Tests swap this for an httpx.MockTransport.
transport: Optional[httpx.AsyncBaseTransport] = None


def client(base_url: str = GITHUB_API) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=15, transport=transport)


async def gh(
    token: str,
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    json: Optional[dict] = None,
    allow_404: bool = False,
    raw_diff: bool = False,
) -> Any:
    """Call the GitHub API as the signed-in user and translate failures to HTTP errors.

    With raw_diff=True the response body is returned as unified-diff text.
    """
    async with client() as c:
        res = await c.request(
            method,
            path,
            params=params,
            json=json,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.diff" if raw_diff else "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if res.status_code == 404 and allow_404:
        return None
    if res.is_success:
        if raw_diff:
            return res.text
        return res.json() if res.content else None

    try:
        message = res.json().get("message", "")
    except ValueError:
        message = res.text[:200]
    if res.status_code == 401:
        raise HTTPException(401, "GitHub token expired or was revoked. Sign in again.")
    if res.status_code == 403 and res.headers.get("x-ratelimit-remaining") == "0":
        raise HTTPException(429, "GitHub API rate limit reached. Try again in a few minutes.")
    if res.status_code == 422:
        raise HTTPException(422, f"GitHub: {message or 'invalid ref or path'}")
    if res.status_code in (403, 404):
        raise HTTPException(res.status_code, f"GitHub: {message or 'not found or no access'}")
    raise HTTPException(502, f"GitHub returned {res.status_code}: {message}")
