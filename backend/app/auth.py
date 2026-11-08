import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .config import settings
from .sessions import Session, create_session, delete_session, get_session

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API = "https://api.github.com"


def _public_user(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "login": user.get("login"),
        "name": user.get("name"),
        "avatar_url": user.get("avatar_url"),
        "html_url": user.get("html_url"),
    }


def require_session(request: Request) -> Session:
    session = get_session(request.cookies.get(settings.session_cookie))
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session


def _login_error(reason: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.frontend_url}/login?{urlencode({'error': reason})}")


@router.get("/github/login")
def github_login() -> RedirectResponse:
    if not settings.github_client_id:
        raise HTTPException(500, "GITHUB_CLIENT_ID is not configured")
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": settings.github_scopes,
        "state": state,
        "allow_signup": "true",
    }
    response = RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}")
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
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return _login_error(error)
    expected_state = request.cookies.get(settings.state_cookie)
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return _login_error("invalid_state")

    async with httpx.AsyncClient(timeout=10) as client:
        token_res = await client.post(
            GITHUB_TOKEN_URL,
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
            return _login_error("token_exchange_failed")

        user_res = await client.get(
            f"{GITHUB_API}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if not user_res.is_success:
            return _login_error("user_fetch_failed")

    sid = create_session(access_token, _public_user(user_res.json()))
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
