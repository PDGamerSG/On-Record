# Architecture decision records

These records describe decisions already visible in the code at commit `8943885`. They are retroactive: each one is reconstructed from code comments, documents and pull request descriptions, and cites them. Where the repository does not say which alternatives were considered, the record says "Not recorded in the repository".

For the system overview see [ARCHITECTURE.md](../ARCHITECTURE.md). New records copy [the template](0000-template.md) and take the next number.

| Number | Title | Status | Record |
|---|---|---|---|
| 0001 | Store meeting memory in FalkorDB | Accepted (retroactive) | [0001-falkordb-graph-store.md](0001-falkordb-graph-store.md) |
| 0002 | Hybrid retrieval with reciprocal-rank fusion | Accepted (retroactive) | [0002-hybrid-retrieval-rrf.md](0002-hybrid-retrieval-rrf.md) |
| 0003 | Local EmbeddingGemma embeddings with a hashing fallback | Accepted (retroactive) | [0003-embeddinggemma-with-hash-fallback.md](0003-embeddinggemma-with-hash-fallback.md) |
| 0004 | Provider-agnostic Gemma 4 text adapters behind contracts.LLM | Accepted (retroactive) | [0004-provider-agnostic-llm-adapters.md](0004-provider-agnostic-llm-adapters.md) |
| 0005 | Sarvam Document AI with 10-page splitting | Accepted (retroactive) | [0005-sarvam-document-ai-page-splitting.md](0005-sarvam-document-ai-page-splitting.md) |
| 0006 | Keep only citations to retrieved evidence | Accepted (retroactive) | [0006-citation-grounding.md](0006-citation-grounding.md) |
| 0007 | Demo mode in the web app | Accepted (retroactive) | [0007-web-demo-mode.md](0007-web-demo-mode.md) |
| 0008 | Limit concurrent model calls with ModelGate | Accepted (retroactive) | [0008-model-gate-concurrency.md](0008-model-gate-concurrency.md) |
| 0009 | Server-Sent Events for live updates | Accepted (retroactive) | [0009-server-sent-events.md](0009-server-sent-events.md) |
