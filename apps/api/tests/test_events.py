from __future__ import annotations

import pytest

from wsw_brain.events import EventBus


def test_publish_rejects_invalid_event_payloads() -> None:
    bus = EventBus()

    for event_type, data, meeting_id, field, error_type in [
        ("", {}, None, "type", ValueError),
        (" ", {}, None, "type", ValueError),
        ("meeting.started", [], None, "data", TypeError),
        ("meeting.started", {}, " ", "meeting_id", ValueError),
    ]:
        try:
            bus.publish(event_type, data, meeting_id=meeting_id)  # type: ignore[arg-type]
        except error_type as exc:
            assert field in str(exc)
        else:
            raise AssertionError(f"publish should reject invalid {field}")


@pytest.mark.parametrize("since_id", [-1, True, "1"])
def test_subscribe_rejects_invalid_replay_cursors(since_id: object) -> None:
    with pytest.raises(ValueError, match="since_id"):
        EventBus().subscribe(since_id=since_id)  # type: ignore[arg-type]


def test_subscribe_rejects_blank_meeting_filters() -> None:
    with pytest.raises(ValueError, match="meeting_id"):
        EventBus().subscribe(meeting_id=" \t")


def test_subscribe_filters_replay_by_meeting() -> None:
    bus = EventBus()
    bus.publish("meeting.started", {"title": "One"}, meeting_id="m1")
    bus.publish("meeting.started", {"title": "Two"}, meeting_id="m2")

    queue = bus.subscribe(meeting_id="m1")

    assert queue.qsize() == 1
    assert queue.get_nowait()["meeting_id"] == "m1"


def test_subscribe_filters_live_events_and_unsubscribe() -> None:
    bus = EventBus()
    queue = bus.subscribe(meeting_id="m1")

    bus.publish("utterance.created", {"text": "first"}, meeting_id="m2")
    bus.publish("utterance.created", {"text": "second"}, meeting_id="m1")
    assert queue.get_nowait()["data"] == {"text": "second"}
    assert queue.empty()

    bus.unsubscribe(queue)
    bus.publish("utterance.created", {"text": "third"}, meeting_id="m1")
    assert queue.empty()


def test_unfiltered_subscriber_keeps_existing_all_events_behavior() -> None:
    bus = EventBus()
    queue = bus.subscribe()

    bus.publish("listener.status", {"state": "idle"})
    bus.publish("meeting.started", {"title": "One"}, meeting_id="m1")

    assert [queue.get_nowait()["type"], queue.get_nowait()["type"]] == ["listener.status", "meeting.started"]


def test_subscriber_filters_replay_after_an_event_id() -> None:
    bus = EventBus()
    first = bus.publish("meeting.started", {}, meeting_id="m1")
    bus.publish("utterance.created", {}, meeting_id="m1")
    bus.publish("utterance.created", {}, meeting_id="m2")

    queue = bus.subscribe(since_id=first["id"], meeting_id="m1")

    assert queue.qsize() == 1
    assert queue.get_nowait()["type"] == "utterance.created"


@pytest.mark.asyncio
async def test_subscription_context_replays_matching_events_and_cleans_up() -> None:
    bus = EventBus()
    bus.publish("meeting.started", {"title": "One"}, meeting_id="m1")
    bus.publish("meeting.started", {"title": "Two"}, meeting_id="m2")

    async with bus.subscription(meeting_id="m1") as subscription:
        assert subscription.queue.qsize() == 1
        assert subscription.queue.get_nowait()["meeting_id"] == "m1"

        subscription.close()
        subscription.close()
        bus.publish("utterance.created", {"text": "after close"}, meeting_id="m1")

    assert subscription.queue.empty()
    assert bus._subs == {}


def test_meeting_filter_handles_legacy_events_without_meeting_id() -> None:
    bus = EventBus()
    bus._replay.append({"id": 1, "type": "listener.status", "ts": 0.0, "data": {}})

    queue = bus.subscribe(meeting_id="m1")
    bus.publish("utterance.created", {}, meeting_id="m1")

    assert queue.qsize() == 1
    assert queue.get_nowait()["type"] == "utterance.created"


def test_subscribe_rejects_non_positive_replay_size() -> None:
    try:
        EventBus(replay=0)
    except ValueError as exc:
        assert "replay" in str(exc)
    else:
        raise AssertionError("EventBus should reject an empty replay buffer")


@pytest.mark.parametrize("queue_size", [0, -1])
def test_subscribe_rejects_non_positive_queue_size(queue_size: int) -> None:
    with pytest.raises(ValueError, match="queue_size"):
        EventBus(queue_size=queue_size)


def test_subscriber_queue_uses_configured_capacity_and_drops_slow_events() -> None:
    bus = EventBus(queue_size=1)
    queue = bus.subscribe()

    bus.publish("listener.status", {"state": "first"})
    bus.publish("listener.status", {"state": "second"})

    assert queue.maxsize == 1
    assert queue.qsize() == 1
    assert queue.get_nowait()["data"] == {"state": "first"}
