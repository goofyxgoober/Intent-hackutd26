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

    # Two-Mode Terminal and Query Engine settings
    query_planner_max_files: int = int(os.getenv("QUERY_PLANNER_MAX_FILES", "8"))
    query_max_rounds: int = int(os.getenv("QUERY_MAX_ROUNDS", "2"))
    query_outline_token_budget: int = int(os.getenv("QUERY_OUTLINE_TOKEN_BUDGET", "3000"))
    query_context_token_budget: int = int(os.getenv("QUERY_CONTEXT_TOKEN_BUDGET", "10000"))
    query_source_max_lines_per_file: int = int(os.getenv("QUERY_SOURCE_MAX_LINES_PER_FILE", "120"))
    query_source_max_total_lines: int = int(os.getenv("QUERY_SOURCE_MAX_TOTAL_LINES", "400"))
    query_answer_provider: str = os.getenv("QUERY_ANSWER_PROVIDER", "nemotron")
    query_fallback_to_gemini: bool = _bool("QUERY_FALLBACK_TO_GEMINI", "true")
    chat_generation_timeout_seconds: int = int(os.getenv("CHAT_GENERATION_TIMEOUT_SECONDS", "120"))
    nemotron_tier_query_answer: str = os.getenv("NEMOTRON_TIER_QUERY_ANSWER", "fast")

    # Jev Decision & Hypothesis Generation Settings
    jev_prompt_min_confidence: float = float(os.getenv("JEV_PROMPT_MIN_CONFIDENCE", "0.75"))
    jev_decision_ttl_seconds: int = int(os.getenv("JEV_DECISION_TTL_SECONDS", "300"))
    hypothesis_per_tenet_cap: int = int(os.getenv("HYPOTHESIS_PER_TENET_CAP", "10"))
    hypothesis_rate_limit_per_minute: int = int(os.getenv("HYPOTHESIS_RATE_LIMIT_PER_MINUTE", "10"))
    nemotron_tier_jev_prompt: str = os.getenv("NEMOTRON_TIER_JEV_PROMPT", "fast")
    nemotron_tier_generator: str = os.getenv("NEMOTRON_TIER_GENERATOR", "deep")
    nemotron_tier_verifier: str = os.getenv("NEMOTRON_TIER_VERIFIER", "fast")



settings = Settings()
