import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db, errors, events, github, repos, sync, webhooks
from .intent import routes as intent_routes
from .copilot.api.routes import router as copilot_router
from .copilot.db.init_db import init_db as init_copilot_db
from .config import settings

# The engine package (intentflow/) lives in my-app/, one level above backend/.
# Make it importable however uvicorn is started (npm run dev:api, or from backend/).
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from intentflow.api import router as engine_router  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    init_copilot_db()
    events.bind_loop(asyncio.get_running_loop())
    yield
    sync.stop_all()


app = FastAPI(title="IntentFlow API", lifespan=lifespan)
errors.install(app)
init_copilot_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(github.router)
app.include_router(repos.router)
app.include_router(webhooks.router)
app.include_router(intent_routes.router)
app.include_router(intent_routes.ws_router)
app.include_router(engine_router)
app.include_router(copilot_router)


@app.get("/")
def read_root() -> dict:
    return {
        "service": "IntentFlow Unified API",
        "agent": "Google Gemini Modernization & Test Orchestrator",
        "status": "online",
        "endpoints": {
            "chat": "POST /api/chat",
            "sessions": "GET/POST /api/sessions",
            "session_messages": "GET /api/sessions/{session_id}/messages",
            "compare": "POST /api/chat/compare",
            "test_generation": "POST /api/generate-tests",
            "intent_graph": "GET /api/graph",
            "metrics": "GET /api/metrics/summary",
            "docs": "/docs"
        }
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
