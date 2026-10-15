from __future__ import annotations

from wsw_brain.events import EventBus


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


def test_subscribe_rejects_non_positive_replay_size() -> None:
    try:
        EventBus(replay=0)
    except ValueError as exc:
        assert "replay" in str(exc)
    else:
        raise AssertionError("EventBus should reject an empty replay buffer")
