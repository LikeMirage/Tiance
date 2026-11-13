"""Live execution facts, owned by the run manager, independent of stored messages.

No inactivity deadline: an upstream wait and cancellation settlement are both busy.
The event feed carries identities/counters only, never bodies or list invalidations.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from threading import Lock


@dataclass(frozen=True)
class ConversationRuntime:
    project_id: str
    session_id: str
    run_id: str
    phase: str = "running"
    output_seq: int = 0

    def payload(self):
        return vars(self).copy()


class ConversationRuntimeRegistry:
    def __init__(self):
        self._lock = Lock()
        self._active: dict[tuple[str, str], ConversationRuntime] = {}
        self._subscribers: dict[asyncio.Queue, tuple[asyncio.AbstractEventLoop, dict]] = {}

    def is_running(self, project_id: str, session_id: str) -> bool:
        with self._lock:
            return (project_id, session_id) in self._active

    def project_states(self, project_id: str, states: dict):
        with self._lock:
            active_ids = {sid for pid, sid in self._active if pid == project_id}
        return {
            sid: replace(state, runtime_status=(
                "running" if sid in active_ids else
                "idle" if state.runtime_status == "running" else state.runtime_status
            ))
            for sid, state in states.items()
        }

    def start(self, project_id: str, session_id: str, run_id: str):
        with self._lock:
            state = ConversationRuntime(project_id, session_id, run_id)
            self._active[(project_id, session_id)] = state
            self._publish_locked(state)

    def update(self, project_id: str, session_id: str, run_id: str, *,
               stopping: bool = False, output: bool = False, outcome: str | None = None):
        with self._lock:
            key = (project_id, session_id)
            current = self._active.get(key)
            if current is None or current.run_id != run_id:
                return
            state = replace(current,
                phase=outcome or ("stopping" if stopping else current.phase),
                output_seq=current.output_seq + int(output and current.phase == "running"))
            if outcome:
                del self._active[key]
            else:
                self._active[key] = state
            self._publish_locked(state)

    def _publish_locked(self, state):
        for queue, (loop, pending) in self._subscribers.items():
            needs_signal = not pending
            pending[(state.project_id, state.session_id)] = state.payload()
            # A stalled subscriber reconciles from a snapshot instead of retaining
            # an unbounded history of completed runs.
            if len(pending) > 512:
                pending.clear()
                pending[None] = None
            if needs_signal:
                try:
                    loop.call_soon_threadsafe(self._signal, queue)
                except RuntimeError:
                    # A closing observer must never break task execution/settlement.
                    pass

    @staticmethod
    def _signal(queue):
        if queue.empty():
            queue.put_nowait(True)

    async def events(self):
        queue = asyncio.Queue(maxsize=1)
        pending = {}
        with self._lock:
            self._subscribers[queue] = (asyncio.get_running_loop(), pending)
            initial = [state.payload() for state in self._active.values()]
        try:
            yield {"kind": "snapshot", "runs": initial}
            while True:
                await queue.get()
                # Coalesce output notifications; this delay never changes liveness.
                await asyncio.sleep(0.1)
                with self._lock:
                    reset = None in pending
                    runs = ([state.payload() for state in self._active.values()]
                            if reset else list(pending.values()))
                    pending.clear()
                yield {"kind": "snapshot" if reset else "changed", "runs": runs}
        finally:
            with self._lock:
                self._subscribers.pop(queue, None)


conversation_runtime = ConversationRuntimeRegistry()
