"""IngestPipeline with an in-memory graph store: batched writes, speaker merges, live extraction and ending."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from wsw_brain.brain.embed import HashEmbedder
from wsw_brain.brain.extract import Extractor
from wsw_brain.brain.llm import FakeLLM
from wsw_brain.contracts import ActionItemDraft, DecisionDraft, Insights, Utterance
from wsw_brain.ingest.pipeline import IngestPipeline, _MeetingRecords, _same_owner

LINES = [
    ("S1", "Let's start with the pricing review for the Pro plan."),
    ("S2", "I think twenty dollars a month is too low for the Pro plan."),
    ("S1", "Agreed, we decided to price the Pro plan at twenty five dollars a month."),
    ("S1", "I'll send the updated pricing deck to the sales team by Friday."),
]


def _utterance(seq: int, speaker: str | None = None, text: str | None = None) -> Utterance:
    track, line = LINES[seq % len(LINES)]
    return Utterance(
        meeting_id="m1",
        seq=seq,
        speaker=speaker or track,
        t_start=seq * 6.0,
        t_end=seq * 6.0 + 5.0,
        text=text or line,
        confidence=0.9,
    )


class FakeStore:
    """The GraphStore methods the pipeline calls, kept in memory, with every write recorded in `calls`."""

    def __init__(self) -> None:
        self.meeting = {
            "id": "m1",
            "title": "Pricing review",
            "status": "live",
            "duration_s": 0.0,
            "summary": None,
        }
        self.speakers = [
            {"track": "S1", "label": "Speaker 1", "name": "Priya"},
            {"track": "S2", "label": "Speaker 2", "name": "Rahul"},
        ]
        self.utterances: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []
        self.calls: list[tuple[Any, ...]] = []

    def write_utterances(
        self, utterances: list[Utterance], embeddings: list[list[float]] | None
    ) -> dict[str, Any]:
        self.calls.append(("write", [u.seq for u in utterances], embeddings is not None))
        for u in utterances:
            self.utterances.append(
                {"id": u.id, "meeting_id": u.meeting_id, "seq": u.seq, "speaker": u.speaker, "speaker_name": None,
                 "t_start": u.t_start, "t_end": u.t_end, "text": u.text, "confidence": u.confidence}
            )  # fmt: skip
        return {"written": len(utterances), "ms": 1.0}

    def merge_speakers(self, meeting_id: str, src: str, dst: str) -> int:
        self.calls.append(("merge", src, dst))
        moved = [u for u in self.utterances if u["speaker"] == src]
        for u in moved:
            u["speaker"] = dst
        return len(moved)

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        if meeting_id != "m1":
            return None
        return {
            "meeting": dict(self.meeting),
            "speakers": self.speakers,
            "utterances": sorted(self.utterances, key=lambda u: u["seq"]),
            "decisions": list(self.decisions),
            "action_items": list(self.items),
            "topics": [],
        }

    def list_meetings(self) -> list[dict[str, Any]]:
        return [dict(self.meeting)]

    def list_decisions(self, meeting_id: str | None = None) -> list[dict[str, Any]]:
        return list(reversed(self.decisions))

    def write_insights(self, meeting_id: str, insights: Insights) -> dict[str, list[dict[str, Any]]]:
        self.calls.append(("insights", len(insights.decisions), len(insights.action_items)))
        decisions = [{"text": d.text, "evidence": d.evidence, "status": "active"} for d in insights.decisions]
        items = [
            {"text": i.text, "evidence": i.evidence, "owner": i.owner, "owner_track": i.owner, "due": i.due}
            for i in insights.action_items
        ]
        self.decisions.extend(decisions)
        self.items.extend(items)
        return {
            "decisions": decisions,
            "action_items": items,
            "topics": [{"name": t} for t in insights.topics],
        }

    def end_meeting(self, meeting_id: str, ended_at_ms: int, duration_s: float) -> dict[str, Any] | None:
        self.calls.append(("end", duration_s))
        self.meeting.update(status="ended", ended_at=ended_at_ms, duration_s=duration_s)
        return dict(self.meeting)

    def set_meeting_summary(self, meeting_id: str, summary: str) -> None:
        self.meeting["summary"] = summary

    def stats(self) -> dict[str, int]:
        return {"Utterance": len(self.utterances)}


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any], str | None]] = []

    def publish(self, type_: str, data: dict[str, Any], meeting_id: str | None = None) -> dict[str, Any]:
        self.events.append((type_, data, meeting_id))
        return {"type": type_, "data": data}

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [data for kind, data, _ in self.events if kind == type_]


class FailingEmbedder(HashEmbedder):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding model unavailable")


def _pipeline(
    store: FakeStore, bus: RecordingBus, *, extract_every: int = 100, embedder: Any = None, **kwargs: Any
):
    pipeline = IngestPipeline(
        store,  # type: ignore[arg-type]
        embedder or HashEmbedder(8),
        Extractor(FakeLLM()),
        bus,  # type: ignore[arg-type]
        SimpleNamespace(extract_every=extract_every),  # type: ignore[arg-type]
        flush_interval_s=0.05,
        **kwargs,
    )
    pipeline.start(asyncio.get_running_loop())
    pipeline.begin_meeting("m1")
    return pipeline


async def _until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_writer_batches_embeds_and_publishes_utterances() -> None:
    store, bus = FakeStore(), RecordingBus()
    pipeline = _pipeline(store, bus, batch_size=2)
    pipeline.speaker_named("m1", "S1", "Priya")
    for seq in range(3):
        pipeline.submit(_utterance(seq))
    assert await asyncio.to_thread(pipeline.flush, 5)
    await pipeline.aclose()

    assert store.calls == [("write", [0, 1], True), ("write", [2], True)]
    created = bus.of("utterance.created")
    assert [u["seq"] for u in created] == [0, 1, 2]
    assert created[0]["id"] == "m1:u00000" and created[0]["speaker_name"] == "Priya"
    assert created[1]["speaker_name"] is None  # S2 was not named through this pipeline
    writes = bus.of("graph.write")
    assert [w["utterances"] for w in writes] == [2, 1] and writes[0]["totals"] == {"Utterance": 2}
    assert pipeline.next_seq("m1") == 3


@pytest.mark.asyncio
async def test_a_speaker_merge_waits_for_the_utterances_queued_before_it() -> None:
    store, bus = FakeStore(), RecordingBus()
    pipeline = _pipeline(store, bus)
    pipeline.speaker_named("m1", "S2", "Rahul")
    pipeline.submit(_utterance(0, speaker="S2"))
    pipeline.speaker_merged("m1", "S2", "S1")
    pipeline.submit(_utterance(1, speaker="S1"))
    assert await asyncio.to_thread(pipeline.flush, 5)
    await pipeline.aclose()

    assert store.calls == [("write", [0], True), ("merge", "S2", "S1"), ("write", [1], True)]
    assert bus.of("speaker.merged") == [{"from": "S2", "to": "S1"}]
    assert bus.of("utterance.created")[1]["speaker_name"] == "Rahul"  # the name moved with the track


@pytest.mark.asyncio
async def test_utterances_are_kept_when_embedding_fails() -> None:
    store, bus = FakeStore(), RecordingBus()
    pipeline = _pipeline(store, bus, embedder=FailingEmbedder(8))
    pipeline.submit(_utterance(0))
    assert await asyncio.to_thread(pipeline.flush, 5)
    await pipeline.aclose()
    assert store.calls == [("write", [0], False)]
    assert len(bus.of("utterance.created")) == 1


@pytest.mark.asyncio
async def test_live_extraction_runs_every_extract_every_utterances() -> None:
    store, bus = FakeStore(), RecordingBus()
    pipeline = _pipeline(store, bus, extract_every=4)
    for seq in range(3):
        pipeline.submit(_utterance(seq))
    assert await asyncio.to_thread(pipeline.flush, 5)
    await asyncio.sleep(0.1)
    assert bus.of("insight.created") == []  # three new utterances: below extract_every
    pipeline.submit(_utterance(3))
    await _until(lambda: bus.of("insight.created"))
    await pipeline.aclose()

    events = bus.of("insight.created")
    kinds = {(e["kind"], e["item"].get("text") or e["item"].get("name")) for e in events}
    assert ("decision", "Agreed, we decided to price the Pro plan at twenty five dollars a month") in kinds
    assert any(kind == "action_item" for kind, _ in kinds)
    assert {e["by"]["provider"] for e in events} == {"heuristic"}


@pytest.mark.asyncio
async def test_ending_a_meeting_runs_the_final_extraction_and_the_summary() -> None:
    store, bus = FakeStore(), RecordingBus()
    pipeline = _pipeline(store, bus)
    for seq in range(4):
        pipeline.submit(_utterance(seq))

    meeting = await pipeline.end_meeting("m1", 10.0, wait_final=True, ended_at_ms=5_000)
    await pipeline.aclose()

    assert ("end", 23.0) in store.calls  # the last utterance ended at 23 s, later than the 10 s passed in
    assert meeting is not None and meeting["status"] == "ended" and meeting["summary"]
    assert "Priya" in meeting["summary"] and store.decisions and store.items
    ended = bus.of("meeting.ended")
    assert len(ended) == 2 and ended[0]["summary"] is None and ended[1]["summary"] == meeting["summary"]
    assert await pipeline.end_meeting("m1") == meeting  # idempotent
    assert len(bus.of("meeting.ended")) == 2


@pytest.mark.asyncio
async def test_a_forgotten_meeting_drops_queued_utterances() -> None:
    store, bus = FakeStore(), RecordingBus()
    pipeline = _pipeline(store, bus)
    pipeline.forget("m1")
    pipeline.submit(_utterance(0))
    assert await asyncio.to_thread(pipeline.flush, 5)
    assert await pipeline.end_meeting("m1") is None
    await pipeline.aclose()
    assert store.calls == [] and bus.of("utterance.created") == []


def test_overlapping_windows_do_not_repeat_insights() -> None:
    held = _MeetingRecords.from_detail(
        {
            "speakers": [{"track": "S3", "label": "Speaker 3", "name": "Meera"}],
            "decisions": [
                {"text": "The annual discount will be 15% and reviewed after 90 days of real data.",
                 "status": "active", "evidence": ["m:u00001"]},
            ],
            "action_items": [
                {"text": "Meera will send the revised deck to Saffron Basket by Thursday.", "owner": "Meera",
                 "owner_track": "S3", "evidence": ["m:u00003"]},
            ],
        }
    )  # fmt: skip
    insights = Insights(
        decisions=[
            DecisionDraft("The annual discount is 15%.", ["m:u00009"]),  # restates a held decision
            DecisionDraft("Starter costs 4,999 rupees a month.", ["m:u00002"]),  # missed before: kept
            DecisionDraft("Self-serve launches on Monday, November 2.", ["m:u00010"]),
            DecisionDraft("Self-serve launches Monday November 2!", ["m:u00011"]),  # repeats the one above
        ],
        action_items=[
            ActionItemDraft("Send the revised deck to Saffron Basket by Thursday.", ["m:u00010"], owner="S3"),
            ActionItemDraft("Meera sends the deck over to Saffron", ["m:u00003"], owner="Meera"),  # context
            ActionItemDraft("Send the revised deck to Saffron Basket by Thursday.", ["m:u00010"], owner="S2"),
            ActionItemDraft("Rahul sets up the Razorpay plans.", [], owner="S2", due="Wednesday"),
        ],
        topics=["pricing"],
    )
    kept, dropped = held.admit(insights, {"m:u00009", "m:u00010", "m:u00011"})
    assert [d.text[:12] for d in kept.decisions] == ["Starter cost", "Self-serve l"]
    assert [(i.owner, i.text[:8]) for i in kept.action_items] == [("S2", "Send the"), ("S2", "Rahul se")]
    assert dropped == 4 and kept.topics == ["pricing"]

    # While speakers are unnamed, "Priya" and "Speaker 1" may be the same person: compared, and repeats.
    unnamed = _MeetingRecords.from_detail(
        {
            "speakers": [{"track": "S1", "label": "Speaker 1", "name": None}],
            "decisions": [],
            "action_items": [
                {"text": "Speaker 1 will draft the pricing page and the FAQ by Monday.", "owner": "Speaker 1",
                 "owner_track": "S1", "evidence": ["m:u00001"]},
            ],
        }
    )  # fmt: skip
    later = Insights(
        action_items=[ActionItemDraft("Priya has the pricing page by Monday.", ["m:u00009"], "Priya")]
    )
    assert unnamed.admit(later, {"m:u00009"})[1] == 1
    assert _same_owner("S2", {"owner": "Meera", "owner_track": "S3"}) is False
    assert _same_owner("Meera", {"owner": "Rahul", "owner_track": "S2"}) is False
    assert _same_owner("Priya", {"owner": "Priya Sharma", "owner_track": None}) is True
