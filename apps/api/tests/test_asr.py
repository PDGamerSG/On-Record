from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from wsw_brain.listen import FasterWhisperASR, FileASR


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, dict[str, object]]] = []

    def transcribe(self, samples: np.ndarray, **options: object):
        self.calls.append((samples, options))
        return (
            iter(
                [
                    SimpleNamespace(text=" Hello there ", avg_logprob=-0.1),
                    SimpleNamespace(text="", avg_logprob=-1.0),
                    SimpleNamespace(text=" team", avg_logprob=-0.3),
                ]
            ),
            SimpleNamespace(language="en"),
        )


def test_transcribe_joins_text_and_returns_bounded_confidence() -> None:
    model = FakeWhisperModel()
    asr = FasterWhisperASR(model=model, language="en")

    text, confidence = asr.transcribe(np.array([0.1, -0.2], dtype=np.float32))

    assert text == "Hello there team"
    assert confidence == pytest.approx((np.exp(-0.1) + np.exp(-0.3)) / 2)
    assert model.calls[0][1] == {"language": "en", "vad_filter": True}


def test_transcribe_does_not_load_or_call_model_for_empty_audio() -> None:
    model = FakeWhisperModel()
    asr = FasterWhisperASR(model=model)

    assert asr.transcribe(np.zeros(0, dtype=np.float32)) == ("", 0.0)
    assert model.calls == []


def test_model_is_loaded_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[dict[str, object]] = []
    model = FakeWhisperModel()

    class FakeWhisperModelFactory:
        def __init__(self, model_size: str, **options: object) -> None:
            loaded.append({"model_size": model_size, **options})

        def transcribe(self, samples: np.ndarray, **options: object):
            return model.transcribe(samples, **options)

    monkeypatch.setattr("faster_whisper.WhisperModel", FakeWhisperModelFactory)
    asr = FasterWhisperASR("tiny", device="cpu", compute_type="int8")
    assert loaded == []

    asr.transcribe(np.ones(4, dtype=np.float32))

    assert loaded == [{"model_size": "tiny", "device": "cpu", "compute_type": "int8"}]


def test_transcribe_file_decodes_audio_and_applies_duration_limit(tmp_path) -> None:
    model = FakeWhisperModel()
    asr = FasterWhisperASR(model=model)
    source = tmp_path / "meeting.wav"
    sf.write(source, np.zeros(16_000, dtype=np.float32), 16_000)

    text, confidence = asr.transcribe_file(source)

    assert text == "Hello there team"
    assert confidence == pytest.approx((np.exp(-0.1) + np.exp(-0.3)) / 2)
    assert model.calls[0][0].dtype == np.float32

    with pytest.raises(ValueError, match="limit"):
        asr.transcribe_file(source, max_duration_s=0.5)


def test_file_asr_contract_is_exported_from_listen_package() -> None:
    from wsw_brain.contracts import FileASR as ContractFileASR

    assert FileASR is ContractFileASR
