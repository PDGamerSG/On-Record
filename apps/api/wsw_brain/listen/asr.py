"""Model-backed automatic speech recognition adapters."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .audio import as_mono_float32, decode_file


class FasterWhisperASR:
    """ASR adapter for faster-whisper's local Whisper models.

    The model is loaded on the first non-empty transcription request, so importing the package and
    constructing the adapter never downloads weights or starts a model runtime. Tests and callers that
    manage a model themselves may pass it through ``model``.
    """

    def __init__(
        self,
        model_size_or_path: str = "small",
        *,
        device: str = "auto",
        compute_type: str = "default",
        language: str | None = None,
        vad_filter: bool = True,
        model: Any | None = None,
    ) -> None:
        if not model_size_or_path:
            raise ValueError("model_size_or_path must be a non-empty string")
        self.name = f"faster-whisper:{model_size_or_path}"
        self.model_size_or_path = model_size_or_path
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.vad_filter = vad_filter
        self._model = model

    def transcribe(self, samples: np.ndarray) -> tuple[str, float]:
        """Return ``(text, confidence)`` for 16 kHz mono float32 samples."""
        audio = as_mono_float32(samples)
        if audio.size == 0:
            return "", 0.0

        options: dict[str, object] = {"vad_filter": self.vad_filter}
        if self.language is not None:
            options["language"] = self.language
        segments, _info = self._get_model().transcribe(audio, **options)
        materialised = list(segments)
        text_parts: list[str] = []
        scores: list[float] = []
        for segment in materialised:
            part = segment.text.strip()
            if part:
                text_parts.append(part)
                scores.append(_segment_confidence(segment))
        text = " ".join(text_parts)
        confidence = float(np.mean(scores)) if scores else 0.0
        return text, confidence

    def transcribe_file(
        self, path: str | Path, *, max_duration_s: float | None = None
    ) -> tuple[str, float]:
        """Decode an audio file and transcribe it with the same ASR settings."""
        return self.transcribe(decode_file(path, max_duration_s=max_duration_s))

    def _get_model(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size_or_path,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model


def _segment_confidence(segment: Any) -> float:
    """Map average log probability to confidence; missing or invalid scores give zero."""
    try:
        logprob = float(getattr(segment, "avg_logprob", None))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(logprob):
        return 0.0
    return float(np.clip(math.exp(min(logprob, 0.0)), 0.0, 1.0))
