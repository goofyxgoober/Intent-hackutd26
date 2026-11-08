from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth, github
from .config import settings

app = FastAPI(title="IntentFlow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(github.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
