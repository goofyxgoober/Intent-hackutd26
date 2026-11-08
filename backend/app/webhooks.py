"""GitHub push webhooks: record modified files and flag the intents they touch.

GitHub must be able to reach this endpoint, so in local dev expose port 8000
with a tunnel (e.g. `ngrok http 8000`) and set the webhook URL to
https://<tunnel>/webhooks/github with content type application/json.
"""
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, HTTPException, Request, Response

from . import db
from .config import settings

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/github", status_code=204)
async def github_webhook(request: Request) -> Response:
    if not settings.webhook_secret:
        raise HTTPException(503, "GITHUB_WEBHOOK_SECRET is not set in backend/.env")
    body = await request.body()
    expected = "sha256=" + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), expected):
        raise HTTPException(401, "Bad webhook signature")

    if request.headers.get("X-GitHub-Event") != "push":
        return Response(status_code=204)  # ping and other events need no action
    payload = json.loads(body)
    repository = payload["repository"]
    if payload.get("ref") != f"refs/heads/{repository['default_branch']}":
        return Response(status_code=204)

    changes: "dict[str, str]" = {}
    for commit in payload.get("commits", []):
        for status in ("added", "modified", "removed"):
            for path in commit.get(status, []):
                changes[path] = status
    if not changes:
        return Response(status_code=204)

    now = time.time()
    with db.connect() as conn:
        repo_ids = [
            r["id"]
            for r in conn.execute("SELECT id FROM repos WHERE full_name = ?", (repository["full_name"],))
        ]
        for repo_id in repo_ids:
            conn.executemany(
                "INSERT INTO file_events (repo_id, commit_sha, path, status, received_at) VALUES (?, ?, ?, ?, ?)",
                [(repo_id, payload["after"], p, s, now) for p, s in changes.items()],
            )
            db.mark_stale(conn, repo_id, set(changes))
    return Response(status_code=204)
