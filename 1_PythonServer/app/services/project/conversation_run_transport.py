from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from app.services.project.conversation_stream_checkpoints import (
    PERSISTENCE_CHECKPOINT_KIND,
)


DEFAULT_SUBSCRIBER_MAX_EVENTS = 1024
DEFAULT_SUBSCRIBER_MAX_CONTENT_UNITS = 8 * 1024 * 1024

StreamEvent: TypeAlias = dict[str, object | None]


class ConversationRunMailboxSignal(Enum):
    END = "end"
    RESYNC_REQUIRED = "resync_required"


StreamMailboxItem: TypeAlias = StreamEvent | ConversationRunMailboxSignal


@dataclass(slots=True)
class ConversationRunReplayBuffer:
    """Keep only the transient events that are not covered by the latest durable checkpoint."""

    _events: list[StreamEvent] = field(default_factory=list)
    _next_sequence: int = 1
    _checkpoint_message_id: str | None = None
    _checkpoint_sequence: int = 0
    _has_settled_event: bool = False
    _run_started_event: StreamEvent | None = None
    _pending_text_event: StreamEvent | None = None
    _pending_text_parts: list[str] = field(default_factory=list)

    def append(self, event: StreamEvent) -> StreamEvent:
        sequenced_event = {
            **event,
            "run_sequence": self._next_sequence,
        }
        self._next_sequence += 1

        if sequenced_event.get("kind") == "conversation_run_settled":
            self._has_settled_event = True
        if sequenced_event.get("kind") == "conversation_run_started":
            self._run_started_event = dict(sequenced_event)

        if _is_persistence_checkpoint(sequenced_event):
            checkpoint_message_id = sequenced_event.get("checkpoint_message_id")
            self._checkpoint_message_id = (
                checkpoint_message_id
                if isinstance(checkpoint_message_id, str)
                else None
            )
            self._checkpoint_sequence = _event_sequence(sequenced_event)
            self._events.clear()
            self._clear_pending_text_delta()
            return sequenced_event

        replay_event = dict(sequenced_event)
        if self._append_text_delta(replay_event):
            return sequenced_event
        self._flush_pending_text_delta()
        self._events.append(replay_event)
        return sequenced_event

    def matches_checkpoint(self, checkpoint_message_id: str | None) -> bool:
        return bool(
            checkpoint_message_id
            and checkpoint_message_id == self._checkpoint_message_id
        )

    def requires_reset(self, checkpoint_message_id: str | None) -> bool:
        if checkpoint_message_id:
            return not self.matches_checkpoint(checkpoint_message_id)
        return self._checkpoint_sequence > 0

    def replay_events(self) -> tuple[StreamEvent, ...]:
        events = [*self._events]
        pending_text_event = self._materialize_pending_text_delta()
        if pending_text_event is not None:
            events.append(pending_text_event)
        if self._run_started_event is None:
            return tuple(events)
        if events and events[0].get("kind") == "conversation_run_started":
            return tuple(events)
        return (self._run_started_event, *events)

    @property
    def has_settled_event(self) -> bool:
        return self._has_settled_event

    @property
    def checkpoint_sequence(self) -> int:
        return self._checkpoint_sequence

    def _append_text_delta(self, event: StreamEvent) -> bool:
        if event.get("kind") not in {"delta", "thinking_delta"}:
            return False
        content = event.get("content")
        if not isinstance(content, str):
            return False
        if (
            self._pending_text_event is None
            or self._pending_text_event.get("kind") != event.get("kind")
        ):
            self._flush_pending_text_delta()
            self._pending_text_event = {**event, "content": None}
        else:
            self._pending_text_event["run_sequence"] = event["run_sequence"]
        self._pending_text_parts.append(content)
        return True

    def _flush_pending_text_delta(self) -> None:
        event = self._materialize_pending_text_delta()
        if event is not None:
            self._events.append(event)
        self._clear_pending_text_delta()

    def _materialize_pending_text_delta(self) -> StreamEvent | None:
        if self._pending_text_event is None:
            return None
        return {
            **self._pending_text_event,
            "content": "".join(self._pending_text_parts),
        }

    def _clear_pending_text_delta(self) -> None:
        self._pending_text_event = None
        self._pending_text_parts.clear()


@dataclass(slots=True)
class ConversationRunMailbox:
    max_events: int = DEFAULT_SUBSCRIBER_MAX_EVENTS
    max_content_units: int = DEFAULT_SUBSCRIBER_MAX_CONTENT_UNITS
    _queue: asyncio.Queue[tuple[StreamMailboxItem, int]] = field(
        default_factory=asyncio.Queue,
    )
    _pending_content_units: int = 0

    async def get(self) -> StreamMailboxItem:
        item, content_units = await self._queue.get()
        self._pending_content_units = max(
            0,
            self._pending_content_units - content_units,
        )
        return item

    def can_accept_all(self, events: tuple[StreamEvent, ...]) -> bool:
        event_count = self._queue.qsize() + len(events)
        if event_count > self.max_events:
            return False
        content_units = self._pending_content_units + sum(
            estimate_stream_event_content_units(event)
            for event in events
        )
        if content_units <= self.max_content_units:
            return True
        return self._queue.empty() and len(events) == 1

    def try_put(self, item: StreamEvent) -> bool:
        content_units = estimate_stream_event_content_units(item)
        would_exceed_count = self._queue.qsize() >= self.max_events
        would_exceed_content = (
            self._pending_content_units + content_units > self.max_content_units
        )
        if would_exceed_count or (would_exceed_content and not self._queue.empty()):
            return False
        self._pending_content_units += content_units
        self._queue.put_nowait((item, content_units))
        return True

    def force_signal(self, signal: ConversationRunMailboxSignal) -> None:
        self.clear()
        self._queue.put_nowait((signal, 0))

    def append_signal(self, signal: ConversationRunMailboxSignal) -> None:
        self._queue.put_nowait((signal, 0))

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._pending_content_units = 0


def estimate_stream_event_content_units(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, dict):
        return sum(
            estimate_stream_event_content_units(key)
            + estimate_stream_event_content_units(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return sum(estimate_stream_event_content_units(item) for item in value)
    return 8


def _is_persistence_checkpoint(event: StreamEvent) -> bool:
    return event.get("kind") == PERSISTENCE_CHECKPOINT_KIND


def _event_sequence(event: StreamEvent) -> int:
    sequence = event.get("run_sequence")
    return sequence if isinstance(sequence, int) else 0
