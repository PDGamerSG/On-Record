# On Record

A meeting assistant that connects what was said to the person who said it.

This repository is being assembled in feature-sized PRs from [Who Said What Brain](https://github.com/Hydra-Of-Malice/hack-october-who-said-what-brain). It currently includes shared Python contracts, graph storage and queries, audio decoding and transcription, text embeddings, hybrid meeting retrieval, local and hosted text model adapters, the web interface, and a small HTTP entrypoint.

The display name lives in `brand.json`. `.env.example` lists the configuration the application will use; keep local values in an ignored `.env` file.

See [the source notes](docs/UPSTREAM.md) for the original snapshot and attribution. The code is licensed under [Apache 2.0](LICENSE).

## Web app

The web interface lives in `apps/web`. It has a landing page with a 3D turntable pressed from a demo meeting, and the app: meetings, the meeting room (speaker lanes, transcript and extracted decisions and action items), commitments, decisions, people, the graph, and spoken questions. It needs Node 20.19 or 22.12 and later. Until the HTTP server arrives it runs on two bundled demo meetings.

```bash
cd apps/web
npm ci
npm run dev        # http://localhost:5173
```

`npm run build` type-checks and builds; `npm run lint` runs oxlint. [`apps/web/README.md`](apps/web/README.md) lists the routes and how to rebuild the 3D assets, and [`docs/DESIGN.md`](docs/DESIGN.md) holds the design notes.

## Python setup

Install [uv](https://docs.astral.sh/uv/), then run from the repository root:

```bash
uv sync --project apps/api --frozen
uv run --project apps/api python -c "from wsw_brain.brand import product_name; print(product_name())"
```

The package uses Python 3.12. It provides configuration, shared data contracts, an in-process event bus, and the HTTP application entrypoint.

## HTTP API

Start the dependency-free API shell locally with:

```bash
uv run --project apps/api python -m wsw_brain
```

The module launcher binds to `127.0.0.1:8000` by default; pass `--host`, `--port`, or `--reload` for local development overrides.

`GET /healthz` returns `{"status":"ok"}` for process health checks. `GET /api/status` returns the product identity without connecting to FalkorDB or loading a model. Feature routes can be mounted on the same app as they are added.

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

`OpenAICompatLLM` targets OpenAI-compatible `/v1/chat/completions` endpoints. Set `WSW_LLM_PROVIDER=openai`, `WSW_OPENAI_BASE_URL`, `WSW_OPENAI_API_KEY` when required by the endpoint, and `WSW_OPENAI_MODEL`. It preserves assistant tool-call IDs and tool results, supports JSON response mode, validates completion and function-call shapes, and reports bounded network errors. The adapter does not claim native audio support.

The transport tests require neither a running model server nor a model download:

```bash
uv run --project apps/api pytest apps/api/tests/test_llm.py -q
```

## Gemma 4 and speech through Sarvam

`SarvamLLM` calls Gemma 4 31B (`gemma4`) through Sarvam's OpenAI-compatible `/v2/chat/completions` endpoint, with the `api-subscription-key` header. Set `SARVAM_API_KEY` in `.env` and either `WSW_LLM_PROVIDER=sarvam`, or leave `auto`, which selects Sarvam when the key is set and no Gemini key is. `WSW_SARVAM_MODEL` can name another model your key can use (`GET https://api.sarvam.ai/v2/models`), such as `sarvam-105b`. Sarvam documents that `gemma4` returns blank output when `response_format` is combined with a JSON instruction in the prompt, so in JSON mode the adapter only sends `response_format` when no message already asks for JSON.

`SaarasASR` (`wsw_brain.listen`) transcribes Indian-language and code-mixed speech with Saaras v4. It follows the same `ASR` contract as `FasterWhisperASR`, so the listener can use it for meetings held in Hindi, Kannada, Tamil, Hinglish and other languages. Each request covers at most 28 seconds of audio, within the 30-second REST limit. Pass speaker names and product terms as `keyterms` to improve recognition of those words. `WSW_SARVAM_ASR_LANGUAGE=auto` detects the language. `WSW_SARVAM_ASR_MODE` selects `transcribe`, `translate` (to English), `verbatim`, `translit` or `codemix`. Saaras returns no transcript confidence, so the adapter reports its language-identification probability.

`SarvamSpeech` (`wsw_brain.sarvam`) translates answers with Sarvam's translation models and reads them aloud with Bulbul v3. Citation markers are removed first, so they are neither translated nor spoken.

## Documents with Sarvam Document AI

Teams also decide things in contracts, specs and policies. The `wsw_brain.documents` package adds those files to the same graph as the meetings:

1. **Split.** Sarvam Document AI accepts at most 10 pages per job. `split_document` cuts a PDF into consecutive parts of up to 10 pages; a ZIP of page images is split the same way. A PNG or JPEG image is processed as a single page. Each part records the source pages it covers.
2. **Digitise.** `SarvamDocAI` sends the parts to Sarvam Vision in parallel, waits for each job, and reads the per-page layout blocks. Running headers and page numbers are dropped, and tables become `cell | cell` rows. Page numbers are shifted back to the original document.
   For an uploaded PNG or JPEG (a whiteboard photo, slide or chart), Gemma 4 31B also looks at the image and describes what the text alone misses: boxes and arrows, chart trends, owners and dates. The description is stored as a section of that page, so it can be searched and cited.
3. **Chunk and embed.** Passages follow section headings, keep their page range, and are embedded with the configured embedder (EmbeddingGemma by default).
4. **Store and search.** `(:Document)-[:HAS_CHUNK]->(:DocChunk)` nodes get their own full-text and vector indexes. `DocumentRetriever` fuses both with reciprocal-rank fusion. The full-text query uses Latin-script words, so words in Indian scripts (for example a Hindi question about a Hindi contract) are matched by a substring search over the passages instead.
5. **Ask.** `answer_question` has Gemma 4 answer only from retrieved passages and cite them as `[d:<chunk id>]`. Citations to passages that were not retrieved are removed. Each document also gets a short Gemma 4 summary of its deadlines, owners and obligations.
6. **Check against meetings.** With `include_meetings`, the question also searches meeting transcripts, using the question itself plus the headings and text of the top passages. Gemma 4 cites meeting lines as `[u:<utterance id>]` with speaker, meeting and date. It says when a newer meeting changed an amount, date, owner or decision that a document states.

Run the document API on its own until the main server is added. With FalkorDB running and `SARVAM_API_KEY` set:

```bash
uv run --project apps/api uvicorn wsw_brain.documents.app:app --port 8000
cd apps/web && npm run dev    # the Documents page proxies /api to port 8000
```

| Route | Purpose |
| --- | --- |
| `POST /api/documents/split` | Show how an upload would be split, without calling Sarvam |
| `POST /api/documents` | Upload (`file`, optional `title`, `language` such as `hi-IN`); returns a job |
| `GET /api/documents/jobs/{id}` | Job progress: split, each digitised part, chunk, embed, store, summary |
| `GET /api/documents`, `GET/DELETE /api/documents/{id}` | List, read (with chunks) and delete documents |
| `GET /api/documents/search?q=` | Fused full-text and vector passage search |
| `POST /api/documents/ask` | Gemma 4 answer with page citations; `include_meetings` adds meeting lines; `language` (e.g. `kn-IN`) adds a translation |
| `POST /api/documents/speak` | Read text aloud with Bulbul v3 (`audio/wav`) |
| `GET /api/documents/status` | Configured digitiser, model, embedder and limits |

To try the meeting check with the bundled demo data, load the two demo meetings and generate a 12-page pricing policy. The policy still states the Starter terms that the later demo meeting changed. Its 12 pages are sent to Document AI as two parts:

```bash
uv run --project apps/api python scripts/seed_demo_meetings.py
uv run --project apps/api python scripts/make_demo_document.py    # writes data/kitepost-pricing-policy.pdf
```

Upload the PDF on the Documents page. Then ask "What does the Starter plan cost?" with meetings included.

`WSW_DOC_PART_PAGES` (at most 10), `WSW_DOC_MAX_PAGES`, `WSW_DOC_MAX_MB`, `WSW_DOC_CONCURRENCY` and `WSW_DOC_LANGUAGE` control the limits and the Document AI language. Upload jobs are tracked in memory by the serving process.

The document, Sarvam and speech tests use mock transports and a disposable graph. They make no Sarvam calls and download no models:

```bash
uv run --project apps/api pytest apps/api/tests/test_documents_split.py apps/api/tests/test_documents_sarvam.py \
  apps/api/tests/test_documents_ingest.py apps/api/tests/test_documents_api.py apps/api/tests/test_sarvam_speech.py \
  apps/api/tests/test_sarvam_asr.py -q
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
