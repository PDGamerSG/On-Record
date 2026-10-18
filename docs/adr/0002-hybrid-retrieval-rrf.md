# ADR-0002: Hybrid retrieval with reciprocal-rank fusion

## Context

Questions about a meeting mix exact words (names, amounts) with paraphrase, and some refer to a speaker or to "just now". No single search method covers all of these, and the methods' scores are not on the same scale.

## Decision

`Retriever` runs full-text search, vector k-nearest-neighbour (KNN) search with any `Embedder`, and speaker and recency Cypher templates, then fuses the ranked lists with reciprocal-rank fusion (RRF) (apps/api/wsw_brain/brain/retrieve.py:1-2). `rrf_fuse` keeps each hit from the list where it ranked best and normalises the fused score so the best hit is 1.0 (apps/api/wsw_brain/brain/retrieve.py:29-31). The constant is `RRF_K = 60`, "the usual reciprocal-rank fusion constant" (apps/api/wsw_brain/brain/retrieve.py:16). Documents reuse the same fusion: `DocumentRetriever` fuses full-text and vector passage hits (apps/api/wsw_brain/documents/answer.py:1-5, README.md:268).

## Status

Accepted (retroactive)

## Consequences

Positive:

- Rank-based fusion needs no score calibration between full-text and vector results.
- Recency phrases such as "just now" or "a moment ago" are detected and handled (apps/api/wsw_brain/brain/retrieve.py:22-26).
- Each fused hit keeps a `via` field naming the list it came from (apps/api/wsw_brain/brain/retrieve.py:30-31).

Negative:

- Every question costs several queries. Checking whether stored vectors match the current embedder costs one embedding and one KNN query per meeting, limited to two meetings per question and trusted for 600 s (apps/api/wsw_brain/brain/retrieve.py:17-21).
- Document full-text search covers Latin-script words only, so questions in Indian scripts fall back to a substring search (README.md:268).

## Alternatives

Not recorded in the repository. For the case where RediSearch rejects a query, the store falls back to a bounded CONTAINS scan instead of raising (apps/api/wsw_brain/graph/store.py:794-796).

## Sources

- apps/api/wsw_brain/brain/retrieve.py:1-31
- apps/api/wsw_brain/documents/answer.py:1-5
- README.md:268
- apps/api/wsw_brain/graph/store.py:794-796
