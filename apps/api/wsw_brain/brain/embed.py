"""Deterministic text embeddings that run without downloading a model."""

from __future__ import annotations

import hashlib
import itertools
import re

import numpy as np

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


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
