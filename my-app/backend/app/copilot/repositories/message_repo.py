from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.copilot.db.models import Message


def load_recent(db: Session, session_id: str, limit: int = 20) -> list[Message]:
    """Last `limit` messages, returned oldest-first."""
    stmt = (select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.seq.desc())
            .limit(limit))
    return list(reversed(list(db.scalars(stmt))))


def load_all(db: Session, session_id: str) -> list[Message]:
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.seq)
    return list(db.scalars(stmt))


def append_messages(db: Session, session_id: str, items: list[dict]) -> None:
    """items: dicts with role, content, and optionally token_metrics,
    retrieved_items, agent_steps. Assigns seq numbers in order."""
    last_seq = db.scalar(
        select(func.max(Message.seq)).where(Message.session_id == session_id)
    )
    next_seq = 0 if last_seq is None else last_seq + 1
    for offset, item in enumerate(items):
        db.add(Message(session_id=session_id, seq=next_seq + offset, **item))
    db.commit()