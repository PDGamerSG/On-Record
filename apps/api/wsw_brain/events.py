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
from typing import Any


class EventBus:
    def __init__(self, replay: int = 500) -> None:
        if replay <= 0:
            raise ValueError("replay must be positive")
        self._subs: dict[asyncio.Queue[dict[str, Any]], str | None] = {}
        self._ids = itertools.count(1)
        self._replay: deque[dict[str, Any]] = deque(maxlen=replay)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type_: str, data: dict[str, Any], meeting_id: str | None = None) -> dict[str, Any]:
        """Thread-safe: may be called from listener worker threads."""
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
            if meeting_id is not None and event["meeting_id"] != meeting_id:
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer: drop; the client re-syncs over REST

    def subscribe(self, since_id: int = 0, meeting_id: str | None = None) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        for e in self._replay:
            if e["id"] > since_id and (meeting_id is None or e["meeting_id"] == meeting_id):
                q.put_nowait(e)
        self._subs[q] = meeting_id
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.pop(q, None)


bus = EventBus()
