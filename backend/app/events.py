"""WebSocket fan-out: every change to a workspace is pushed to its open sockets."""
import asyncio
import json
import time
from typing import Dict, Optional, Set

from fastapi import WebSocket

_subscribers: Dict[int, Set[WebSocket]] = {}
_loop: Optional[asyncio.AbstractEventLoop] = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def subscribe(workspace_id: int, ws: WebSocket) -> None:
    _subscribers.setdefault(workspace_id, set()).add(ws)


def unsubscribe(workspace_id: int, ws: WebSocket) -> None:
    _subscribers.get(workspace_id, set()).discard(ws)


async def _broadcast(workspace_id: int, message: str) -> None:
    for ws in list(_subscribers.get(workspace_id, ())):
        try:
            await ws.send_text(message)
        except Exception:
            unsubscribe(workspace_id, ws)


def emit(workspace_id: int, event_type: str, **data) -> None:
    """Publish an event. Safe to call from request threads and from the event loop."""
    if not _subscribers.get(workspace_id) or _loop is None or _loop.is_closed():
        return
    message = json.dumps({"type": event_type, "workspace_id": workspace_id, "at": time.time(), **data})
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        _loop.create_task(_broadcast(workspace_id, message))
    else:
        asyncio.run_coroutine_threadsafe(_broadcast(workspace_id, message), _loop)
