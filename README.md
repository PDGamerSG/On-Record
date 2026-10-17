# On Record

A meeting assistant that connects what was said to the person who said it.

This repository is being assembled in feature-sized PRs from [Who Said What Brain](https://github.com/Hydra-Of-Malice/hack-october-who-said-what-brain). It currently includes shared Python contracts, graph storage and queries, audio decoding and transcription, text embeddings, hybrid meeting retrieval, and local and hosted text model adapters. Live recording, the assistant, HTTP server, and web interface follow in separate branches.

The display name lives in `brand.json`. `.env.example` lists the configuration the application will use; keep local values in an ignored `.env` file.

See [the source notes](docs/UPSTREAM.md) for the original snapshot and attribution. The code is licensed under [Apache 2.0](LICENSE).

## Python setup

Install [uv](https://docs.astral.sh/uv/), then run from the repository root:

```bash
uv sync --project apps/api --frozen
uv run --project apps/api python -c "from wsw_brain.brand import product_name; print(product_name())"
```

The package uses Python 3.12. It currently provides configuration, shared data contracts, and an in-process event bus. The HTTP server and web interface arrive in later PRs, so there is no application to start yet.

## Offline text embeddings

`HashEmbedder` converts meeting text and search queries into repeatable, normalised vectors without a model download. It uses word and word-pair overlap, so it is useful for local tests and offline search; it does not provide a language model's semantic understanding. Its tokenizer handles ASCII letters and digits. Empty or punctuation-only text receives a fixed unit vector so it remains valid for cosine indexes.

```bash
uv run --project apps/api python -c "from wsw_brain.brain import HashEmbedder; e = HashEmbedder(); print(e.name, len(e.embed_query('pricing deck')))"
```

The default dimension is 768. Pass a positive integer to `HashEmbedder(dim)` to match an existing vector index.

## Model-backed text embeddings

`GemmaEmbedder` runs EmbeddingGemma-300m on the CPU. It applies the model's separate document and query prompts, batches documents, and normalises vectors after truncating them to the requested dimension (up to the model's native width).

```python
from wsw_brain.brain import GemmaEmbedder

embedder = GemmaEmbedder()
documents = embedder.embed_documents(["The pricing deck is due Friday."])
query = embedder.embed_query("When is the pricing deck due?")
```

The first use downloads the quantised ONNX model and tokenizer into `WSW_MODELS_DIR` (default: `models/`). Later runs reuse those files. `WSW_EMBED_REPO` chooses the model repository and `WSW_EMBED_DIM` sets the requested vector width. The tokenizer truncates input to 256 tokens by default; documents are processed in batches of 16. The adapter also accepts `threads`, `max_tokens`, and `batch_size` options, all positive integers. No hosted inference API is required.

Application code can call `get_embedder()` from `wsw_brain.brain` to use `WSW_EMBEDDER=gemma` (the default) or `WSW_EMBEDDER=hash`. Missing external weights trigger one attempt to resume the download. If model loading still fails, it logs the cause and returns `HashEmbedder` at the configured dimension. The selected instance is cached for the process lifetime, including a fallback instance; restart the process after changing provider settings or repairing a failed model download. Direct `GemmaEmbedder()` construction raises loading errors if fallback is not wanted.

Model and hash vectors use different embedding spaces. When changing providers, use a separate graph or rebuild stored embeddings; matching vector dimensions alone does not make them compatible.

## Hybrid meeting retrieval

`Retriever` combines full-text and vector matches with reciprocal-rank fusion, counting each utterance once per source. Questions mentioning a known speaker also search that person's utterances; phrases such as "just now" add the newest utterances. The results keep the meeting, speaker, timestamps, text, and retrieval source needed for citations, alongside the Cypher queries that produced the evidence. Fused scores are relative to the best result, which scores 1.0; they are not confidence probabilities.

With a running database and meetings indexed using the same embedder:

```python
from wsw_brain.brain import Retriever, get_embedder
from wsw_brain.config import settings
from wsw_brain.graph import GraphStore

config = settings()
store = GraphStore(config.falkordb_url, config.graph)
try:
    retriever = Retriever(store, get_embedder())
    hits, cypher = retriever.retrieve("What did Priya say about pricing?", k=5)
    # Pass meeting_id="..." to restrict every search source to one meeting.
finally:
    store.close()
```

Blank questions return no results. `k` must be a positive integer. A failed query embedder or search source is logged, while the remaining sources still contribute results. Speaker names are cached for 30 seconds. Vector compatibility checks sample at most two meetings per query and cache verdicts for ten minutes; confirmed incompatible meetings are excluded from vector results. These checks are best effort: unverified hits stay eligible, and they do not replace rebuilding embeddings when changing providers.

Run the ranking and database integration checks without downloading a model:

```bash
uv run --project apps/api pytest apps/api/tests/test_retrieve.py apps/api/tests/test_retrieve_graph.py -q
```

## Local text model calls

`OllamaLLM` implements text chat and tool calls using the existing `LLM` contract. Start a local model server with your chosen model available, then construct the adapter with its URL and model name. The existing `WSW_OLLAMA_URL` and `WSW_OLLAMA_MODEL` settings supply defaults:

```python
import asyncio

from wsw_brain.brain import OllamaLLM
from wsw_brain.config import settings

async def main():
    config = settings()
    model = OllamaLLM(config.ollama_url, config.ollama_model)
    result = await model.chat([{"role": "user", "content": "Reply with one word: ready"}])
    print(result.text)

asyncio.run(main())
```

`chat()` accepts tool schemas, JSON mode, temperature, and a token limit. Results include cleaned answer text, parsed `ToolCall` values, model/provider names, and latency. `assistant_tool_message` and `tool_result_message` in `brain.llm` preserve a tool exchange for subsequent calls; the adapter returns requested tools for the caller to execute.

Calls have bounded connection, read, and write timeouts. Models that explicitly reject the `think` option are retried once without it; unrelated HTTP errors are returned after one request. Network errors, unsuccessful HTTP responses, malformed responses, empty answers without tools, and invalid tool arguments raise `LLMError`. This adapter reports `supports_audio=False`.

Application code can use the cached `get_llm()` factory instead of constructing an adapter directly. `WSW_LLM_PROVIDER=gemini` selects the hosted adapter, `ollama` selects the configured local adapter without probing, and `fake` selects a deterministic offline responder. `auto` prefers Gemini when `GEMINI_API_KEY` is set, then checks the local model list for an exact model match before falling back to `fake`. The fallback quotes evidence lines such as `[u:m1:u00001] Priya: The deck is due Friday.` so local development remains deterministic.

`GeminiLLM` maps system, user, assistant, and tool messages to the Google GenAI content model. It supports JSON responses and function declarations, skips thought parts in responses, validates candidate and tool-call shapes, and retries once in compatibility mode if a served model rejects system instructions or JSON response configuration. Gemini text models report `supports_audio=False`; native audio remains a separate local runtime feature.

The transport tests require neither a running model server nor a model download:

```bash
uv run --project apps/api pytest apps/api/tests/test_llm.py -q
```

## Local graph database

Start Docker, then run:

```bash
docker compose up -d --wait falkordb
```

FalkorDB is available at `127.0.0.1:6379`, with its browser at <http://localhost:3000>. Both ports bind to this machine only. Database files are kept in the `falkordb_data` volume when the container stops. If you use Colima without making it your default Docker context, use `docker --context colima compose` for these commands.

The schema definitions in `apps/api/wsw_brain/graph/cypher.py` cover range, full-text, and vector indexes. To verify them against the running database:

```bash
uv run --project apps/api pytest apps/api/tests/test_graph_schema.py -q
```

These checks create and delete their own temporary graphs. They verify that reapplying indexes preserves existing records, and that full-text and vector searches return the expected utterances. Set `WSW_FALKORDB_URL` in the command environment to test a different server. The checks fail if the database is unavailable.

Stop the service with `docker compose stop falkordb`. Call `GraphStore.ensure_schema(embedder.dim)` when setting up the configured graph, before writing utterances with embeddings.
