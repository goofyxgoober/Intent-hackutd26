import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DEFAULT_DB_DIR = Path(__file__).resolve().parents[3]
_DB_DIR = Path(os.getenv("CHAT_DB_DIR", str(_DEFAULT_DB_DIR)))
_DB_PATH = _DB_DIR / "messages.db"
_DB_DIR.mkdir(parents=True, exist_ok=True)


class MessageBase(DeclarativeBase):
    """Base class for tables that live in messages.db only."""


message_engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False},
)

MessageSession = sessionmaker(bind=message_engine, autoflush=False)


def get_message_db():
    db = MessageSession()
    try:
        yield db
    finally:
        db.close()