import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db, events, github, repos, sync, webhooks
from .intent import routes as intent_routes
from .config import settings
from intentflow.api import router as engine_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    events.bind_loop(asyncio.get_running_loop())
    yield
    sync.stop_all()


app = FastAPI(title="IntentFlow API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
