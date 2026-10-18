"""Speaker clustering and embedding tests.

Clustering tests use synthetic vectors. Embedding and change-point tests use the sherpa-onnx speaker
models in WSW_MODELS_DIR and skip when a model is missing. The fixture (tests/fixtures/two_speakers.wav)
is a 50 s two-voice dialogue: 9 alternating turns separated by 0.6 s of low noise.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from wsw_brain.config import settings
from wsw_brain.contracts import SAMPLE_RATE
from wsw_brain.listen import (
    OnlineClusterer,
    decode_file,
    get_speaker_embedder,
    speaker_clusterer,
    speaker_model_path,
)
from wsw_brain.listen import factory as listen_factory
from wsw_brain.listen.speakers import SherpaSpeakerEmbedder, speaker_change_points

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_WAV = FIXTURES / "two_speakers.wav"
TRUTH = json.loads((FIXTURES / "two_speakers.truth.json").read_text(encoding="utf-8"))["turns"]
MODELS = settings().models_dir
TITANET = "speaker_embedding_en.onnx"  # NeMo TitaNet-small (the default WSW_SPEAKER_MODEL)
ERES2NET = "speaker_embedding.onnx"  # 3D-Speaker ERes2Net
THRESHOLD = 0.50


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
    return SherpaSpeakerEmbedder(_need(request.param))


@pytest.fixture(scope="module")
def titanet() -> SherpaSpeakerEmbedder:
    return SherpaSpeakerEmbedder(_need(TITANET))


def _vec(*values: float, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[: len(values)] = values
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# online clustering (synthetic vectors)
# ---------------------------------------------------------------------------


def test_clusterer_opens_new_speakers_and_assigns() -> None:
    c = OnlineClusterer(0.5)
    a, b = _vec(1, 0), _vec(0, 1)
    assert c.assign(a, 2.0) == ("S1", 1.0)
    track, conf = c.assign(b, 2.0)
    assert track == "S2" and conf == 1.0  # orthogonal to S1: clearly a new voice
    track, conf = c.assign(_vec(1, 0.2), 1.5)
    assert track == "S1" and 0.5 < conf <= 1.0
    assert c.assign(_vec(0.1, 1), 3.0)[0] == "S2"
    assert c.tracks == ["S1", "S2"] and c.previous == "S2"
    assert set(c.centroids()) == {"S1", "S2"}


def test_clusterer_short_low_similarity_segment_inherits_previous_speaker() -> None:
    c = OnlineClusterer(0.5)
    c.assign(_vec(1, 0), 2.0)
    assert c.assign(_vec(0, 1), 0.5) == ("S1", OnlineClusterer.INHERIT_CONFIDENCE)
    assert c.tracks == ["S1"]
    assert c.assign(_vec(0, 1), 2.0)[0] == "S2"  # the same voice for long enough opens a track


def test_clusterer_merges_tracks_whose_centroids_converge() -> None:
    c = OnlineClusterer(0.6)  # merge_threshold = 0.75
    assert c.merge_threshold == pytest.approx(0.75)
    c.assign(_vec(1, 0), 2.0)
    assert c.assign(_vec(0.5, 1), 2.0)[0] == "S2"  # cos = 0.447 < 0.6
    assert c.merge_close() == []
    for _ in range(6):  # S2 keeps hearing a voice between S1 and S2 (closer to S2), so it drifts to S1 ...
        assert c.assign(_vec(0.8, 0.6), 3.0)[0] == "S2"
    assert c.similarities(c.centroids()["S1"])["S2"] > 0.75
    assert c.merge_close() == [("S2", "S1")]  # ... until the newer track folds into the older one
    assert c.tracks == ["S1"] and c.canonical("S2") == "S1" and c.previous == "S1"
    assert c.assign(_vec(0, 0, 1), 2.0)[0] == "S3"  # numbers are never reused


def test_clusterer_caps_speakers_and_chooses_between_neighbours() -> None:
    c = OnlineClusterer(0.5, max_speakers=2)
    c.assign(_vec(1, 0), 2.0)
    c.assign(_vec(0, 1), 2.0)
    track, conf = c.assign(_vec(0.3, 0, 1), 2.0)  # a third voice, but the cap is 2
    assert track == "S1" and conf < 0.5 and c.tracks == ["S1", "S2"]
    assert c.best_match(_vec(0.2, 1))[0] == "S2"
    assert c.choose(_vec(0.1, 1), ["S1", "S2"])[0] == "S2"
    assert c.choose(None, ["S2", "S1"]) == ("S2", OnlineClusterer.INHERIT_CONFIDENCE)
    with pytest.raises(ValueError):
        c.choose(_vec(1, 0), ["S9"])
    with pytest.raises(ValueError):
        c.assign(np.zeros(8, dtype=np.float32), 1.0)
    with pytest.raises(ValueError):
        OnlineClusterer(1.5)


def test_clusterer_needs_more_than_a_borderline_interjection_to_open_a_track() -> None:
    c = OnlineClusterer(0.5)  # short_s 0.8, confirm_s 2.0, open_margin 0.15
    c.assign(_vec(1, 0), 3.0)
    c.assign(_vec(0, 1), 3.0)
    borderline = _vec(0, 0.45, 0, np.sqrt(1 - 0.45**2))  # cos 0.45 to S2: just below the threshold
    assert c.tentative(0.45, 1.0) and not c.tentative(0.45, 2.5) and not c.tentative(0.2, 1.0)
    assert c.assign(borderline, 1.0) == ("S2", OnlineClusterer.INHERIT_CONFIDENCE)  # a 1 s "Sure."
    assert c.tracks == ["S1", "S2"]
    assert c.assign(_vec(0, 0, 1), 1.0)[0] == "S3"  # a clearly different voice still opens a track
    assert c.assign(borderline, 2.5)[0] == "S4"  # and so does a borderline one with enough speech
    legacy = OnlineClusterer(0.5, confirm_s=0.0)
    legacy.assign(_vec(1, 0), 3.0)
    legacy.assign(_vec(0, 1), 3.0)
    assert legacy.assign(borderline, 1.0)[0] == "S3"  # what used to happen


def test_clusterer_state_carries_tracks_to_a_later_session() -> None:
    first = OnlineClusterer(0.5, merge_threshold=0.3)
    first.assign(_vec(1, 0), 3.0)  # S1
    first.assign(_vec(0, 1), 3.0)  # S2
    first.assign(_vec(0, 0, 1), 3.0)  # S3 ...
    first.assign(_vec(0, 0.6, 0.8), 3.0)  # ... drifts towards S2 and is merged into it
    assert first.merge_close() == [("S3", "S2")]
    state = json.loads(json.dumps(first.state()))
    assert set(state["tracks"]) == {"S1", "S2"} and state["next"] == 4

    resumed = OnlineClusterer(0.5)
    resumed.restore(state)
    assert resumed.tracks == ["S1", "S2"] and resumed.previous is None
    assert resumed.assign(_vec(0.1, 1), 2.0)[0] == "S2"  # the voice that was S2 keeps its track
    assert resumed.assign(_vec(0, 0, 0, 1), 2.0)[0] == "S4"  # a new voice never reuses S1..S3
    np.testing.assert_allclose(resumed.centroids()["S1"], first.centroids()["S1"], atol=1e-5)

    renumbered = OnlineClusterer(0.5)
    renumbered.restore(state, centroids=False)  # another speaker model: only the numbering carries over
    assert renumbered.tracks == [] and renumbered.assign(_vec(1, 0), 2.0)[0] == "S4"
    with pytest.raises(RuntimeError):
        renumbered.restore(state)
    for bad in ({"tracks": {"X1": {"total": [1.0], "weight": 1.0}}}, {"tracks": {"S1": {"weight": 1.0}}}):
        fresh = OnlineClusterer(0.5)
        with pytest.raises(ValueError):
            fresh.restore(bad)
        assert fresh.assign(_vec(1, 0), 2.0)[0] == "S1"  # a failed restore leaves the clusterer untouched


# ---------------------------------------------------------------------------
# speaker embeddings and change points (real models)
# ---------------------------------------------------------------------------


def test_embedder_reports_a_missing_model(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="WSW_SPEAKER_MODEL"):
        SherpaSpeakerEmbedder(tmp_path / "nope.onnx")


def test_embedder_is_normalised_and_separates_voices(
    any_embedder: SherpaSpeakerEmbedder, fixture_audio: np.ndarray
) -> None:
    def turn(i: int) -> np.ndarray:
        t = TRUTH[i]
        return fixture_audio[int(t["t_start"] * SAMPLE_RATE) : int(t["t_end"] * SAMPLE_RATE)]

    d1, z1, d2 = (any_embedder.embed(turn(i)) for i in (0, 1, 2))
    assert d1.shape == (any_embedder.dim,) and d1.dtype == np.float32
    assert np.linalg.norm(d1) == pytest.approx(1.0, abs=1e-5)
    assert float(d1 @ d2) > 0.6 > float(d1 @ z1)


def test_embedder_rejects_a_segment_too_short_to_embed(titanet: SherpaSpeakerEmbedder) -> None:
    with pytest.raises(ValueError, match="too short"):
        titanet.embed(np.zeros(160, dtype=np.float32))


def test_change_point_inside_a_segment(titanet: SherpaSpeakerEmbedder, fixture_audio: np.ndarray) -> None:
    david = fixture_audio[int(TRUTH[6]["t_start"] * SAMPLE_RATE) : int(TRUTH[6]["t_end"] * SAMPLE_RATE)]
    zira = fixture_audio[int(TRUTH[7]["t_start"] * SAMPLE_RATE) : int(TRUTH[7]["t_end"] * SAMPLE_RATE)]
    cuts = speaker_change_points(np.concatenate([david, zira]), titanet, THRESHOLD - 0.1)
    assert len(cuts) == 1 and abs(cuts[0] - david.size) < 0.25 * SAMPLE_RATE, (cuts, david.size)
    assert speaker_change_points(david, titanet, THRESHOLD - 0.1) == []
    assert speaker_change_points(david[:SAMPLE_RATE], titanet, THRESHOLD - 0.1) == []


# ---------------------------------------------------------------------------
# shared models from settings
# ---------------------------------------------------------------------------


@pytest.fixture
def speaker_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("WSW_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("WSW_SPEAKER_MODEL", "voice.onnx")
    settings.cache_clear()
    get_speaker_embedder.cache_clear()
    yield tmp_path
    settings.cache_clear()
    get_speaker_embedder.cache_clear()


def test_speaker_model_path_reads_settings(
    speaker_settings: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    assert speaker_model_path() == speaker_settings / "voice.onnx"
    absolute = tmp_path_factory.mktemp("elsewhere") / "titanet.onnx"
    monkeypatch.setenv("WSW_SPEAKER_MODEL", str(absolute))
    settings.cache_clear()
    assert speaker_model_path() == absolute  # an absolute WSW_SPEAKER_MODEL wins over WSW_MODELS_DIR


def test_get_speaker_embedder_loads_the_configured_model_once(
    speaker_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded: list[Path] = []

    class FakeEmbedder:
        def __init__(self, model_path: Path) -> None:
            loaded.append(model_path)

    monkeypatch.setattr(listen_factory, "SherpaSpeakerEmbedder", FakeEmbedder)
    first = get_speaker_embedder()
    assert get_speaker_embedder() is first
    assert loaded == [speaker_settings / "voice.onnx"]


def test_get_speaker_embedder_reports_a_missing_model_on_every_call(speaker_settings: Path) -> None:
    for _ in range(2):  # a failed load is not cached, so adding the model later works without a restart
        with pytest.raises(FileNotFoundError, match="voice.onnx"):
            get_speaker_embedder()


def test_speaker_clusterer_uses_the_configured_threshold(
    speaker_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WSW_SPEAKER_THRESHOLD", "0.62")
    settings.cache_clear()
    clusterer = speaker_clusterer(max_speakers=3)
    assert clusterer.threshold == pytest.approx(0.62) and clusterer.max_speakers == 3
    assert speaker_clusterer() is not clusterer and speaker_clusterer().tracks == []
