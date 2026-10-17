from __future__ import annotations

import json
from dataclasses import replace

import pytest

from wsw_brain.contracts import ActionItemDraft, DecisionDraft, FileASR, Insights, Utterance
from wsw_brain.listen import FasterWhisperASR


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meeting_id", ""),
        ("meeting_id", " \t"),
        ("meeting_id", None),
        ("speaker", ""),
        ("speaker", " \t"),
        ("speaker", None),
        ("seq", -1),
        ("seq", 1.5),
        ("seq", True),
        ("seq", "1"),
        ("t_start", -0.1),
        ("t_start", float("nan")),
        ("t_start", float("inf")),
        ("t_start", "0"),
        ("t_start", True),
        ("t_end", 0.5),
        ("t_end", float("nan")),
        ("t_end", float("inf")),
        ("t_end", None),
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("confidence", float("nan")),
        ("confidence", float("inf")),
        ("confidence", "0.9"),
        ("confidence", True),
    ],
)
def test_utterance_rejects_invalid_contract_fields(field: str, value: object) -> None:
    fields = {
        "meeting_id": "m1",
        "seq": 0,
        "speaker": "S1",
        "t_start": 1.0,
        "t_end": 2.0,
        "text": "Meeting starts now.",
        "confidence": 0.9,
    }
    fields[field] = value

    with pytest.raises(ValueError, match=field):
        Utterance(**fields)


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_utterance_accepts_zero_duration_and_confidence_boundaries(confidence: float) -> None:
    utterance = Utterance("m1", 0, "S1", 0, 0, "", confidence)

    assert utterance.to_dict() == {
        "id": "m1:u00000",
        "meeting_id": "m1",
        "seq": 0,
        "speaker": "S1",
        "t_start": 0,
        "t_end": 0,
        "text": "",
        "confidence": confidence,
    }


def test_valid_utterance_keeps_serialization_and_sequence_replacement() -> None:
    utterance = Utterance("meeting-1", 12, "S2", 1.25, 3.5, "Hello, team.")

    assert json.loads(json.dumps(utterance.to_dict(), allow_nan=False)) == {
        "id": "meeting-1:u00012",
        "meeting_id": "meeting-1",
        "seq": 12,
        "speaker": "S2",
        "t_start": 1.25,
        "t_end": 3.5,
        "text": "Hello, team.",
        "confidence": 1.0,
    }
    assert replace(utterance, seq=13).id == "meeting-1:u00013"


def test_file_asr_contract_matches_file_transcription_adapter() -> None:
    adapter = FasterWhisperASR(model=object())

    assert isinstance(adapter, FileASR)


@pytest.mark.parametrize("draft", [DecisionDraft, ActionItemDraft])
def test_insight_drafts_reject_blank_text(draft: type[DecisionDraft | ActionItemDraft]) -> None:
    with pytest.raises(ValueError, match="text"):
        draft(" \t", [])


def test_decision_draft_rejects_malformed_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        DecisionDraft("Ship the release", ["m1:u0001", " "])

    with pytest.raises(ValueError, match="evidence"):
        DecisionDraft("Ship the release", "m1:u0001")  # type: ignore[arg-type]


def test_decision_draft_rejects_blank_optional_fields() -> None:
    with pytest.raises(ValueError, match="proposed_by"):
        DecisionDraft("Ship the release", [], proposed_by=" \t")

    with pytest.raises(ValueError, match="supersedes_text"):
        DecisionDraft("Ship the release", [], supersedes_text=" \t")


def test_action_item_draft_rejects_blank_optional_fields() -> None:
    with pytest.raises(ValueError, match="owner"):
        ActionItemDraft("Send the notes", [], owner=" \t")

    with pytest.raises(ValueError, match="due"):
        ActionItemDraft("Send the notes", [], due=" \t")


def test_insights_rejects_invalid_collection_types() -> None:
    with pytest.raises(ValueError, match="decisions"):
        Insights(decisions=None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="action_items"):
        Insights(action_items=["send notes"])  # type: ignore[list-item]


def test_insights_rejects_blank_topics() -> None:
    with pytest.raises(ValueError, match="topics"):
        Insights(topics=[" "])
