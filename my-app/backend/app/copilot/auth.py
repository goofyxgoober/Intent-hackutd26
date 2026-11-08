from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.copilot.db.meta_db import get_meta_db
from app.copilot.db.models import User, Team, TeamMember
from app.copilot.repositories import session_repo


@dataclass
class CurrentUser:
    id: str
    username: str
    team_id: str


def get_current_user(request: Request, meta_db: DBSession = Depends(get_meta_db)) -> CurrentUser:
    # 1. Check if authenticated via Ayaan's GitHub session cookie
    try:
        from app.config import settings
        from app.sessions import get_session
        sid = request.cookies.get(settings.session_cookie)
        gh_session = get_session(sid)
        if gh_session and gh_session.user:
            gh_username = gh_session.user.get("login", "")
            user = meta_db.scalar(select(User).where(User.username == gh_username))
            if not user:
                # Provision user & link to dev-team
                user = User(username=gh_username)
                meta_db.add(user)
                meta_db.flush()
                team = meta_db.scalar(select(Team).where(Team.name == "dev-team"))
                if team:
                    meta_db.add(TeamMember(team_id=team.id, user_id=user.id, role="member"))
                meta_db.commit()
            team_id = session_repo.get_user_team_id(meta_db, user.id)
            return CurrentUser(id=user.id, username=user.username, team_id=team_id)
    except Exception:
        pass

    # 2. Fallback to seeded "dev" user (for offline, local scripts, and tests)
    user = meta_db.scalar(select(User).where(User.username == "dev"))
    if user is None:
        raise HTTPException(status_code=500, detail="Dev user missing; did init_db() run?")
    team_id = session_repo.get_user_team_id(meta_db, user.id)
    return CurrentUser(id=user.id, username=user.username, team_id=team_id)
