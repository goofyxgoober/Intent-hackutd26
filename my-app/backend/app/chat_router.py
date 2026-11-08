"""Top-level chat router module forwarding to app.copilot.chat_router."""
from app.copilot.chat_router import (
    WorkspaceContext,
    get_gate_reply,
    route_chat,
)

__all__ = ["route_chat", "get_gate_reply", "WorkspaceContext"]
