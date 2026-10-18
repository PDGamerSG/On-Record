"""Server-sent event streaming for the in-process event bus."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .events import EventBus, EventSubscription

router = APIRouter()


def format_sse(event: dict[str, Any]) -> str:
    """Encode one event as a standards-compliant SSE frame."""
    payload = json.dumps(event["data"], ensure_ascii=False, separators=(",", ":"))
    return f'id: {event["id"]}\nevent: {event["type"]}\ndata: {payload}\n\n'


async def _event_stream(request: Request, subscription: EventSubscription) -> AsyncIterator[str]:
    """Yield queued events until the client disconnects, then clean up."""
    try:
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(subscription.queue.get(), timeout=15)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield format_sse(event)
    finally:
        subscription.close()


@router.get("/api/events", response_class=StreamingResponse)
async def events(
    request: Request,
    since_id: int = Query(default=0, ge=0),
    meeting_id: str | None = Query(default=None),
) -> StreamingResponse:
    """Stream replayed and newly published events as server-sent events."""
    event_bus: EventBus = request.app.state.event_bus
    event_bus.bind_loop(asyncio.get_running_loop())
    try:
        subscription = event_bus.subscription(since_id=since_id, meeting_id=meeting_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return StreamingResponse(
        _event_stream(request, subscription),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
