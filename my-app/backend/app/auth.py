import logging
import secrets
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from . import db
from .config import settings
from .github_client import GITHUB_WEB, client
from .sessions import Session, create_session, delete_session, get_session

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("uvicorn.error")


def _public_user(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "login": user.get("login"),
        "name": user.get("name"),
        "avatar_url": user.get("avatar_url"),
        "html_url": user.get("html_url"),
        "two_factor_authentication": user.get("two_factor_authentication"),
    }


def require_session(request: Request) -> Session:
    session = get_session(request.cookies.get(settings.session_cookie))
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session


def _login_error(reason: str, detail: str = "") -> RedirectResponse:
    log.warning("GitHub sign-in failed: %s%s", reason, f" ({detail})" if detail else "")
    return RedirectResponse(f"{settings.frontend_url}/login?{urlencode({'error': reason})}")


@router.get("/github/login")
def github_login() -> RedirectResponse:
    if not settings.github_client_id:
        raise HTTPException(500, "GITHUB_CLIENT_ID is not set in backend/.env")
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": settings.github_scopes,
        "state": state,
        "allow_signup": "true",
    }
    response = RedirectResponse(f"{GITHUB_WEB}/login/oauth/authorize?{urlencode(params)}")
    response.set_cookie(
        settings.state_cookie,
        state,
        max_age=600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    if error:
        return _login_error(error, "GitHub returned an error to the callback")
    expected_state = request.cookies.get(settings.state_cookie)
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return _login_error("invalid_state", "state cookie missing or mismatched; sign-in took too long or cookies are blocked")

    async with client(GITHUB_WEB) as web:
        token_res = await web.post(
            "/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.redirect_uri,
            },
        )
    access_token = token_res.json().get("access_token") if token_res.is_success else None
    if not access_token:
        reason = token_res.json().get("error_description", "") if token_res.is_success else f"HTTP {token_res.status_code}"
        return _login_error("token_exchange_failed", reason or "no access_token in GitHub's reply")

    async with client() as api:
        user_res = await api.get(
            "/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
    if not user_res.is_success:
        return _login_error("user_fetch_failed", f"GET /user returned {user_res.status_code}")
    user = user_res.json()

    # GitHub reports this flag only to the account owner's own token. "Off" and
    # "not reported" get different messages so the cause is clear.
    two_factor = user.get("two_factor_authentication")
    if settings.require_2fa and two_factor is not True:
        if two_factor is False:
            return _login_error("2fa_required", f"{user.get('login')} has 2FA turned off")
        return _login_error("2fa_unknown", f"GitHub did not report 2FA status for {user.get('login')}")

    user_id = db.upsert_user(user["id"], user["login"])
    sid = create_session(access_token, _public_user(user), user_id)
    response = RedirectResponse(f"{settings.frontend_url}/dashboard")
    response.delete_cookie(settings.state_cookie)
    response.set_cookie(
        settings.session_cookie,
        sid,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/me")
def me(session: Session = Depends(require_session)) -> dict:
    return session.user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    delete_session(request.cookies.get(settings.session_cookie))
    response.delete_cookie(settings.session_cookie)
    return response
