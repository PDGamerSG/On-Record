"""Sarvam translation and Bulbul speech over an HTTP mock transport."""

import base64
import io
import json
import wave

import httpx
import pytest

from wsw_brain.sarvam import SarvamSpeech, SarvamSpeechError, join_wavs, strip_citations

BASE = "https://sarvam.test"


def wav(frames: int, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x00\x01" * frames)
    return out.getvalue()


def test_strip_citations_removes_markers_and_dangling_separators():
    text = "Invoices are paid in 45 days [d:doc-a:c0004], [d:doc-a:c0005]. Priya agreed [u:m1:u00002]."
    assert strip_citations(text) == "Invoices are paid in 45 days. Priya agreed."


@pytest.mark.asyncio
async def test_translate_detects_source_with_mayura_and_uses_sarvam_translate_for_known_source():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        assert request.headers["api-subscription-key"] == "key"
        return httpx.Response(200, json={"translated_text": "ಅನುವಾದ"})

    speech = SarvamSpeech("key", BASE, transport=httpx.MockTransport(handler))
    assert await speech.translate("Paid in 45 days [d:x:c0001].", "kn-IN") == "ಅನುವಾದ"
    assert bodies[0] == {"input": "Paid in 45 days.", "source_language_code": "auto",
                         "target_language_code": "kn-IN", "model": "mayura:v1"}
    await speech.translate("Hello.", "hi-IN", source="en-IN")
    assert bodies[1]["model"] == "sarvam-translate:v1"
    assert await speech.translate("Same.", "hi-IN", source="hi-IN") == "Same."
    with pytest.raises(ValueError):
        await speech.translate("x", "kannada")


@pytest.mark.asyncio
async def test_long_text_is_translated_in_pieces_under_the_limit():
    sizes = []

    def handler(request):
        sizes.append(len(json.loads(request.content)["input"]))
        return httpx.Response(200, json={"translated_text": "t"})

    speech = SarvamSpeech("key", BASE, transport=httpx.MockTransport(handler))
    await speech.translate("A sentence that repeats. " * 100, "hi-IN")
    assert len(sizes) > 1 and max(sizes) <= 900


@pytest.mark.asyncio
async def test_speak_returns_wav_and_validates_language():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"audios": [base64.b64encode(wav(240)).decode()]})

    speech = SarvamSpeech("key", BASE, transport=httpx.MockTransport(handler))
    audio = await speech.speak("Namaste [d:x:c1].", "hi-IN")
    assert audio.startswith(b"RIFF")
    assert bodies[0]["text"] == "Namaste." and bodies[0]["model"] == "bulbul:v3"
    assert bodies[0]["language_code"] == "hi-IN" and bodies[0]["speaker"] == "priya"
    with pytest.raises(ValueError, match="cannot speak"):
        await speech.speak("x", "ur-IN")
    with pytest.raises(ValueError, match="pace"):
        await speech.speak("x", "hi-IN", pace=3)


@pytest.mark.asyncio
async def test_speech_errors_are_reported():
    speech = SarvamSpeech("key", BASE, transport=httpx.MockTransport(lambda r: httpx.Response(429, text="busy")))
    with pytest.raises(SarvamSpeechError, match="HTTP 429"):
        await speech.speak("hello", "en-IN")


def test_join_wavs_concatenates_frames():
    joined = join_wavs([wav(100), wav(50)])
    with wave.open(io.BytesIO(joined), "rb") as reader:
        assert reader.getnframes() == 150 and reader.getframerate() == 24000
