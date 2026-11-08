from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copilot.db.models import ChatSession, TeamMember, User, utcnow


def get_user_team_id(db: Session, user_id: str) -> str | None:
    return db.scalar(select(TeamMember.team_id).where(TeamMember.user_id == user_id))


def create_session(db: Session, team_id: str, user_id: str,
                   title: str = "New chat",
                   selected_node_ids: list[str] | None = None) -> ChatSession:
    session = ChatSession(
        team_id=team_id,
        created_by=user_id,
        title=title[:80],
        selected_node_ids=selected_node_ids or [],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str) -> ChatSession | None:
    return db.get(ChatSession, session_id)


def list_team_sessions(db: Session, team_id: str) -> list[ChatSession]:
    stmt = (select(ChatSession)
            .where(ChatSession.team_id == team_id)
            .order_by(ChatSession.last_active_at.desc()))
    return list(db.scalars(stmt))


def touch_session(db: Session, session_id: str, added_messages: int) -> None:
    session = db.get(ChatSession, session_id)
    if session is None:
        return
    session.message_count += added_messages
    session.last_active_at = utcnow()
    db.commit()