"""LiveSession tests: VAD segmentation, speaker attribution, batching, recording and resumed meetings.

Session tests feed tests/fixtures/two_speakers.wav (a 50 s dialogue, 9 alternating turns separated by
0.6 s of low noise) through the real Silero VAD and speaker model with a stub ASR, and skip when either
model is missing from WSW_MODELS_DIR. `_tight` rebuilds the dialogue with 0.15 s gaps, which the VAD
cannot cut, to exercise in-segment speaker-change detection.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from wsw_brain.config import settings
from wsw_brain.contracts import SAMPLE_RATE, ListenerCallbacks, Utterance
from wsw_brain.listen import (
    AudioTooLong,
    ListenerOverloaded,
    LiveSession,
    decode_file,
    float_to_pcm16,
    process_file,
    write_wav,
)
from wsw_brain.listen.session import _is_garbage
from wsw_brain.listen.speakers import SherpaSpeakerEmbedder

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_WAV = FIXTURES / "two_speakers.wav"
TRUTH = json.loads((FIXTURES / "two_speakers.truth.json").read_text(encoding="utf-8"))["turns"]
MODELS = settings().models_dir
TITANET = "speaker_embedding_en.onnx"  # NeMo TitaNet-small (the default WSW_SPEAKER_MODEL)
ERES2NET = "speaker_embedding.onnx"  # 3D-Speaker ERes2Net
VAD = "silero_vad.onnx"
THRESHOLD = 0.50  # TitaNet-small is perfect from 0.45 to 0.55 on every set here; ERes2Net attributes all
# turns correctly at 0.50 too


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class StubASR:
    """Deterministic ASR for speaker-attribution tests (speaker logic does not depend on the text)."""

    name = "stub"

    def __init__(self, fail_first: int = 0) -> None:
        self.calls = 0
        self.fail_first = fail_first

    def transcribe(self, samples: np.ndarray) -> tuple[str, float]:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("stub ASR exploded")
        return f"words {self.calls}", 0.9


class Collector:
    def __init__(self) -> None:
        self.utterances: list[Utterance] = []
        self.merges: list[tuple[str, str]] = []
        self.statuses: list[tuple[float, str, dict[str, Any]]] = []

    def callbacks(self) -> ListenerCallbacks:
        return ListenerCallbacks(
            on_utterance=self.utterances.append,
            on_speaker_merged=self._merged,
            on_status=lambda state, detail: self.statuses.append((time.monotonic(), state, detail)),
        )

    def _merged(self, meeting_id: str, src: str, dst: str) -> None:
        self.merges.append((src, dst))
        for u in self.utterances:
            if u.speaker == src:
                u.speaker = dst


def _need(model: str) -> Path:
    path = MODELS / model
    if not path.is_file():
        pytest.skip(f"model not downloaded: {path}")
    return path


@pytest.fixture(scope="module")
def fixture_audio() -> np.ndarray:
    return decode_file(FIXTURE_WAV)


@pytest.fixture(scope="module", params=[TITANET, ERES2NET])
def any_embedder(request: pytest.FixtureRequest) -> SherpaSpeakerEmbedder:
    _need(VAD)
    return SherpaSpeakerEmbedder(_need(request.param))


@pytest.fixture(scope="module")
def titanet() -> SherpaSpeakerEmbedder:
    _need(VAD)
    return SherpaSpeakerEmbedder(_need(TITANET))


class _NoEmbedder:
    """For configuration errors raised before the session embeds anything."""

    name, dim = "none", 1

    def embed(self, samples: np.ndarray) -> np.ndarray:
        raise AssertionError("not expected to embed")


def _tight(audio: np.ndarray, gap_s: float = 0.15) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """The fixture turns re-joined with `gap_s` of noise: too short for the VAD to separate them."""
    rng = np.random.default_rng(1)
    pieces = [np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)]
    cursor, turns = 0.5, []
    for turn in TRUTH:
        seg = audio[int(turn["t_start"] * SAMPLE_RATE) : int(turn["t_end"] * SAMPLE_RATE)]
        turns.append({**turn, "t_start": cursor, "t_end": cursor + seg.size / SAMPLE_RATE})
        pieces += [seg, rng.normal(0.0, 0.0008, int(gap_s * SAMPLE_RATE)).astype(np.float32)]
        cursor += seg.size / SAMPLE_RATE + gap_s
    return np.concatenate(pieces), turns


def _attribution(utterances: list[Utterance], turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Map tracks to true speakers by overlap; score time-weighted accuracy and per-turn majority."""
    overlap: dict[tuple[str, str], float] = defaultdict(float)
    for u in utterances:
        for t in turns:
            o = min(u.t_end, t["t_end"]) - max(u.t_start, t["t_start"])
            if o > 0:
                overlap[(u.speaker, t["speaker"])] += o
    tracks = sorted({u.speaker for u in utterances}, key=lambda trk: int(trk[1:]))
    mapping: dict[str, str] = {}  # one-to-one, greedy by overlap; extra tracks count as wrong ("?")
    for (trk, sp), _ in sorted(overlap.items(), key=lambda kv: kv[1], reverse=True):
        if trk not in mapping and sp not in mapping.values():
            mapping[trk] = sp
    mapping.update({trk: "?" for trk in tracks if trk not in mapping})
    total = sum(overlap.values())
    correct = sum(v for (trk, sp), v in overlap.items() if mapping[trk] == sp)
    turn_ok = 0
    for t in turns:
        votes: Counter[str] = Counter()
        for u in utterances:
            o = min(u.t_end, t["t_end"]) - max(u.t_start, t["t_start"])
            if o > 0:
                votes[mapping[u.speaker]] += o
        turn_ok += bool(votes) and votes.most_common(1)[0][0] == t["speaker"]
    return {
        "tracks": tracks,
        "mapping": mapping,
        "time_acc": correct / total if total else 0.0,
        "turn_acc": turn_ok / len(turns),
    }


def _run_session(
    audio: np.ndarray, asr: Any, embedder: Any, collector: Collector, *, live: bool = False, **kwargs: Any
) -> LiveSession:
    """Feed 100 ms PCM16 frames like the WebSocket does. live=True waits for the worker after every
    frame, i.e. the worker keeps up with the stream (each segment is handled as soon as it ends)."""
    session = LiveSession(
        "m_test",
        asr,
        embedder,
        collector.callbacks(),
        threshold=kwargs.pop("threshold", THRESHOLD),
        max_utterance_s=12.0,
        **kwargs,
    )
    pcm = float_to_pcm16(audio)
    for i in range(0, len(pcm), 3200):
        session.feed_pcm16(pcm[i : i + 3200])
        if live:
            assert session.wait_idle(120), "worker did not keep up"
    session.close(timeout=600)
    return session


def _assert_two_speakers_in_order(utterances: list[Utterance], turns: list[dict[str, Any]]) -> dict[str, Any]:
    score = _attribution(utterances, turns)
    assert score["tracks"] == ["S1", "S2"], score
    assert sorted(score["mapping"].values()) == ["David", "Zira"], score
    assert score["turn_acc"] >= 0.8, score
    seqs = [u.seq for u in utterances]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    assert all(a.t_start <= b.t_start for a, b in itertools.pairwise(utterances))
    assert all(0.0 <= u.confidence <= 1.0 and u.t_end > u.t_start for u in utterances)
    return score


# ---------------------------------------------------------------------------
# without models
# ---------------------------------------------------------------------------


def test_garbage_filter() -> None:
    assert _is_garbage("", rms=0.1, asr_confidence=0.9, quiet_rms=0.012)
    assert _is_garbage(" ... !? ", rms=0.1, asr_confidence=0.9, quiet_rms=0.012)
    assert _is_garbage("Thank you.", rms=0.005, asr_confidence=0.9, quiet_rms=0.012)  # near-silence
    assert _is_garbage("Thank you.", rms=0.1, asr_confidence=0.2, quiet_rms=0.012)  # unsure
    assert not _is_garbage("Thank you.", rms=0.1, asr_confidence=0.8, quiet_rms=0.012)
    assert not _is_garbage("Ship it on Friday.", rms=0.005, asr_confidence=0.3, quiet_rms=0.012)


def test_session_requires_utterances_longer_than_min_speech() -> None:
    with pytest.raises(ValueError, match="max_utterance_s"):
        LiveSession(
            "m", StubASR(), _NoEmbedder(), Collector().callbacks(), threshold=0.5, max_utterance_s=0.1
        )


def test_session_reports_a_missing_vad_model(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Silero VAD model not found"):
        LiveSession(
            "m",
            StubASR(),
            _NoEmbedder(),
            Collector().callbacks(),
            threshold=0.5,
            max_utterance_s=12.0,
            vad_model_path=tmp_path / "missing.onnx",
        )


def test_process_file_rejects_an_unknown_pace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pace"):
        process_file(
            tmp_path / "clip.wav",
            "m",
            StubASR(),
            _NoEmbedder(),
            Collector().callbacks(),
            pace="slow",  # type: ignore[arg-type]
            threshold=THRESHOLD,
            max_utterance_s=12.0,
        )


def test_process_file_returns_nothing_when_cancelled_before_it_starts() -> None:
    cancel = threading.Event()
    cancel.set()
    utterances = process_file(
        FIXTURE_WAV,
        "m",
        StubASR(),
        _NoEmbedder(),
        Collector().callbacks(),
        threshold=THRESHOLD,
        max_utterance_s=12.0,
        cancel=cancel,
    )
    assert utterances == []


def test_process_file_refuses_missing_and_too_long_audio_before_listening(tmp_path: Path) -> None:
    kwargs: dict[str, Any] = {"threshold": THRESHOLD, "max_utterance_s": 12.0}
    with pytest.raises(FileNotFoundError):
        process_file(
            tmp_path / "missing.wav", "m", StubASR(), _NoEmbedder(), Collector().callbacks(), **kwargs
        )
    clip = tmp_path / "clip.wav"
    write_wav(clip, np.zeros(2 * SAMPLE_RATE, dtype=np.float32))
    rec = tmp_path / "rec.wav"
    with pytest.raises(AudioTooLong):
        process_file(
            clip,
            "m",
            StubASR(),
            _NoEmbedder(),
            Collector().callbacks(),
            recording_path=rec,
            max_duration_s=1.0,
            **kwargs,
        )
    assert not rec.exists()  # refused before the session opened a recording


# ---------------------------------------------------------------------------
# LiveSession with the real VAD and speaker models (stub ASR: fast)
# ---------------------------------------------------------------------------


def test_session_back_to_back_turns(any_embedder: SherpaSpeakerEmbedder, fixture_audio: np.ndarray) -> None:
    audio, turns = _tight(fixture_audio)
    collector = Collector()
    session = _run_session(audio, StubASR(), any_embedder, collector)
    score = _assert_two_speakers_in_order(collector.utterances, turns)
    assert score["turn_acc"] == 1.0 and score["time_acc"] > 0.95, score
    assert session.metrics()["splits"] >= 5  # most turn changes had no pause the VAD could use


def test_session_records_audio_reports_status_and_numbers_from_start_seq(
    titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray, tmp_path: Path
) -> None:
    clip = fixture_audio[: int(13.0 * SAMPLE_RATE)]  # first two turns
    collector = Collector()
    rec = tmp_path / "audio" / "m_test.wav"
    session = _run_session(clip, StubASR(), titanet, collector, start_seq=40, recording_path=rec)
    assert collector.utterances[0].seq == 40
    assert session.next_seq == 40 + len(collector.utterances)
    assert {u.speaker for u in collector.utterances} == {"S1", "S2"}
    assert sf.info(str(rec)).frames == clip.size and session.recording_path == rec
    states = [s for _, s, _ in collector.statuses]
    assert states[0] == "listening" and states[-1] == "idle"
    assert all("lag_s" in d for _, _, d in collector.statuses)
    regular = [ts for ts, s, _ in collector.statuses if s in ("listening", "processing")]
    assert all(b - a >= 1.9 for a, b in itertools.pairwise(regular))  # at most every 2 s
    assert session.lag_s == 0.0 and not session.running
    with pytest.raises(RuntimeError, match="closed"):
        session.feed(np.zeros(160, dtype=np.float32))
    session.close()  # idempotent


def test_session_survives_asr_errors(titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray) -> None:
    collector = Collector()
    asr = StubASR(fail_first=1)
    session = _run_session(fixture_audio[: int(20 * SAMPLE_RATE)], asr, titanet, collector)
    errors = [d for _, s, d in collector.statuses if s == "error"]
    assert len(errors) == 1 and "stub ASR exploded" in errors[0]["detail"]
    assert collector.utterances and asr.calls > 1
    assert session.metrics()["errors"] == 1 and not session.running


def test_session_survives_a_failing_callback(
    titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray
) -> None:
    delivered: list[Utterance] = []
    statuses: list[tuple[str, dict[str, Any]]] = []

    def on_utterance(u: Utterance) -> None:
        if u.seq == 0:
            raise KeyError("graph writer down")
        delivered.append(u)

    callbacks = ListenerCallbacks(on_utterance=on_utterance, on_status=lambda s, d: statuses.append((s, d)))
    session = LiveSession("m_cb", StubASR(), titanet, callbacks, threshold=THRESHOLD, max_utterance_s=12.0)
    session.feed(fixture_audio[: int(20 * SAMPLE_RATE)])
    session.close()
    errors = [d["detail"] for s, d in statuses if s == "error"]
    assert errors == ["delivering an utterance: KeyError: 'graph writer down'"]
    assert [u.seq for u in delivered] == list(range(1, 1 + len(delivered))) and delivered


def test_session_ignores_silence_and_noise(titanet: SherpaSpeakerEmbedder) -> None:
    rng = np.random.default_rng(3)
    noise = rng.normal(0.0, 0.001, 3 * SAMPLE_RATE).astype(np.float32)
    collector = Collector()
    asr = StubASR()
    session = _run_session(noise, asr, titanet, collector)
    assert collector.utterances == [] and asr.calls == 0
    assert session.metrics()["audio_s"] == pytest.approx(3.0)


def _shifted(turns: list[dict[str, Any]], start_s: float) -> list[dict[str, Any]]:
    return [{**t, "t_start": t["t_start"] - start_s, "t_end": t["t_end"] - start_s} for t in turns]


def test_session_resumed_meeting_keeps_speaker_tracks(
    titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray, tmp_path: Path
) -> None:
    """A microphone that reconnects starts a new LiveSession for the same meeting. Its first voice must
    not take track S1 when S1 is somebody else: tracks name the meeting's Speaker nodes."""
    state = tmp_path / "audio" / "m_test.speakers.json"
    first = Collector()
    _run_session(
        fixture_audio[: int(13.0 * SAMPLE_RATE)], StubASR(), titanet, first, speaker_state_path=state
    )
    assert _attribution(first.utterances, TRUTH[:2])["mapping"] == {"S1": "David", "S2": "Zira"}
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert set(saved["tracks"]) == {"S1", "S2"} and saved["next"] == 3 and saved["model"] == titanet.name

    start = 19.5  # the session after the reconnect hears Zira first, then David
    resumed_audio, turns = (
        fixture_audio[int(start * SAMPLE_RATE) : int(31.0 * SAMPLE_RATE)],
        _shifted(TRUTH[3:5], start),
    )
    fresh = Collector()
    _run_session(resumed_audio, StubASR(), titanet, fresh)
    assert _attribution(fresh.utterances, turns)["mapping"] == {"S1": "Zira", "S2": "David"}  # the bug
    resumed = Collector()
    session = _run_session(resumed_audio, StubASR(), titanet, resumed, speaker_state_path=state)
    assert _attribution(resumed.utterances, turns)["mapping"] == {"S1": "David", "S2": "Zira"}
    assert session.clusterer.tracks == ["S1", "S2"]

    other_model = tmp_path / "other.speakers.json"
    other_model.write_text(json.dumps({**saved, "model": "sherpa-other"}), encoding="utf-8")
    renumbered = LiveSession(
        "m_test",
        StubASR(),
        titanet,
        Collector().callbacks(),
        threshold=THRESHOLD,
        max_utterance_s=12.0,
        speaker_state_path=other_model,
    )
    renumbered.close()
    assert renumbered.speaker_state()["tracks"] == {} and renumbered.speaker_state()["next"] == 3
    broken = tmp_path / "broken.speakers.json"
    broken.write_text("{not json", encoding="utf-8")
    ignored = LiveSession(
        "m_test",
        StubASR(),
        titanet,
        Collector().callbacks(),
        threshold=THRESHOLD,
        max_utterance_s=12.0,
        speaker_state_path=broken,
    )
    ignored.close()
    assert ignored.speaker_state()["next"] == 1


class _BorderlineShortParts:
    """The real embedder, except that a part between short_s and confirm_s long comes back at cosine
    `sim` (just below the threshold) to its closest track and orthogonal to all others' directions: the
    noisy embedding of a brief interjection that used to open a phantom track."""

    def __init__(self, inner: SherpaSpeakerEmbedder, sim: float) -> None:
        self.inner, self.sim = inner, sim
        self.name, self.dim = inner.name, inner.dim
        self.session: LiveSession | None = None
        self.perturbed = 0

    def embed(self, samples: np.ndarray) -> np.ndarray:
        vec = self.inner.embed(samples)
        centroids = self.session.clusterer.centroids() if self.session is not None else {}
        if not centroids or not 0.8 * SAMPLE_RATE <= samples.size < 2.0 * SAMPLE_RATE:
            return vec
        basis = np.stack(list(centroids.values()))
        closest = basis[int(np.argmax(basis @ vec))]
        q, _ = np.linalg.qr(basis.T)
        noise = np.random.default_rng(self.perturbed).normal(size=vec.size).astype(np.float32)
        noise -= q @ (q.T @ noise)
        noise /= np.linalg.norm(noise)
        self.perturbed += 1
        return (self.sim * closest + np.sqrt(1.0 - self.sim**2) * noise).astype(np.float32)


@pytest.mark.parametrize("confirm_s", [2.0, 0.0])
def test_session_borderline_interjection_does_not_open_a_phantom_track(
    titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray, confirm_s: float
) -> None:
    def cut(t0: float, t1: float) -> np.ndarray:
        return fixture_audio[int(t0 * SAMPLE_RATE) : int(t1 * SAMPLE_RATE)]

    gap = np.random.default_rng(2).normal(0.0, 0.0008, int(0.8 * SAMPLE_RATE)).astype(np.float32)
    clip_start = 13.0 + gap.size / SAMPLE_RATE
    # David, Zira, then a 1.2 s piece of Zira (the interjection), then David again
    audio = np.concatenate([cut(0.0, 13.0), gap, cut(44.0, 45.2), gap, cut(13.28, 19.4)])
    embedder = _BorderlineShortParts(titanet, sim=THRESHOLD - 0.05)
    collector = Collector()
    session = LiveSession(
        "m_test",
        StubASR(),
        embedder,
        collector.callbacks(),
        threshold=THRESHOLD,
        max_utterance_s=12.0,
        split_turns=False,
        confirm_s=confirm_s,
    )
    embedder.session = session
    session.feed(audio)
    session.close(timeout=120)
    assert embedder.perturbed >= 1
    clip = [u for u in collector.utterances if u.t_start < clip_start + 1.2 and u.t_end > clip_start]
    assert clip, collector.utterances
    if confirm_s == 0.0:  # the old rule: a 1.2 s part just below the threshold opens a track of its own
        assert "S3" in session.clusterer.tracks and clip[0].speaker == "S3"
    else:
        assert session.clusterer.tracks == ["S1", "S2"], collector.utterances
        assert {u.speaker for u in clip} == {"S2"} and session.metrics()["held"] >= 1  # Zira's track


def test_session_feed_refuses_audio_past_max_queued(titanet: SherpaSpeakerEmbedder) -> None:
    release = threading.Event()

    def on_status(state: str, detail: dict[str, Any]) -> None:
        release.wait(30)  # the worker's first status call: it takes nothing off the queue until released

    session = LiveSession(
        "m_flood",
        StubASR(),
        titanet,
        ListenerCallbacks(on_utterance=lambda u: None, on_status=on_status),
        threshold=THRESHOLD,
        max_utterance_s=12.0,
        max_queued_s=5.0,
    )
    second = np.zeros(SAMPLE_RATE, dtype=np.float32)
    for _ in range(5):
        session.feed(second)
    with pytest.raises(ListenerOverloaded, match="faster than it can be processed"):
        session.feed(second)
    with pytest.raises(ListenerOverloaded):
        session.feed(np.zeros(10 * SAMPLE_RATE, dtype=np.float32))
    assert session.queued_s == 5.0 and session.metrics()["audio_s"] == 5.0  # the refused audio was not queued
    assert not session.wait_queued(1.0, timeout=0.2)
    release.set()
    assert session.wait_queued(0.0, timeout=30)
    session.feed(second)  # room again
    session.close()
    assert session.metrics()["audio_s"] == 6.0 and session.lag_s == 0.0


def test_process_file_realtime_pace_follows_the_clock(
    titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray, tmp_path: Path
) -> None:
    clip = tmp_path / "clip.wav"
    write_wav(clip, fixture_audio[: int(1.5 * SAMPLE_RATE)])
    t0 = time.monotonic()
    process_file(
        clip,
        "m_rt",
        StubASR(),
        titanet,
        Collector().callbacks(),
        pace="realtime",
        threshold=THRESHOLD,
        max_utterance_s=12.0,
    )
    assert time.monotonic() - t0 >= 1.4


class _SlowASR(StubASR):
    def transcribe(self, samples: np.ndarray) -> tuple[str, float]:
        time.sleep(0.05)
        return super().transcribe(samples)


def test_process_file_cancel_mid_run_abandons_the_rest(
    titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray, tmp_path: Path
) -> None:
    """Deleting a meeting while its upload is processed: a "fast" file must not already be queued in
    full, and closing must not transcribe whatever is still queued."""
    path = tmp_path / "long.wav"
    write_wav(path, np.tile(fixture_audio, 4))  # ~200 s
    cancel = threading.Event()
    collector = Collector()
    callbacks = collector.callbacks()

    def on_utterance(u: Utterance) -> None:
        callbacks.on_utterance(u)
        cancel.set()  # the meeting is deleted as soon as its first utterance appears

    asr = _SlowASR()
    rec = tmp_path / "rec.wav"
    utterances = process_file(
        path,
        "m_cancel",
        asr,
        titanet,
        dataclasses.replace(callbacks, on_utterance=on_utterance),
        threshold=THRESHOLD,
        max_utterance_s=12.0,
        recording_path=rec,
        cancel=cancel,
    )
    assert utterances and utterances == collector.utterances
    assert max(u.t_end for u in utterances) < 100.0, [(u.seq, u.t_end) for u in utterances]
    assert asr.calls < 20  # the full file is ~36 utterances
    assert sf.info(str(rec)).duration < 100.0  # the recording was finalised where the listener stopped
    rec.unlink()  # closed: a deleted meeting's files can be removed at once
