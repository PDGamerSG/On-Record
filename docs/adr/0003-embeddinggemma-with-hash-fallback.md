# ADR-0003: Local EmbeddingGemma embeddings with a hashing fallback

## Context

Vector search needs text embeddings for utterances, questions and document passages. The project runs on a laptop and in CI, where a model download may be missing or fail.

## Decision

The default embedder is `GemmaEmbedder`, EmbeddingGemma-300m run on the CPU from an ONNX snapshot, with asymmetric search prompts for queries and documents (apps/api/wsw_brain/brain/embed.py:18-20, apps/api/wsw_brain/brain/embed.py:43-46). `get_embedder()` loads it once. If loading fails, or `WSW_EMBEDDER` names another provider, it returns `HashEmbedder`, signed feature hashing over words and bigrams with L2-normalised output (apps/api/wsw_brain/brain/embed.py:140-141, apps/api/wsw_brain/brain/embed.py:173-186). Settings are listed in [CONFIGURATION.md](../CONFIGURATION.md).

## Status

Accepted (retroactive)

## Consequences

Positive:

- No text is sent to a hosted embedding service.
- The service and tests keep working offline; the pipeline tests run on `HashEmbedder`.
- The fallback is logged with its cause (apps/api/wsw_brain/brain/embed.py:182-183).

Negative:

- Hashed vectors capture word overlap, not meaning, so semantic recall drops with only a log line to show it.
- Vectors from the two embedders are not comparable. The retriever has to check whether a meeting's stored vectors match the current embedder (apps/api/wsw_brain/brain/retrieve.py:17-21), and the index dimension must match (README.md:168).

## Alternatives

The hashing embedder is the named alternative: "CPU text embeddings with a deterministic offline alternative" (apps/api/wsw_brain/brain/embed.py:1). No other embedding model is recorded in the repository.

## Sources

- apps/api/wsw_brain/brain/embed.py:1-20
- apps/api/wsw_brain/brain/embed.py:43-46
- apps/api/wsw_brain/brain/embed.py:140-146
- apps/api/wsw_brain/brain/embed.py:173-186
- README.md:168
