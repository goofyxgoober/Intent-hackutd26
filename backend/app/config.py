import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    github_client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    github_client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    github_scopes: str = os.getenv("GITHUB_OAUTH_SCOPES", "read:user repo")
    redirect_uri: str = os.getenv(
        "OAUTH_REDIRECT_URI", "http://localhost:8000/auth/github/callback"
    )
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    session_cookie: str = "intentflow_session"
    state_cookie: str = "intentflow_oauth_state"
    session_ttl_seconds: int = 60 * 60 * 24 * 7


settings = Settings()
