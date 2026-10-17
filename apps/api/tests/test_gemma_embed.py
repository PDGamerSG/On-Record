"""Exercise the real tokenizer and ONNX runtime with tiny local embedding models."""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from wsw_brain.brain import GemmaEmbedder
from wsw_brain.brain import embed as embed_module
from wsw_brain.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
REPO = "tests/tiny-embeddings"


@pytest.fixture(params=["token_embeddings.onnx", "pooled_embedding.onnx"])
def local_model(request, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = Settings(_env_file=None, WSW_MODELS_DIR=tmp_path / "models", WSW_EMBED_DIM=4)
    monkeypatch.setattr(embed_module, "settings", lambda: cfg)
    folder = cfg.models_dir / REPO.replace("/", "--")
    (folder / "onnx").mkdir(parents=True)
    shutil.copyfile(FIXTURES / request.param, folder / "onnx" / "model_quantized.onnx")
    vocab = {word: index for index, word in enumerate([
        "<pad>", "<unk>", "title:", "none", "|", "text:", "task:", "search", "result", "query:",
        "alpha", "beta",
    ])}
    tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.save(str(folder / "tokenizer.json"))
    return folder


def test_gemma_uses_distinct_document_and_query_prompts(local_model: Path) -> None:
    embedder = GemmaEmbedder(repo=REPO)

    document = embedder.embed_documents(["alpha"])[0]
    query = embedder.embed_query("alpha")

    assert document == pytest.approx([1 / math.sqrt(2), 1 / math.sqrt(2), 0, 0])
    assert query == pytest.approx([3 / math.sqrt(34), 5 / math.sqrt(34), 0, 0])


def test_gemma_batches_in_order_and_ignores_padding(local_model: Path) -> None:
    embedder = GemmaEmbedder(repo=REPO, batch_size=2)

    vectors = embedder.embed_documents(["alpha", "alpha beta", "beta"])

    expected = [
        [1 / math.sqrt(2), 1 / math.sqrt(2), 0, 0],
        [4 / math.sqrt(132), 4 / math.sqrt(132), 6 / math.sqrt(132), 8 / math.sqrt(132)],
        [1 / math.sqrt(101), 0, 6 / math.sqrt(101), 8 / math.sqrt(101)],
    ]
    np.testing.assert_allclose(vectors, expected, atol=1e-6)


def test_gemma_truncates_dimensions_before_normalising(local_model: Path) -> None:
    embedder = GemmaEmbedder(repo=REPO, dim=2)

    assert embedder.embed_documents(["beta"])[0] == pytest.approx([1, 0])
    assert embedder.dim == 2


def test_gemma_caps_the_requested_dimension_at_model_width(local_model: Path) -> None:
    embedder = GemmaEmbedder(repo=REPO, dim=8)

    assert len(embedder.embed_query("alpha")) == embedder.dim == 4


def test_gemma_limits_tokens_before_running_inference(local_model: Path) -> None:
    embedder = GemmaEmbedder(repo=REPO, max_tokens=5)

    vector = embedder.embed_documents(["alpha beta"])[0]

    # The four document prompt tokens leave room for alpha, but not beta.
    assert vector == pytest.approx([1 / math.sqrt(2), 1 / math.sqrt(2), 0, 0])


def test_gemma_empty_batch_returns_no_vectors(local_model: Path) -> None:
    assert GemmaEmbedder(repo=REPO).embed_documents([]) == []


@pytest.mark.parametrize(("argument", "value"), [
    ("dim", 0), ("dim", True), ("dim", 2.5),
    ("threads", 0), ("max_tokens", -1), ("batch_size", 0), ("batch_size", True),
])
def test_gemma_rejects_invalid_options_before_loading_a_model(
    argument: str, value: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_download(repo: str) -> Path:
        pytest.fail("invalid options must not start model loading")

    monkeypatch.setattr(embed_module, "_snapshot_dir", unexpected_download)

    with pytest.raises(ValueError, match=argument):
        GemmaEmbedder(**{argument: value})


def test_cached_model_is_usable_without_a_network_call(
    local_model: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_download(*args, **kwargs):
        pytest.fail("the cached plain-file model must be reused")

    monkeypatch.setattr("huggingface_hub.snapshot_download", unexpected_download)

    assert len(GemmaEmbedder(repo=REPO).embed_query("alpha")) == 4


def test_snapshot_download_keeps_external_model_files_together(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Settings(_env_file=None, WSW_MODELS_DIR=tmp_path / "models")
    monkeypatch.setattr(embed_module, "settings", lambda: cfg)
    folder = cfg.models_dir / REPO.replace("/", "--")

    def download(repo: str, *, allow_patterns: list[str], local_dir: Path) -> str:
        assert repo == REPO and local_dir == folder
        assert "onnx/model_quantized.onnx*" in allow_patterns
        (local_dir / "onnx").mkdir(parents=True)
        (local_dir / "onnx" / "model_quantized.onnx").write_bytes(b"model")
        (local_dir / "onnx" / "model_quantized.onnx_data").write_bytes(b"weights")
        (local_dir / "tokenizer.json").write_text("{}")
        return str(local_dir)

    monkeypatch.setattr("huggingface_hub.snapshot_download", download)

    assert embed_module._snapshot_dir(REPO) == folder
    assert (folder / "onnx" / "model_quantized.onnx_data").is_file()


def test_incomplete_snapshot_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Settings(_env_file=None, WSW_MODELS_DIR=tmp_path / "models")
    monkeypatch.setattr(embed_module, "settings", lambda: cfg)
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda *args, **kwargs: str(tmp_path))

    with pytest.raises(FileNotFoundError, match="lacks"):
        embed_module._snapshot_dir(REPO)
