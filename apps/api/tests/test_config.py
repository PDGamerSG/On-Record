from __future__ import annotations

import pytest
from pydantic import ValidationError

from wsw_brain.config import Settings


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("WSW_EMBED_DIM", 0),
        ("WSW_EXTRACT_EVERY", 0),
        ("WSW_MAX_UTTERANCE_S", 0),
        ("WSW_MODEL_SLOTS", 0),
        ("WSW_MODEL_MAX_WAITING", -1),
        ("WSW_MODEL_QUEUE_WAIT_S", 0),
    ],
)
def test_settings_reject_non_positive_runtime_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_settings_expose_model_queue_limits() -> None:
    configured = Settings(
        WSW_MODEL_SLOTS=3,
        WSW_MODEL_MAX_WAITING=12,
        WSW_MODEL_QUEUE_WAIT_S=45,
    )

    assert configured.model_slots == 3
    assert configured.model_max_waiting == 12
    assert configured.model_queue_wait_s == 45


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_settings_reject_speaker_threshold_outside_probability_range(value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(WSW_SPEAKER_THRESHOLD=value)


def test_settings_accept_probability_boundaries() -> None:
    assert Settings(WSW_SPEAKER_THRESHOLD=0).speaker_threshold == 0
    assert Settings(WSW_SPEAKER_THRESHOLD=1).speaker_threshold == 1


@pytest.mark.parametrize("field", ["WSW_FALKORDB_URL", "WSW_GRAPH"])
def test_settings_reject_empty_storage_identifiers(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: ""})
