"""Async background job registry and Server-Sent Events (SSE) bus."""
import asyncio
import time
from collections import deque
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from .models import EngineError, new_id


class Bus:
    """Pub/sub event bus supporting SSE streaming with ring buffer for reconnects."""

    def __init__(self, buffer_size: int = 200):
        self.subs: Dict[str, List[asyncio.Queue]] = {}
        self.buffer_size = buffer_size
        self.history: Dict[str, deque] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subs.setdefault(session_id, []).append(q)
        # Replay buffered events
        if session_id in self.history:
            for item in self.history[session_id]:
                q.put_nowait(item)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        if session_id in self.subs and q in self.subs[session_id]:
            self.subs[session_id].remove(q)

    def publish(self, session_id: str, event_type: str, data: Dict[str, Any]) -> None:
        item = (event_type, data)
        self.history.setdefault(session_id, deque(maxlen=self.buffer_size)).append(item)
        for q in self.subs.get(session_id, []):
            q.put_nowait(item)


class JobRecord:
    def __init__(self, job_id: str, kind: str, session_id: str):
        self.job_id = job_id
        self.kind = kind
        self.session_id = session_id
        self.status = "running"
        self.progress: Dict[str, Any] = {}
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.finished_at: Optional[float] = None


class Jobs:
    def __init__(self, bus: Bus):
        self.bus = bus
        self.jobs: Dict[str, JobRecord] = {}
        self.locks: Dict[str, str] = {}  # lock_key -> job_id

    def spawn(
        self,
        session_id: str,
        kind: str,
        coro_fn: Callable[[Callable[[str, int, int], None]], Coroutine[Any, Any, Any]],
        lock_key: Optional[str] = None,
    ) -> str:
        """Spawn an async background job with locking, progress, and SSE publishing."""
        if lock_key:
            active_job_id = self.locks.get(lock_key)
            if active_job_id and active_job_id in self.jobs and self.jobs[active_job_id].status == "running":
                raise EngineError(
                    "BUSY",
                    f"A job ({active_job_id}) is already active on resource {lock_key}",
                    hint="Wait for the running job to complete or check events.",
                )

        job_id = new_id("job")
        record = JobRecord(job_id, kind, session_id)
        self.jobs[job_id] = record
        if lock_key:
            self.locks[lock_key] = job_id

        async def runner():
            def report_progress(msg: str, done: int = 0, total: int = 1):
                record.progress = {"message": msg, "done": done, "total": total}
                self.bus.publish(
                    session_id,
                    "job.progress",
                    {"job_id": job_id, "kind": kind, "message": msg, "done": done, "total": total},
                )

            try:
                res = await coro_fn(report_progress)
                record.status = "completed"
                record.result = res
                record.finished_at = time.time()
                summary_text = res.get("summary", "Job completed successfully") if isinstance(res, dict) else str(res)
                self.bus.publish(
                    session_id,
                    "job.completed",
                    {"job_id": job_id, "kind": kind, "summary": summary_text, "result_ref": res},
                )
            except Exception as e:
                record.status = "failed"
                record.error = str(e)
                record.finished_at = time.time()
                self.bus.publish(
                    session_id,
                    "job.failed",
                    {"job_id": job_id, "kind": kind, "error": str(e)},
                )
            finally:
                if lock_key and self.locks.get(lock_key) == job_id:
                    del self.locks[lock_key]

        asyncio.create_task(runner())
        return job_id

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        r = self.jobs.get(job_id)
        if not r:
            return None
        return {
            "job_id": r.job_id,
            "kind": r.kind,
            "status": r.status,
            "progress": r.progress,
            "result": r.result,
            "error": r.error,
            "created_at": r.created_at,
            "finished_at": r.finished_at,
        }
