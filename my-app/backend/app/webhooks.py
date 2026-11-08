"""GitHub push webhooks: git is the notification system (spec rule 11).

GitHub must be able to reach this endpoint, so in local dev expose port 8000
with a tunnel (e.g. `ngrok http 8000`) and set the webhook URL to
https://<tunnel>/webhooks/github with content type application/json.
"""
import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Request, Response

from . import sync
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
    # Pushes are stored, then handled together once they go quiet (debouncing).
    for workspace_id in sync.record_push(json.loads(body)):
        sync.schedule(workspace_id)
    return Response(status_code=204)
