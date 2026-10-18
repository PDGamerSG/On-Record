import pytest
from fastapi.testclient import TestClient

from wsw_brain.app import create_app
from wsw_brain.event_stream import events
from wsw_brain.events import EventBus


def test_health_endpoint_returns_without_external_services() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_endpoint_exposes_product_identity() -> None:
    client = TestClient(create_app())

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "product": "On Record"}


def _request(app: object) -> object:
    """Build a request scope for consuming one frame without buffering forever."""
    from starlette.requests import Request

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/events",
            "raw_path": b"/api/events",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "app": app,
        },
        receive,
    )


@pytest.mark.asyncio
async def test_events_endpoint_replays_events_as_sse_frames() -> None:
    event_bus = EventBus()
    event = event_bus.publish("meeting.started", {"title": "Planning"}, meeting_id="meeting-1")

    response = await events(_request(create_app(event_bus=event_bus)), since_id=0, meeting_id=None)
    frame = await anext(response.body_iterator)
    await response.body_iterator.aclose()

    assert response.media_type == "text/event-stream"
    assert frame == (
        f'id: {event["id"]}\n'
        "event: meeting.started\n"
        'data: {"title":"Planning"}\n\n'
    )


@pytest.mark.asyncio
async def test_events_endpoint_applies_cursor_and_meeting_filter() -> None:
    event_bus = EventBus()
    first = event_bus.publish("meeting.started", {"title": "One"}, meeting_id="meeting-1")
    event_bus.publish("meeting.started", {"title": "Other"}, meeting_id="meeting-2")
    matching = event_bus.publish("meeting.ended", {"title": "One"}, meeting_id="meeting-1")

    response = await events(
        _request(create_app(event_bus=event_bus)), since_id=first["id"], meeting_id="meeting-1"
    )
    frame = await anext(response.body_iterator)
    await response.body_iterator.aclose()

    assert f'id: {matching["id"]}' in frame
    assert "event: meeting.ended" in frame
    assert 'data: {"title":"One"}' in frame


def test_events_endpoint_rejects_invalid_cursor_and_filter() -> None:
    event_bus = EventBus()
    with TestClient(create_app(event_bus=event_bus)) as client:
        assert client.get("/api/events?since_id=-1").status_code == 422
        assert client.get("/api/events?meeting_id=%20").status_code == 422
