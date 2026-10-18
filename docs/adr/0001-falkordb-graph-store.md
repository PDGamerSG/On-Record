# ADR-0001: Store meeting memory in FalkorDB

## Context

On Record keeps meetings, people, utterances, decisions, action items and documents, and links them to each other (who said what, which decision came from which line). Questions need both keyword and semantic search over the same records (docs/ARCHITECTURE.md:36).

## Decision

A single FalkorDB graph holds the meeting memory and provides the full-text and vector indexes. `GraphStore` is the only module that talks to FalkorDB (apps/api/wsw_brain/graph/store.py:1), and every Cypher statement lives in `graph/cypher.py` with values passed as `$params` (apps/api/wsw_brain/graph/cypher.py:1-2). Documents use the same connection through `DocumentStore` (apps/api/wsw_brain/documents/store.py:153). FalkorDB runs from `docker compose` (README.md:99-105). The schema is described in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Status

Accepted (retroactive)

## Consequences

Positive:

- Relationships, full-text search and vector search sit in one store, so a hit can be expanded to its meeting and speaker without a second system.
- Writes are batched with `UNWIND $rows`, one query per batch (apps/api/wsw_brain/graph/store.py:4).
- Each read that feeds an answer records its Cypher in `last_cypher`, so the interface can show "Why this answer" (apps/api/wsw_brain/graph/store.py:10-11).

Negative:

- Queries must follow engine-specific rules to stay correct on both the 4.x and 6.0.x engines (apps/api/wsw_brain/graph/store.py:5-7).
- Vector scores come back as distances and must be converted to similarities (apps/api/wsw_brain/graph/store.py:8-9).
- Development and CI need a running database; several live tests fail without it (README.md:116).

## Alternatives

Not recorded in the repository. Within FalkorDB, the code names one query-level choice: inline property maps after `UNWIND` "rather than WHERE n.id = r.id" (apps/api/wsw_brain/graph/store.py:5-7).

## Sources

- docs/ARCHITECTURE.md:36
- apps/api/wsw_brain/graph/store.py:1-11
- apps/api/wsw_brain/graph/cypher.py:1-2
- apps/api/wsw_brain/documents/store.py:153
- README.md:99-116
