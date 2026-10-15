from __future__ import annotations

import pytest
from pydantic import ValidationError

from wsw_brain.config import Settings


@pytest.mark.parametrize(
    ("field", "value"),
    [("WSW_EMBED_DIM", 0), ("WSW_EXTRACT_EVERY", 0), ("WSW_MAX_UTTERANCE_S", 0)],
)
def test_settings_reject_non_positive_runtime_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


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
