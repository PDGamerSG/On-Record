"""Ranking and failure isolation for hybrid meeting retrieval."""

from copy import deepcopy

import pytest

from wsw_brain.brain.retrieve import refers_to_recent, rrf_fuse


def hit(uid, via):
    return {"utterance_id": uid, "via": via, "text": uid, "score": 0.5}


def test_fusion_rewards_agreement_and_preserves_best_source_without_mutating_inputs():
    sources = [
        [hit("x", "fulltext"), hit("y", "fulltext"), hit("z", "fulltext")],
        [hit("y", "vector"), hit("w", "vector")],
        [hit("y", "graph")],
    ]
    original = deepcopy(sources)

    fused = rrf_fuse(sources, k=4)

    assert [h["utterance_id"] for h in fused] == ["y", "x", "w", "z"]
    assert fused[0]["via"] == "vector"
    assert [h["score"] for h in fused] == [1.0, 0.3351, 0.3297, 0.3245]
    assert sources == original


def test_fusion_counts_each_utterance_once_per_source_and_accepts_id_alias():
    fused = rrf_fuse(
        [[hit("x", "fulltext"), hit("x", "fulltext"), {}, hit("y", "fulltext")],
         [{"id": "y", "via": "vector", "text": "y", "score": 0.2}]],
        k=5,
    )
    assert [h["utterance_id"] for h in fused] == ["y", "x"]
    assert fused[0]["via"] == "vector"
    assert fused[1]["score"] == 0.5041


def test_fusion_has_stable_ties_and_respects_result_limit():
    sources = [[hit("x", "fulltext")], [hit("y", "vector")]]
    assert [h["utterance_id"] for h in rrf_fuse(sources, k=1)] == ["x"]
    assert rrf_fuse([[], []], k=2) == []


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
@pytest.mark.parametrize("argument", ["k", "rrf_k"])
def test_fusion_rejects_invalid_rank_limits(value, argument):
    kwargs = {"k": 3, argument: value}
    with pytest.raises(ValueError, match=argument):
        rrf_fuse([[hit("x", "fulltext")]], **kwargs)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What was said just now?", True),
        ("What changed MOST RECENTLY?", True),
        ("Any decisions so far?", True),
        ("What happened a moment ago?", True),
        ("When is the pricing deck due?", False),
        ("Explain the latestness metric", False),
    ],
)
def test_recency_detection_uses_whole_phrases(question, expected):
    assert refers_to_recent(question) is expected
