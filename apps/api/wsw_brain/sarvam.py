"""Sarvam translation (Mayura and sarvam-translate) and speech (Bulbul) for answers in Indian languages."""

from __future__ import annotations

import asyncio
import base64
import re
from typing import Any

import httpx

SARVAM_BASE_URL = "https://api.sarvam.ai"
TRANSLATE_MODEL = "sarvam-translate:v1"
TTS_MODEL = "bulbul:v3"
TRANSLATE_MAX_CHARS = 1900  # sarvam-translate accepts up to 2000 characters per request
DETECT_MODEL = "mayura:v1"  # detects the source language ("auto"); accepts up to 1000 characters
DETECT_MAX_CHARS = 900
TTS_MAX_CHARS = 2500  # Bulbul REST limit per request
LID_MAX_CHARS = 1000  # /text-lid input limit
# Languages Bulbul can speak. Mayura translates into the same 11; sarvam-translate covers all 22 scheduled
# languages but needs a real source code, so /text-lid identifies the source for the other 11.
SPEECH_LANGUAGES = frozenset({"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN",
                              "ta-IN", "te-IN"})
MAYURA_LANGUAGES = SPEECH_LANGUAGES
_CITATION = re.compile(r"\s*\[[du]:[^\]\s]+\]")
_LANGUAGE = re.compile(r"^[a-z]{2,3}-IN$")
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)


class SarvamSpeechError(RuntimeError):
    """A translation or speech request failed."""


def strip_citations(text: str) -> str:
    """Remove [d:...] and [u:...] markers so they are neither translated nor read aloud."""
    text = _CITATION.sub("", text or "")
    text = re.sub(r"[ \t]*,[ \t]*(?=[.;:!?,]|$)", "", text)  # separators left between removed markers
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _check_language(code: str) -> str:
    if not isinstance(code, str) or not _LANGUAGE.match(code):
        raise ValueError(f"language must look like hi-IN, got {code!r}")
    return code


def _pieces(text: str, limit: int) -> list[str]:
    """Split at sentence ends so each request stays under the service's character limit."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?।\n])\s+", text.strip()):
        while len(sentence) > limit:
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


class SarvamSpeech:
    def __init__(
        self,
        api_key: str,
        base_url: str = SARVAM_BASE_URL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("a Sarvam API key is required (set SARVAM_API_KEY)")
        self.base_url = base_url.rstrip("/")
        self._headers = {"api-subscription-key": api_key.strip()}
        self._transport = transport

    async def translate(self, text: str, target: str, source: str = "auto") -> str:
        """Translate text (citation markers removed) into `target`, e.g. "kn-IN". With source="auto" and a
        Mayura target, Mayura detects the source language. Otherwise sarvam-translate is used; for an "auto"
        source, /text-lid identifies it first. /text-lid knows only the 11 Mayura languages, so text in any
        other language raises SarvamSpeechError."""
        _check_language(target)
        clean = strip_citations(text)
        if not clean:
            return ""
        if source != "auto":
            _check_language(source)
            if source == target:
                return clean
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client:
            if source == "auto" and target not in MAYURA_LANGUAGES:
                source = await self._detect(client, clean)  # sarvam-translate has no "auto"
            model, limit = (
                (DETECT_MODEL, DETECT_MAX_CHARS) if source == "auto" else (TRANSLATE_MODEL, TRANSLATE_MAX_CHARS)
            )
            results = await asyncio.gather(*(
                self._post(client, "/translate", {
                    "input": piece, "source_language_code": source, "target_language_code": target, "model": model,
                })
                for piece in _pieces(clean, limit)
            ))
        translated = [r.get("translated_text") for r in results]
        if not all(isinstance(t, str) for t in translated):
            raise SarvamSpeechError("Sarvam translate returned no translated_text")
        return " ".join(translated).strip()

    async def speak(self, text: str, language: str, speaker: str = "priya", pace: float = 1.0) -> bytes:
        """Spoken WAV audio of `text` in `language` from Bulbul v3."""
        _check_language(language)
        if language not in SPEECH_LANGUAGES:
            raise ValueError(f"Bulbul cannot speak {language}; choose one of {sorted(SPEECH_LANGUAGES)}")
        if not 0.5 <= pace <= 2.0:
            raise ValueError("pace must be between 0.5 and 2.0")
        clean = strip_citations(text)
        if not clean:
            raise ValueError("nothing to speak")
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client:
            # One request per piece keeps each under the REST limit; the WAVs play back to back.
            results = [
                await self._post(client, "/text-to-speech", {
                    "text": piece, "language_code": language, "model": TTS_MODEL, "speaker": speaker,
                    "pace": pace, "speech_sample_rate": 24000,
                })
                for piece in _pieces(clean, TTS_MAX_CHARS)
            ]
        clips = [base64.b64decode(audio) for result in results for audio in (result.get("audios") or [])]
        if not clips:
            raise SarvamSpeechError("Sarvam text-to-speech returned no audio")
        return clips[0] if len(clips) == 1 else join_wavs(clips)

    async def _detect(self, client: httpx.AsyncClient, text: str) -> str:
        """The language code /text-lid identifies for `text` (its first LID_MAX_CHARS characters)."""
        body = await self._post(client, "/text-lid", {"input": text[:LID_MAX_CHARS]})
        code = body.get("language_code")
        if not isinstance(code, str) or not _LANGUAGE.match(code):
            raise SarvamSpeechError("Sarvam could not identify the source language")
        return code

    async def _post(self, client: httpx.AsyncClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await client.post(f"{self.base_url}{path}", json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SarvamSpeechError(f"Sarvam {path} request failed: {exc!r}") from exc
        if response.status_code != 200:
            raise SarvamSpeechError(f"Sarvam {path} returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise SarvamSpeechError(f"Sarvam {path} returned non-JSON") from exc
        if not isinstance(data, dict):
            raise SarvamSpeechError(f"Sarvam {path} returned an unexpected body")
        return data


def translator_name(target: str, source: str = "auto") -> str:
    """The model SarvamSpeech.translate() uses for these arguments, as shown to users."""
    return "Sarvam Mayura" if source == "auto" and target in MAYURA_LANGUAGES else "Sarvam Translate"


def join_wavs(clips: list[bytes]) -> bytes:
    """Concatenate PCM WAV clips that share one format (Bulbul returns 16-bit mono at the requested rate)."""
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        for index, clip in enumerate(clips):
            with wave.open(io.BytesIO(clip), "rb") as reader:
                if index == 0:
                    writer.setparams(reader.getparams())
                writer.writeframes(reader.readframes(reader.getnframes()))
    return out.getvalue()
