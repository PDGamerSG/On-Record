"""Saaras speech recognition over an HTTP mock transport."""

import io
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from wsw_brain.config import Settings
from wsw_brain.contracts import SAMPLE_RATE
from wsw_brain.listen import SaarasASR, SarvamASRError


def tone(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def recorder(responses):
    seen = []

    def handler(request):
        seen.append(request)
        return responses.pop(0) if len(responses) > 1 else responses[0]

    return seen, httpx.MockTransport(handler)


def form_fields(request) -> str:
    return request.content.decode("utf-8", errors="replace")


def test_transcribe_posts_wav_and_maps_language_probability_to_confidence():
    seen, transport = recorder([httpx.Response(200, json={
        "transcript": " Kal tak deck bhej dena. ", "language_code": "hi-IN", "language_probability": 0.87})])
    asr = SaarasASR("key", keyterms=["Priya", "Orbit"], transport=transport)

    text, confidence = asr.transcribe(tone(2.0))

    assert (text, confidence) == ("Kal tak deck bhej dena.", 0.87)
    assert asr.last_language == "hi-IN" and asr.name == "sarvam:saaras:v4"
    request = seen[0]
    assert request.headers["api-subscription-key"] == "key"
    body = form_fields(request)
    assert "saaras:v4" in body and 'name="language_code"' in body and "unknown" in body
    assert json.dumps(["Priya", "Orbit"]) in body
    wav = request.content[request.content.index(b"RIFF"):]
    samples, rate = sf.read(io.BytesIO(wav))
    assert rate == SAMPLE_RATE and len(samples) == 2 * SAMPLE_RATE


def test_long_audio_uses_windows_under_the_rest_limit():
    seen, transport = recorder([
        httpx.Response(200, json={"transcript": "first", "language_probability": 1.0}),
        httpx.Response(200, json={"transcript": "second", "language_probability": 0.5}),
    ])
    text, confidence = SaarasASR("key", language="kn-IN", transport=transport).transcribe(tone(40.0))
    assert (text, confidence) == ("first second", 0.75)
    assert len(seen) == 2 and "kn-IN" in form_fields(seen[0])


def test_silence_skips_the_request_and_errors_are_raised():
    seen, transport = recorder([httpx.Response(200, json={"transcript": "x"})])
    assert SaarasASR("key", transport=transport).transcribe(np.zeros(SAMPLE_RATE, np.float32)) == ("", 0.0)
    assert seen == []
    _, failing = recorder([httpx.Response(400, text="bad audio")])
    with pytest.raises(SarvamASRError, match="HTTP 400"):
        SaarasASR("key", transport=failing).transcribe(tone(1.0))
    _, broken = recorder([httpx.Response(200, json={"language_code": "hi-IN"})])
    with pytest.raises(SarvamASRError, match="no transcript"):
        SaarasASR("key", transport=broken).transcribe(tone(1.0))


def test_keyterms_are_only_sent_to_v4_and_settings_select_language():
    seen, transport = recorder([httpx.Response(200, json={"transcript": "ok"})])
    SaarasASR("key", model="saaras:v3", keyterms=["Priya"], transport=transport).transcribe(tone(1.0))
    assert "keyterms" not in form_fields(seen[0])
    s = Settings(_env_file=None, SARVAM_API_KEY="k", WSW_SARVAM_ASR_LANGUAGE="ta-IN", WSW_SARVAM_ASR_MODE="codemix")
    asr = SaarasASR.from_settings(s, keyterms=["Asha"])
    assert (asr.language, asr.mode, asr.keyterms) == ("ta-IN", "codemix", ["Asha"])
    assert SaarasASR.from_settings(Settings(_env_file=None, SARVAM_API_KEY="k")).language is None
    with pytest.raises(ValueError):
        SaarasASR.from_settings(Settings(_env_file=None))
