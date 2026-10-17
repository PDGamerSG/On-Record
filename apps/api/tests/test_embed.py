"""Offline embeddings must stay usable across indexing and later search processes."""

from __future__ import annotations

import numpy as np
import pytest

from wsw_brain.brain import HashEmbedder


@pytest.mark.parametrize("dim", [1, 64, 768])
def test_embeddings_have_the_requested_size_and_unit_length(dim: int) -> None:
    embedder = HashEmbedder(dim)

    vectors = embedder.embed_documents(["pricing deck", "hiring plans"])

    assert embedder.dim == dim
    assert len(vectors) == 2
    assert all(isinstance(vector, list) and len(vector) == dim for vector in vectors)
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1.0, 1.0])
    assert np.isfinite(vectors).all()


def test_documents_and_queries_use_the_same_text_normalisation() -> None:
    embedder = HashEmbedder(64)

    documents = embedder.embed_documents(["PRICING, deck!", "hiring plans"])

    assert documents == [embedder.embed_query("pricing deck"), embedder.embed_query("hiring plans")]


def test_shared_words_rank_above_unrelated_meeting_text() -> None:
    embedder = HashEmbedder()
    documents = np.array(embedder.embed_documents([
        "The pricing deck is due Friday.",
        "Hire a backend engineer next quarter.",
    ]))

    pricing, hiring = documents @ np.array(embedder.embed_query("pricing deck"))

    assert pricing > hiring


def test_bigrams_distinguish_reversed_phrases() -> None:
    embedder = HashEmbedder()

    forward = embedder.embed_query("pricing deck")
    reverse = embedder.embed_query("deck pricing")

    assert forward != reverse
    assert 0 < np.dot(forward, reverse) < 1


@pytest.mark.parametrize("text", ["", " \t\n", "?!"])
def test_text_without_words_has_a_fixed_nonzero_vector(text: str) -> None:
    embedder = HashEmbedder(8)

    assert embedder.embed_query(text) == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_empty_document_batch_returns_no_vectors() -> None:
    assert HashEmbedder().embed_documents([]) == []


@pytest.mark.parametrize("dim", [0, -1, True, 2.5, "64", None])
def test_invalid_dimensions_fail_before_building_vectors(dim: object) -> None:
    with pytest.raises(ValueError, match="dim must be a positive int"):
        HashEmbedder(dim)  # type: ignore[arg-type]
