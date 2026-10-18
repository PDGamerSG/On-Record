"""Listener models built from settings, loaded once and shared by every session."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import settings
from .speakers import OnlineClusterer, SherpaSpeakerEmbedder


def speaker_model_path() -> Path:
    """The configured speaker model; an absolute WSW_SPEAKER_MODEL wins over WSW_MODELS_DIR."""
    cfg = settings()
    return cfg.models_dir / cfg.speaker_model


def vad_model_path() -> Path:
    """The Silero VAD model that LiveSession loads unless it is given another path."""
    return settings().models_dir / "silero_vad.onnx"


@lru_cache(maxsize=1)
def get_speaker_embedder() -> SherpaSpeakerEmbedder:
    """The shared speaker embedder. Raises FileNotFoundError if the model file is missing."""
    return SherpaSpeakerEmbedder(speaker_model_path())


def speaker_clusterer(max_speakers: int = 8) -> OnlineClusterer:
    """A fresh clusterer for one meeting, matching voices at WSW_SPEAKER_THRESHOLD."""
    return OnlineClusterer(settings().speaker_threshold, max_speakers=max_speakers)
