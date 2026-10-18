# Configuration

Every setting the backend, the web app and the tests read, with its default and the code that uses it. Settings marked *not read yet* are kept for parts of the application that later PRs will add. Setting them today has no effect.

## How settings are loaded

- **Backend.** `Settings` (`apps/api/wsw_brain/config.py`) reads environment variables, then the `.env` file at the repository root. An environment variable wins over the same name in `.env`. Copy [`.env.example`](../.env.example) to `.env` to start, and keep secrets there; `.env` is ignored by git.
  - Unknown names are ignored, so a misspelt variable is silently skipped.
  - Values are checked when settings are first read: for example, `WSW_EMBED_DIM=0` is rejected.
  - `settings()` is cached for the life of the process, so restart the server or script after changing a value. The model provider and embedder chosen from these settings are cached too.
  - The first call to `settings()` creates `WSW_DATA_DIR` and its `audio/` folder.
- **Web app.** Variables starting with `VITE_` are fixed into the bundle when `npm run dev` or `npm run build` starts. Set them in the shell or in `apps/web/.env.local`. `WSW_API_URL` is read only by the Vite dev server's config, so set it in the shell.

Some defaults in the code differ from the values in `.env.example`. The tables below list the code default and note where `.env.example` differs.

## Graph database and storage

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `WSW_FALKORDB_URL` | `falkor://127.0.0.1:6379` | FalkorDB connection URL. Use `falkors://` for TLS, and `falkor://default:<password>@<host>:<port>` for a hosted database | Document API, `scripts/seed_demo_meetings.py`, graph tests |
| `WSW_GRAPH` | `wsw_demo` | Name of the graph that holds meetings and documents | Document API, `scripts/seed_demo_meetings.py` |
| `WSW_DATA_DIR` | `data/` | Folder for runtime files; `audio/` inside it is created at startup | Created by `settings()`; *nothing else reads it yet* |
| `WSW_MODELS_DIR` | `models/` | Where downloaded model files are kept | `brain/embed.py`, `listen/factory.py` |

Both folder defaults are relative to the repository root.

## Text models

`WSW_LLM_PROVIDER` chooses the adapter that `get_llm()` returns (`brain/llm.py`):

- `gemini`, `sarvam`, `openai` and `ollama` use that adapter. Selecting `gemini`, `sarvam` or `openai` raises `LLMError` if its key or base URL is missing.
- `fake` gives deterministic offline answers that quote the evidence lines.
- `auto` (the default) uses Gemini if `GEMINI_API_KEY` is set, otherwise Sarvam if `SARVAM_API_KEY` is set. Otherwise it checks the local model server, using Ollama if `WSW_OLLAMA_MODEL` is installed there and the fake responder if not. If only OpenAI-compatible settings are present, `auto` refuses to guess; set `WSW_LLM_PROVIDER=openai`.

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `WSW_LLM_PROVIDER` | `auto` | `auto`, `gemini`, `sarvam`, `openai`, `ollama` or `fake` | `brain/llm.py` |
| `GEMINI_API_KEY` | unset | Google AI Studio key for the hosted Gemini API | `brain/llm.py` |
| `WSW_GEMINI_MODEL` | `gemma-4-26b-a4b-it` | Model name on the Gemini API | `brain/llm.py`, `brain/gemma.py` |
| `SARVAM_API_KEY` | unset | Sarvam key for Gemma 4 chat, Saaras speech recognition, Document AI, translation and speech. Keep it server-side | `brain/llm.py`, `listen/sarvam_asr.py`, document API |
| `WSW_SARVAM_BASE_URL` | `https://api.sarvam.ai` | Sarvam API origin | `brain/llm.py`, `listen/sarvam_asr.py`, document API |
| `WSW_SARVAM_MODEL` | `gemma4` | Chat model on Sarvam; any model your key can use | `brain/llm.py` |
| `WSW_OPENAI_BASE_URL` | unset | Base URL of an OpenAI-compatible `/v1/chat/completions` endpoint | `brain/llm.py` |
| `WSW_OPENAI_API_KEY` | unset | Bearer token for that endpoint, if it needs one | `brain/llm.py` |
| `WSW_OPENAI_MODEL` | `gemma-4-26b-a4b-it` | Model name on that endpoint | `brain/llm.py`, `brain/gemma.py` |
| `WSW_OLLAMA_URL` | `http://127.0.0.1:11434` | Local Ollama server | `brain/llm.py` |
| `WSW_OLLAMA_MODEL` | `gemma4:12b-it-qat` | Ollama model tag (install with `ollama pull gemma4:12b-it-qat`) | `brain/llm.py`, `brain/gemma.py` |
| `WSW_QUESTION_AUDIO` | `auto` | Which runtime will transcribe spoken questions: `auto`, `ollama` (Gemma 4 audio input) or `whisper` | *Not read yet* |

### Request queue

Each model endpoint gets a `ModelGate` that limits concurrent generations, so a busy local model stays responsive. The limits are read once per endpoint.

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `WSW_MODEL_SLOTS` | `2` | Generations that can run at the same time against one endpoint | `brain/llm.py` |
| `WSW_MODEL_MAX_WAITING` | `6` | Ordinary requests that can wait for a slot. Further requests fail straight away with "the language model is busy". Priority work is not capped | `brain/llm.py` |
| `WSW_MODEL_QUEUE_WAIT_S` | `90` | Seconds a request waits for a slot before it gives up | `brain/llm.py` |

## Embeddings

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `WSW_EMBEDDER` | `gemma` | `gemma` (EmbeddingGemma-300m on the CPU) or `hash` (offline word hashing, no download) | `brain/embed.py` |
| `WSW_EMBED_REPO` | `onnx-community/embeddinggemma-300m-ONNX` | Hugging Face repository the model is downloaded from | `brain/embed.py` |
| `WSW_EMBED_DIM` | `768` | Vector width. It must match the graph's vector indexes; changing it, or switching between `gemma` and `hash`, means rebuilding stored embeddings | `brain/embed.py` |

## Speech recognition

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `WSW_SARVAM_ASR_MODEL` | `saaras:v4` | Sarvam speech recognition model | `listen/sarvam_asr.py` |
| `WSW_SARVAM_ASR_MODE` | `transcribe` | `transcribe`, `translate` (to English), `verbatim`, `translit` or `codemix` | `listen/sarvam_asr.py` |
| `WSW_SARVAM_ASR_LANGUAGE` | `auto` | Language code such as `hi-IN`, or `auto` to detect it | `listen/sarvam_asr.py` |
| `WSW_ASR_MODEL` | `small` | faster-whisper model size or path for the listener | *Not read yet*; `FasterWhisperASR` takes it as an argument |
| `WSW_ASR_DEVICE` | `cpu` | Device for faster-whisper | *Not read yet* |
| `WSW_ASR_COMPUTE` | `int8` | faster-whisper compute type | *Not read yet* |
| `WSW_ASR_LANGUAGE` | `en` | Language passed to faster-whisper | *Not read yet* |
| `WSW_SPEAKER_MODEL` | `speaker_embedding_en.onnx` | Speaker embedding model for telling voices apart | `listen/factory.py` |
| `WSW_SPEAKER_THRESHOLD` | `0.55` | Voice similarity threshold (0 to 1) for matching a known speaker | `listen/factory.py` |
| `WSW_MAX_UTTERANCE_S` | `12` | Longest utterance the listener should produce, in seconds | *Not read yet*; `LiveSession` takes it as `max_utterance_s` |

## Documents

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `WSW_DOC_LANGUAGE` | `en-IN` | Document AI language when an upload doesn't name one | Document API |
| `WSW_DOC_PART_PAGES` | `10` | Pages per Document AI job (at most 10, the API limit) | Document API |
| `WSW_DOC_MAX_PAGES` | `100` | Largest upload, in pages | Document API |
| `WSW_DOC_MAX_MB` | `25` | Largest upload, in megabytes | Document API |
| `WSW_DOC_CONCURRENCY` | `3` | Document AI jobs run in parallel for one upload | Document API |

## Server

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `WSW_CORS_ORIGINS` | `*` (`.env.example`: empty) | Comma-separated origins allowed to call the API from another site. Empty adds no CORS headers, so only same-origin requests work; `*` allows any origin | `documents/app.py` |
| `WSW_EXTRACT_EVERY` | `6` | How often decisions and action items are extracted during a meeting | *Not read yet* |
| `WSW_SEED_DEMO` | `true` (`.env.example`: `false`) | Load the demo meetings automatically | *Not read yet*; `scripts/seed_demo_meetings.py` loads them by hand |

`.env.example` also lists `WSW_ADMIN_TOKEN`, `WSW_CREATE_LIMIT` and `WSW_ALLOWED_HOSTS` for the access controls of the upcoming meeting API. `Settings` doesn't define them yet, so they are ignored.

## Web app

| Variable | Default | What it controls | Read by |
| --- | --- | --- | --- |
| `VITE_API_BASE` | unset (same origin) | Origin of a separately hosted API, e.g. `https://api.example.com`. All REST, SSE and WebSocket URLs are built from it | `src/api/base.ts` |
| `VITE_DEMO` | unset | `1`/`true` forces the bundled demo data, `0`/`false` forces the API. Unset means the app checks `/api/health`. A `?demo=` query parameter overrides it | `src/api/mode.ts` |
| `WSW_API_URL` | `http://127.0.0.1:8000` | Where the dev server proxies `/api` and `/ws` | `apps/web/vite.config.ts` |

See [ARCHITECTURE.md](ARCHITECTURE.md#demo-mode-and-live-mode) for how the web app chooses between demo and live data.
