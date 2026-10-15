"""Validate schema and search queries against a disposable FalkorDB graph.

Set WSW_FALKORDB_URL to use a different local server. These checks fail if the
database is unavailable, so a successful run always exercises real indexes.
"""

from __future__ import annotations

import os
import uuid

import pytest
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from wsw_brain.graph import cypher
from wsw_brain.graph.text import fulltext_query, query_terms


@pytest.fixture
def graph():
    db = FalkorDB.from_url(
        os.environ.get("WSW_FALKORDB_URL", "falkor://127.0.0.1:6379"),
        socket_connect_timeout=3,
        socket_timeout=10,
    )
    raw = db.select_graph("on_record_schema_test_" + uuid.uuid4().hex)
    try:
        yield raw
    finally:
        if db.connection.exists(raw.name):
            raw.delete()
        db.connection.close()


def apply_schema(graph):
    # Like the source GraphStore, allow only the expected duplicate-index error.
    for statement in [*cypher.schema_statements(), cypher.vector_index(8)]:
        try:
            graph.query(statement)
        except ResponseError as exc:
            if "already indexed" not in str(exc).lower():
                raise


def test_schema_can_be_reapplied_without_changing_indexes(graph):
    apply_schema(graph)
    first = graph.query(cypher.LIST_INDEXES).result_set
    graph.query("CREATE (:Meeting {id: 'retained', title: 'Pricing review'})")

    apply_schema(graph)
    second = graph.query(cypher.LIST_INDEXES).result_set
    assert sorted(first) == sorted(second)
    assert graph.query("MATCH (m:Meeting {id: 'retained'}) RETURN m.title").result_set == [
        ["Pricing review"]
    ]

    indexes = {row[0]: (row[2], row[3]) for row in second}
    for label in ("Meeting", "Speaker", "Person", "Topic", "Decision", "ActionItem", "Entity", "Turn"):
        assert indexes[label][0]["id"] == ["RANGE"], label
    types, options = indexes["Utterance"]
    assert types["id"] == ["RANGE"]
    assert types["t_start"] == ["RANGE"]
    assert types["meeting_id"] == ["RANGE"]
    assert types["text"] == ["FULLTEXT"]
    assert types["embedding"] == ["VECTOR"]
    assert options["embedding"]["dimension"] == 8
    assert options["embedding"]["similarityFunction"] == "cosine"
    assert indexes["ActionItem"][0]["status"] == ["RANGE"]
    assert indexes["Decision"][0]["status"] == ["RANGE"]
    assert indexes["Turn"][0]["session_id"] == ["RANGE"]


def test_fulltext_and_vector_queries_return_the_matching_utterance(graph):
    apply_schema(graph)
    graph.query(
        """
        UNWIND $rows AS r
        CREATE (u:Utterance {id: r.id, meeting_id: 'm1', seq: r.seq, text: r.text})
        SET u.embedding = vecf32(r.embedding)
        """,
        {"rows": [
            {"id": "pricing", "seq": 0, "text": "The pricing review is on Friday",
             "embedding": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            {"id": "hiring", "seq": 1, "text": "We are hiring two designers",
             "embedding": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        ]},
    )
    text_hits = graph.query(
        cypher.fulltext_hits(False),
        {"query": fulltext_query(query_terms('What about "pricing"?')), "k": 5},
    ).result_set
    assert [row[0] for row in text_hits] == ["pricing"]

    vector_hits = graph.query(
        cypher.vector_hits(False),
        {"vector": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "knn": 2, "k": 2},
    ).result_set
    assert [row[0] for row in vector_hits] == ["pricing", "hiring"]
    assert vector_hits[0][8] > vector_hits[1][8]
