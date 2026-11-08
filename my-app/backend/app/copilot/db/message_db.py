from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DB_PATH = Path(__file__).resolve().parents[3] / "messages.db"


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