"""In-process event bus. Writers publish; the SSE endpoint fans events out to browsers.

Event shape (JSON): {"id": int, "type": str, "meeting_id": str | None, "ts": float, "data": {...}}

Types:
  meeting.started   data: MeetingSummary
  meeting.ended     data: MeetingSummary
  utterance.created data: Utterance (graph dict, see contracts.UtteranceOut)
  speaker.merged    data: {"from": track, "to": track}
  speaker.named     data: {"track": str, "name": str, "person_id": str}
  insight.created   data: {"kind": "decision" | "action_item" | "topic", "item": {...}}
  action.updated    data: ActionItem dict
  graph.write       data: {"utterances": int, "ms": float, "totals": {label: count}}
  listener.status   data: {"state": "listening" | "processing" | "idle" | "error", "lag_s": float, "detail": str}
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections import deque
from types import TracebackType
from typing import Any, Self


class EventSubscription:
    """Own one event queue and remove it safely when the consumer disconnects."""

    def __init__(self, bus: EventBus, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._bus = bus
        self.queue = queue
        self._closed = False

    def close(self) -> None:
        """Detach this subscription; repeated cleanup calls are harmless."""
        if not self._closed:
            self._bus.unsubscribe(self.queue)
            self._closed = True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.close()


class EventBus:
    """Fans events out to subscribers (one per SSE connection).

    The last `replay` events (500) are kept, so a reconnecting browser can resume after the last id it saw.
    Each subscriber gets a queue of `queue_size` events (2000; keep it above `replay`, which is copied in on
    subscribe). A full queue drops new events, and that client re-syncs over REST.

    publish() can be called from any thread once bind_loop() has the server's event loop; the SSE endpoint
    (routes/event_stream.py) binds it when a browser connects. publish() then delivers on that loop, directly when
    already on it or with call_soon_threadsafe from another thread, because asyncio queues are not
    thread-safe. Without a running bound loop it delivers in the calling thread, which suits tests and
    scripts.
    """

    def __init__(self, replay: int = 500, queue_size: int = 2000) -> None:
        if replay <= 0:
            raise ValueError("replay must be positive")
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self.queue_size = queue_size
        self._subs: dict[asyncio.Queue[dict[str, Any]], str | None] = {}
        self._ids = itertools.count(1)
        self._replay: deque[dict[str, Any]] = deque(maxlen=replay)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Deliver events on this loop from now on (see the class docstring)."""
        self._loop = loop

    def publish(self, type_: str, data: dict[str, Any], meeting_id: str | None = None) -> dict[str, Any]:
        """Thread-safe: may be called from listener worker threads."""
        _require_non_empty_text(type_, "event type")
        if not isinstance(data, dict):
            raise TypeError("event data must be a dictionary")
        if meeting_id is not None:
            _require_non_empty_text(meeting_id, "meeting_id")
        event = {"id": next(self._ids), "type": type_, "meeting_id": meeting_id, "ts": time.time(), "data": data}
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                self._fanout(event)
            else:
                loop.call_soon_threadsafe(self._fanout, event)
        else:
            self._fanout(event)
        return event

    def _fanout(self, event: dict[str, Any]) -> None:
        self._replay.append(event)
        for q, meeting_id in list(self._subs.items()):
            if meeting_id is not None and event.get("meeting_id") != meeting_id:
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer: drop; the client re-syncs over REST

    def subscribe(self, since_id: int = 0, meeting_id: str | None = None) -> asyncio.Queue[dict[str, Any]]:
        """A queue that first gets the kept events with id > since_id, then every new one. meeting_id limits
        it to that meeting's events. Pair with unsubscribe(), or use subscription(), which does it for you."""
        if isinstance(since_id, bool) or not isinstance(since_id, int) or since_id < 0:
            raise ValueError("since_id must be a non-negative int")
        if meeting_id is not None:
            _require_non_empty_text(meeting_id, "meeting_id")
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        for e in self._replay:
            if e["id"] > since_id and (meeting_id is None or e.get("meeting_id") == meeting_id):
                q.put_nowait(e)
        self._subs[q] = meeting_id
        return q

    def subscription(self, since_id: int = 0, meeting_id: str | None = None) -> EventSubscription:
        """Create a queue subscription that can be cleaned up with an async context manager."""
        return EventSubscription(self, self.subscribe(since_id=since_id, meeting_id=meeting_id))

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Stop delivering to this queue; an unknown queue is ignored."""
        self._subs.pop(q, None)


bus = EventBus()


def _require_non_empty_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
