import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


class Settings:
    github_client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    github_client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    github_scopes: str = os.getenv("GITHUB_OAUTH_SCOPES", "read:user repo")
    redirect_uri: str = os.getenv(
        "OAUTH_REDIRECT_URI", "http://localhost:8000/auth/github/callback"
    )
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    cookie_secure: bool = _bool("COOKIE_SECURE", "false")
    # Only let in GitHub accounts that have two-factor authentication turned on.
    require_2fa: bool = _bool("REQUIRE_GITHUB_2FA", "true")
    database_path: str = os.getenv("DATABASE_PATH", "intentflow.db")
    webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    intent_branch: str = os.getenv("INTENT_BRANCH", "intentflow/intents")
    intent_file_path: str = os.getenv("INTENT_FILE_PATH", ".intentflow/intent_graph.json")
    session_cookie: str = "intentflow_session"
    state_cookie: str = "intentflow_oauth_state"
    session_ttl_seconds: int = 60 * 60 * 24 * 7


settings = Settings()
