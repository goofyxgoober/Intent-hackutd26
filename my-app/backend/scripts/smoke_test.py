import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
for p in [str(_BACKEND_DIR), str(_REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import select

from app.copilot.db.init_db import init_db
from app.copilot.db.message_db import MessageSession
from app.copilot.db.meta_db import MetaSession
from app.copilot.db.models import User
from app.copilot.repositories import message_repo, session_repo

init_db()

with MetaSession() as meta, MessageSession() as msgs:
    user = meta.scalar(select(User).where(User.username == "dev"))
    team_id = session_repo.get_user_team_id(meta, user.id)

    s = session_repo.create_session(meta, team_id, user.id, title="smoke test")

    message_repo.append_messages(msgs, s.id, [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "agent_steps": ["step 1"]},
    ])
    session_repo.touch_session(meta, s.id, added_messages=2)

    print([(m.seq, m.role, m.content) for m in message_repo.load_recent(msgs, s.id)])
    print("message_count:", session_repo.get_session(meta, s.id).message_count)

