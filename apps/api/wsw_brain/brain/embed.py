"""CPU text embeddings with a deterministic offline alternative."""

from __future__ import annotations

import hashlib
import itertools
import logging
import re
from pathlib import Path

import numpy as np

from ..config import settings

log = logging.getLogger(__name__)
QUERY_PROMPT = "task: search result | query: {text}"
DOCUMENT_PROMPT = "title: none | text: {text}"
_SNAPSHOT_PATTERNS = ["onnx/model_quantized.onnx*", "tokenizer*", "*.json"]
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _snapshot_dir(repo: str) -> Path:
    """Keep ONNX and its external weights together as plain files, not HF cache symlinks."""
    from huggingface_hub import snapshot_download

    def has_model(path: Path) -> bool:
        return (path / "onnx" / "model_quantized.onnx").is_file() and (path / "tokenizer.json").is_file()

    folder = settings().models_dir / repo.replace("/", "--")
    if has_model(folder):
        return folder
    log.info("EmbeddingGemma %s not in %s; downloading", repo, folder)
    path = Path(snapshot_download(repo, allow_patterns=_SNAPSHOT_PATTERNS, local_dir=folder))
    if not has_model(path):
        raise FileNotFoundError(
            f"{repo} snapshot at {path} lacks onnx/model_quantized.onnx or tokenizer.json"
        )
    return path


class GemmaEmbedder:
    """EmbeddingGemma-300m with asymmetric search prompts and batched CPU inference."""

    name = "embeddinggemma-300m"

    def __init__(
        self,
        repo: str | None = None,
        dim: int | None = None,
        *,
        threads: int = 4,
        max_tokens: int = 256,
        batch_size: int = 16,
    ) -> None:
        for argument, value in (("threads", threads), ("max_tokens", max_tokens), ("batch_size", batch_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{argument} must be a positive int")
        if dim is not None and (isinstance(dim, bool) or not isinstance(dim, int) or dim <= 0):
            raise ValueError("dim must be a positive int")

        import onnxruntime as ort
        from tokenizers import Tokenizer

        cfg = settings()
        folder = _snapshot_dir(repo or cfg.embed_repo)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(folder / "onnx" / "model_quantized.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._inputs = {item.name for item in self._session.get_inputs()}
        missing = {"input_ids", "attention_mask"} - self._inputs
        if missing:
            raise RuntimeError(
                f"EmbeddingGemma ONNX lacks inputs {sorted(missing)}; has {sorted(self._inputs)}"
            )
        outputs = {item.name: item for item in self._session.get_outputs()}
        if "sentence_embedding" in outputs:
            self._output, self._pooled = "sentence_embedding", True
        elif "last_hidden_state" in outputs:
            self._output, self._pooled = "last_hidden_state", False
        else:
            raise RuntimeError(f"EmbeddingGemma ONNX has no usable output; has {sorted(outputs)}")
        native = outputs[self._output].shape[-1]
        native_dim = native if isinstance(native, int) else 768
        self.dim = min(dim if dim is not None else cfg.embed_dim, native_dim)

        self._tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        pad_id = self._tokenizer.token_to_id("<pad>")
        self._tokenizer.enable_truncation(max_length=max_tokens)
        self._tokenizer.enable_padding(pad_id=pad_id if pad_id is not None else 0, pad_token="<pad>")
        self._batch_size = batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([DOCUMENT_PROMPT.format(text=text) for text in texts]).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._embed([QUERY_PROMPT.format(text=text)])[0].tolist()

    def _embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        chunks = [self._run(texts[i : i + self._batch_size]) for i in range(0, len(texts), self._batch_size)]
        vectors = np.concatenate(chunks, axis=0)[:, : self.dim]
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)

    def _run(self, texts: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(texts)
        ids = np.array([encoding.ids for encoding in encodings], dtype=np.int64)
        mask = np.array([encoding.attention_mask for encoding in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        (output,) = self._session.run([self._output], feeds)
        if self._pooled:
            return np.asarray(output, dtype=np.float32)
        weights = mask[..., None].astype(np.float32)
        return (output * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1.0)


class HashEmbedder:
    """Signed feature hashing over words and bigrams, with L2-normalised output."""

    def __init__(self, dim: int = 768) -> None:
        if isinstance(dim, bool) or not isinstance(dim, int) or dim <= 0:
            raise ValueError("dim must be a positive int")
        self.dim = dim
        self.name = f"hash-{dim}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        words = _WORD.findall(text.lower())
        vec = np.zeros(self.dim, dtype=np.float32)
        features = [(word, 1.0) for word in words] + [
            (f"{a} {b}", 0.5) for a, b in itertools.pairwise(words)
        ]
        for feature, weight in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            vec[value % self.dim] += weight if (value >> 63) & 1 else -weight
        norm = float(np.linalg.norm(vec))
        if norm == 0.0:
            # Cosine indexes require a nonzero vector, including for empty text.
            vec[0] = 1.0
            return vec.tolist()
        return (vec / norm).tolist()
