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
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    cookie_secure: bool = _bool("COOKIE_SECURE", "false")
    # Only let in GitHub accounts that have two-factor authentication turned on.
    require_2fa: bool = _bool("REQUIRE_GITHUB_2FA", "true")
    database_path: str = os.getenv("DATABASE_PATH", "intentflow.db")
    webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    intent_branch: str = os.getenv("INTENT_BRANCH", "intentflow/intents")
    intent_folder: str = os.getenv("INTENT_FOLDER", ".intentflow")
    # Where each connected repo's intent folder lives on the backend.
    data_dir: str = os.getenv("DATA_DIR", "data")
    # Agent API keys, "role:key" pairs separated by commas. Roles: builder, test_runner, engine.
    agent_keys: str = os.getenv("AGENT_KEYS", "")
    # Pushes arriving within this many seconds of each other are handled as one batch.
    sync_debounce_seconds: float = float(os.getenv("SYNC_DEBOUNCE_SECONDS", "20"))
    # "peer_children" (spec default) or "any": which Tenets a composition reference may target.
    reference_scope: str = os.getenv("REFERENCE_SCOPE", "peer_children")
    # Polling: check the default branch for new commits this often (0 turns it off).
    poll_interval_seconds: float = float(os.getenv("POLL_INTERVAL_SECONDS", "30"))
    # Stop polling a repo nobody has used for this long; it restarts on next use.
    poll_idle_stop_seconds: float = float(os.getenv("POLL_IDLE_STOP_SECONDS", "1800"))
    session_cookie: str = "intentflow_session"
    state_cookie: str = "intentflow_oauth_state"
    session_ttl_seconds: int = 60 * 60 * 24 * 7


settings = Settings()
