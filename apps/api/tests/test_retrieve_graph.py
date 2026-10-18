"""Hybrid retrieval against disposable local graphs; no model downloads."""

import os
import uuid
from types import SimpleNamespace

import pytest

from wsw_brain.brain import HashEmbedder
from wsw_brain.brain import retrieve as retrieve_module
from wsw_brain.brain.retrieve import Retriever
from wsw_brain.contracts import Utterance
from wsw_brain.graph import GraphQueryError, GraphStore

pytestmark = pytest.mark.live


@pytest.fixture
def embedder():
    return HashEmbedder(64)


@pytest.fixture
def store(embedder):
    store = GraphStore(
        os.environ.get("WSW_FALKORDB_URL", "falkor://127.0.0.1:6379"),
        "on_record_retrieval_test_" + uuid.uuid4().hex,
    )
    try:
        store.ensure_schema(embedder.dim)
        meetings = [
            ("pricing", "Pricing review", 1000, [
                ("S1", "The Pro plan costs twenty five dollars per month."),
                ("S2", "We should update the billing page next week."),
                ("S1", "I will send the revised pricing deck by Friday."),
                ("S2", "The invoice migration is ready for launch."),
            ]),
            ("hiring", "Hiring sync", 2000, [
                ("S1", "Hire two backend engineers next quarter."),
                ("S2", "The team will interview candidates on Monday."),
            ]),
        ]
        for mid, title, started, lines in meetings:
            store.create_meeting(mid, title, "mic", started)
            utterances = [
                Utterance(mid, seq, speaker, seq * 5.0, seq * 5.0 + 4.0, text)
                for seq, (speaker, text) in enumerate(lines)
            ]
            store.write_utterances(utterances, embedder.embed_documents([u.text for u in utterances]))
        store.name_speaker("pricing", "S1", "Priya Sharma")
        store.name_speaker("pricing", "S2", "Rahul Singh")
        store.name_speaker("hiring", "S1", "Asha Rao")
        yield store
    finally:
        try:
            store.reset()
        finally:
            store.close()


def test_retrieval_fuses_real_indexes_and_returns_citation_fields_and_queries(store, embedder):
    hits, cypher = Retriever(store, embedder).retrieve("pricing deck", meeting_id="pricing", k=3)

    assert hits[0]["utterance_id"] == "pricing:u00002"
    assert hits[0]["score"] == 1.0
    assert hits[0]["meeting_title"] == "Pricing review"
    assert hits[0]["speaker_name"] == "Priya Sharma"
    assert hits[0]["t_start"] == 10.0
    assert len({h["utterance_id"] for h in hits}) == len(hits) <= 3
    assert {h["meeting_id"] for h in hits} == {"pricing"}
    assert any("db.idx.fulltext.queryNodes" in q for q in cypher)
    assert any("db.idx.vector.queryNodes" in q for q in cypher)


def test_retrieval_can_search_across_meetings(store, embedder):
    hits, _ = Retriever(store, embedder).retrieve("backend engineers", k=6)
    assert hits[0]["utterance_id"] == "hiring:u00000"
    assert {h["meeting_id"] for h in hits} == {"pricing", "hiring"}


def test_speaker_lookup_matches_full_names_first_names_and_unnamed_tracks(store, embedder):
    retriever = Retriever(store, embedder)
    assert retriever.mentioned_speakers("What did PRIYA commit to?", "pricing") == ["Priya Sharma"]
    assert retriever.mentioned_speakers("Ask Priyanka about that", "pricing") == []
    assert retriever.mentioned_speakers("What did Speaker 2 say?", "pricing") == ["Speaker 2"]
    hits, cypher = retriever.retrieve("What did Priya say about the deck?", "pricing")
    assert hits[0]["utterance_id"] == "pricing:u00002"
    assert any("$who" in q for q in cypher)


def test_recency_ranks_newest_first_and_keeps_meeting_scope(store, embedder, monkeypatch):
    monkeypatch.setattr(store, "search_fulltext", lambda *args, **kwargs: [])
    monkeypatch.setattr(store, "search_vector", lambda *args, **kwargs: [])
    retriever = Retriever(store, embedder)
    hits, _ = retriever.retrieve("What was said just now?", "pricing", k=2)
    assert [h["utterance_id"] for h in hits] == ["pricing:u00003", "pricing:u00002"]
    assert all(h["via"] == "recent" for h in hits)
    hits, _ = retriever.retrieve("What was said just now?", k=2)
    assert [h["utterance_id"] for h in hits] == ["hiring:u00001", "hiring:u00000"]


def test_recency_uses_sequence_order_when_speakers_share_a_timestamp(store, embedder, monkeypatch):
    store.create_meeting("overlap", "Overlapping speakers", "mic", 3000)
    utterances = [
        Utterance("overlap", seq, "S1", 0.0, float(seq + 1), f"Overlapping turn number {seq}.")
        for seq in range(3)
    ]
    store.write_utterances(utterances, None)
    monkeypatch.setattr(store, "search_fulltext", lambda *args, **kwargs: [])
    monkeypatch.setattr(store, "search_vector", lambda *args, **kwargs: [])
    hits, _ = Retriever(store, embedder).retrieve("What was said just now?", "overlap", k=2)
    assert [h["utterance_id"] for h in hits] == ["overlap:u00002", "overlap:u00001"]


def test_blank_question_does_not_touch_sources(store, embedder, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("blank question must not query or embed")
    monkeypatch.setattr(store, "search_fulltext", unexpected)
    monkeypatch.setattr(embedder, "embed_query", unexpected)
    assert Retriever(store, embedder).retrieve("  \n ") == ([], [])


@pytest.mark.parametrize("k", [0, -1, True, 2.5, "3"])
def test_retrieval_rejects_invalid_limits_before_querying(store, embedder, monkeypatch, k):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid limit must be rejected before querying")
    monkeypatch.setattr(store, "search_fulltext", unexpected)
    with pytest.raises(ValueError, match="k"):
        Retriever(store, embedder).retrieve("pricing", k=k)


def test_query_embedding_failure_preserves_text_results(store, embedder, monkeypatch, caplog):
    def broken_embedding(text):
        raise RuntimeError("query model unavailable")
    monkeypatch.setattr(embedder, "embed_query", broken_embedding)
    hits, cypher = Retriever(store, embedder).retrieve("pricing deck", "pricing", k=2)
    assert hits[0]["utterance_id"] == "pricing:u00002"
    assert all(h["via"] == "fulltext" for h in hits)
    assert any("db.idx.fulltext.queryNodes" in q for q in cypher)
    assert "query model unavailable" in caplog.text


@pytest.mark.parametrize(
    "failed_source",
    ["search_fulltext", "search_vector", "list_people", "utterances_by_speaker", "recent_utterances"],
)
def test_one_failed_source_does_not_discard_other_results(store, embedder, monkeypatch, failed_source):
    def broken_source(*args, **kwargs):
        raise GraphQueryError("source unavailable")
    monkeypatch.setattr(store, failed_source, broken_source)
    hits, _ = Retriever(store, embedder).retrieve("What did Priya say about the pricing deck just now?", "pricing", k=2)
    assert hits[0]["utterance_id"] == "pricing:u00002"


def test_confirmed_incompatible_vectors_are_excluded_and_verdict_is_cached(store, embedder, monkeypatch):
    class OtherSpace:
        name = "reversed-hash"
        dim = embedder.dim

        def embed_query(self, text):
            return embedder.embed_query(text)[::-1]

        def embed_documents(self, texts):
            return [v[::-1] for v in embedder.embed_documents(texts)]

    retriever = Retriever(store, OtherSpace())
    vector_hits = store.search_vector(OtherSpace().embed_query("pricing deck"), k=6)
    assert {h["meeting_id"] for h in vector_hits} == {"pricing", "hiring"}
    assert retriever.same_space_hits(vector_hits) == []

    def unexpected(*args, **kwargs):
        pytest.fail("cached embedding-space verdict must not query again")
    monkeypatch.setattr(store, "search_vector", unexpected)
    assert retriever.same_space_hits(vector_hits) == []


def test_matching_vectors_survive_space_verification(store, embedder):
    hits = store.search_vector(embedder.embed_query("pricing deck"), k=6)
    assert Retriever(store, embedder).same_space_hits(hits) == hits


def test_repeated_passages_remain_valid_when_self_query_chooses_other_tied_ids(store, embedder):
    text = "I agree with that plan."
    store.create_meeting("repeated", "Repeated agreement", "mic", 3000)
    utterances = [Utterance("repeated", seq, "S1", seq * 5.0, seq * 5.0 + 4.0, text) for seq in range(10)]
    store.write_utterances(utterances, embedder.embed_documents([text] * 10))
    tied = store.search_vector(embedder.embed_documents([text])[0], k=5, meeting_id="repeated")
    all_hits = store.search_vector(embedder.embed_query("agree plan"), k=16, meeting_id="repeated")
    tied_ids = {h["utterance_id"] for h in tied}
    omitted = next(h for h in all_hits if h["utterance_id"] not in tied_ids)
    assert Retriever(store, embedder).same_space_hits([omitted]) == [omitted]


def test_missing_self_neighbor_is_inconclusive_instead_of_confirming_mismatch(store, embedder, monkeypatch):
    hits = store.search_vector(embedder.embed_query("pricing deck"), k=4, meeting_id="pricing")
    monkeypatch.setattr(store, "search_vector", lambda *args, **kwargs: [])
    assert Retriever(store, embedder).same_space_hits(hits) == hits


def test_speaker_name_cache_refreshes_after_rename(store, embedder, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(retrieve_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    retriever = Retriever(store, embedder)
    assert retriever.mentioned_speakers("What did Noor say?", "pricing") == []
    store.name_speaker("pricing", "S2", "Noor Khan")
    assert retriever.mentioned_speakers("What did Noor say?", "pricing") == []
    now[0] = 131.0
    assert retriever.mentioned_speakers("What did Noor say?", "pricing") == ["Noor Khan"]


def test_embedding_space_verdict_expires_after_vectors_are_replaced(store, embedder, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(retrieve_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    retriever = Retriever(store, embedder)
    hits = store.search_vector(embedder.embed_query("pricing deck"), k=6, meeting_id="pricing")
    assert retriever.same_space_hits(hits) == hits
    detail = store.get_meeting("pricing")
    utterances = [
        Utterance(u["meeting_id"], u["seq"], u["speaker"], u["t_start"], u["t_end"], u["text"])
        for u in detail["utterances"]
    ]
    store.write_utterances(
        utterances,
        [v[::-1] for v in embedder.embed_documents([u.text for u in utterances])],
    )
    assert retriever.same_space_hits(hits) == hits
    now[0] = 701.0
    assert retriever.same_space_hits(hits) == []
