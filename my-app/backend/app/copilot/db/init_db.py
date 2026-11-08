from sqlalchemy import select

from app.copilot.db import models  # noqa: F401  (importing registers the tables)
from app.copilot.db.message_db import MessageBase, message_engine
from app.copilot.db.meta_db import MetaBase, MetaSession, meta_engine


def init_db() -> None:
    MetaBase.metadata.create_all(meta_engine)
    MessageBase.metadata.create_all(message_engine)
    _seed_dev_data()


def _seed_dev_data() -> None:
    with MetaSession() as db:
        if db.scalar(select(models.User).where(models.User.username == "dev")):
            return
        user = models.User(username="dev")
        team = models.Team(name="dev-team")
        db.add_all([user, team])
        db.flush()  # assigns the ids so we can link them
        db.add(models.TeamMember(team_id=team.id, user_id=user.id, role="owner"))
        db.commit()