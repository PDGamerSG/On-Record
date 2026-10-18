"""Sarvam Saaras speech recognition for Indian-language and code-mixed (e.g. Hinglish) meetings.

`SaarasASR` implements the same ASR contract as FasterWhisperASR: 16 kHz mono float32 in,
`(text, confidence)` out. Listener utterances are short, so each call uses the synchronous REST API,
which accepts up to 30 seconds; longer audio is transcribed in consecutive windows.

Saaras returns no transcript confidence. The reported confidence is its language-identification
probability (`language_probability`), which drops for unclear or off-language audio.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import httpx
import numpy as np
import soundfile as sf

from ..contracts import SAMPLE_RATE
from .audio import as_mono_float32, decode_file

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger(__name__)

REST_MAX_S = 30.0
WINDOW_S = 28.0  # stay under the REST limit after container overhead
Mode = Literal["transcribe", "translate", "verbatim", "translit", "codemix"]
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)


class SarvamASRError(RuntimeError):
    """A Saaras request failed or returned an unusable response."""


class SaarasASR:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "saaras:v4",
        mode: Mode = "transcribe",
        language: str | None = None,
        keyterms: list[str] | None = None,
        base_url: str = "https://api.sarvam.ai",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """`language` is a code such as "hi-IN"; None lets Saaras detect it. `keyterms` (Saaras v4)
        bias recognition toward names and terms, e.g. the speakers and products of a meeting."""
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("a Sarvam API key is required (set SARVAM_API_KEY)")
        self.name = f"sarvam:{model}"
        self.model = model
        self.mode = mode
        self.language = language
        self.keyterms = [k for k in (keyterms or []) if isinstance(k, str) and k.strip()][:50]
        self.url = f"{base_url.rstrip('/')}/speech-to-text"
        self._headers = {"api-subscription-key": api_key.strip()}
        self._transport = transport
        self.last_language: str | None = None

    @classmethod
    def from_settings(cls, s: Settings, keyterms: list[str] | None = None) -> SaarasASR:
        if not s.sarvam_api_key:
            raise ValueError("Saaras needs SARVAM_API_KEY")
        language = None if s.sarvam_asr_language in ("", "auto", "unknown") else s.sarvam_asr_language
        return cls(s.sarvam_api_key, model=s.sarvam_asr_model, mode=s.sarvam_asr_mode, language=language,
                   keyterms=keyterms, base_url=s.sarvam_base_url)

    def transcribe(self, samples: np.ndarray) -> tuple[str, float]:
        """Return `(text, confidence)` for 16 kHz mono float32 samples; silence-only input gives ("", 0.0)."""
        audio = as_mono_float32(samples)
        if audio.size == 0 or not np.any(np.abs(audio) > 1e-4):
            return "", 0.0
        window = int(WINDOW_S * SAMPLE_RATE)
        texts: list[str] = []
        scores: list[float] = []
        with httpx.Client(timeout=_TIMEOUT, transport=self._transport) as client:
            for start in range(0, audio.size, window):
                text, score = self._request(client, audio[start:start + window])
                if text:
                    texts.append(text)
                    scores.append(score)
        return " ".join(texts), float(np.mean(scores)) if scores else 0.0

    def transcribe_file(self, path: str | Path, *, max_duration_s: float | None = None) -> tuple[str, float]:
        return self.transcribe(decode_file(path, max_duration_s=max_duration_s))

    def _request(self, client: httpx.Client, audio: np.ndarray) -> tuple[str, float]:
        buffer = io.BytesIO()
        sf.write(buffer, audio, SAMPLE_RATE, subtype="PCM_16", format="WAV")
        data = {"model": self.model, "mode": self.mode, "language_code": self.language or "unknown"}
        if self.keyterms and self.model.endswith("v4"):
            data["keyterms"] = json.dumps(self.keyterms, ensure_ascii=False)
        try:
            response = client.post(
                self.url,
                headers=self._headers,
                data=data,
                files={"file": ("segment.wav", buffer.getvalue(), "audio/wav")},
            )
        except httpx.HTTPError as exc:
            raise SarvamASRError(f"Saaras request failed: {exc!r}") from exc
        if response.status_code != 200:
            raise SarvamASRError(f"Saaras returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise SarvamASRError("Saaras returned non-JSON") from exc
        transcript = body.get("transcript") if isinstance(body, dict) else None
        if not isinstance(transcript, str):
            raise SarvamASRError("Saaras response has no transcript")
        self.last_language = body.get("language_code") if isinstance(body.get("language_code"), str) else None
        try:
            score = float(body.get("language_probability"))
        except (TypeError, ValueError):
            score = 0.0
        score = min(max(score, 0.0), 1.0) if np.isfinite(score) else 0.0
        return transcript.strip(), score if transcript.strip() else 0.0
