from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DB_PATH = Path(__file__).resolve().parents[3] / "meta.db"


class MetaBase(DeclarativeBase):
    """Base class for tables that live in meta.db only."""


meta_engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(meta_engine, "connect")
def _enable_foreign_keys(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


MetaSession = sessionmaker(bind=meta_engine, autoflush=False)


def get_meta_db():
    db = MetaSession()
    try:
        yield db
    finally:
        db.close()