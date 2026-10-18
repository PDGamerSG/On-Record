# HTTP API reference

This page lists every HTTP route that the Python backend (`apps/api/wsw_brain`) serves at commit `8943885`, the Server-Sent Events (SSE) stream, and the routes the web client calls that no server provides yet. The system overview is in [../ARCHITECTURE.md](../ARCHITECTURE.md); settings are in [../CONFIGURATION.md](../CONFIGURATION.md).

There are two separate FastAPI applications. Neither mounts the other's routes.

| App | Module | Serves | Source |
|---|---|---|---|
| Main API | `wsw_brain.app:app` | `/healthz`, `/api/status`, `/api/capabilities`, `/api/events`; `/api/agent/ask` only when built with an agent | `apps/api/wsw_brain/app.py:14-44` |
| Documents app | `wsw_brain.documents.app:app` | `/api/documents/*` only, with optional CORS (cross-origin resource sharing) | `apps/api/wsw_brain/documents/app.py:21-25` |

No other module defines routes. `apps/api/wsw_brain/ingest/pipeline.py` and `apps/api/wsw_brain/brain/gemma.py` contain no `APIRouter` or `@app` routes.

## OpenAPI schema

[openapi.json](openapi.json) is the OpenAPI 3.1 schema of the default main app, `wsw_brain.app:app`, generated from the running code. Regenerate it from the repository root with:

```bash
uv run --project apps/api python -c "import json; from wsw_brain.app import app; print(json.dumps(app.openapi(), indent=2))" > docs/api/openapi.json
```

What the schema does not contain:

- `POST /api/agent/ask`. The agent router is included only when `create_app()` is given a `MeetingAgent` (`apps/api/wsw_brain/app.py:19-20`). The module-level `app` is `create_app()` with no arguments (`apps/api/wsw_brain/app.py:44`), and no entrypoint passes an agent, so the route is absent from the default app and from `openapi.json`.
- `GET /healthz`, which is registered with `include_in_schema=False` (`apps/api/wsw_brain/app.py:22`).
- `/api/documents/*`, which belongs to the separate documents app. Print that app's schema with:

```bash
uv run --project apps/api python -c "import json; from wsw_brain.documents.app import app; print(json.dumps(app.openapi(), indent=2))"
```

## Running the apps

| App | Command (from the repository root) | Default address | Source |
|---|---|---|---|
| Main API | `uv run --project apps/api python -m wsw_brain.cli` (options `--host`, `--port`, `--reload`) | `127.0.0.1:8000` | `apps/api/wsw_brain/cli.py:21-31` |
| Documents app | `uv run --project apps/api uvicorn wsw_brain.documents.app:app --port 8000` | `127.0.0.1:8000` (uvicorn default host) | `apps/api/wsw_brain/documents/app.py:3` |

Both default to port 8000, so run them on different ports if you need both at once. The main API has no CORS middleware (`apps/api/wsw_brain/app.py:14-41`). The documents app adds CORS only when `WSW_CORS_ORIGINS` is non-empty (`apps/api/wsw_brain/documents/app.py:22-24`; see [../CONFIGURATION.md](../CONFIGURATION.md)). Neither app has authentication.

## Try it

With the main app running (`uv run --project apps/api python -m wsw_brain.cli`, port 8000), these are the responses recorded from commit `8943885`:

```bash
curl -s http://127.0.0.1:8000/healthz
# {"status":"ok"}

curl -s http://127.0.0.1:8000/api/status
# {"status":"ok","product":"On Record"}

curl -s http://127.0.0.1:8000/api/capabilities
# {"product":"On Record","api_version":"v1","features":["status","documents","events"]}

curl -sN -D - "http://127.0.0.1:8000/api/events?since_id=0"
# HTTP/1.1 200 OK, content-type: text/event-stream; charset=utf-8,
# cache-control: no-cache, x-accel-buffering: no. No frames arrive while nothing publishes events;
# after 15 s without events the stream sends ": keep-alive".

curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "content-type: application/json" \
  -d '{"question":"What did Priya commit to?"}' http://127.0.0.1:8000/api/agent/ask
# 404: the default app has no MeetingAgent, so the agent route is not mounted
```

`/api/capabilities` lists `documents` although this app does not serve `/api/documents/*`; those routes are on the documents app below.

## Main API routes

Status: Implemented, except `/api/agent/ask`, which is Partial (the route works when an agent is injected, as the tests do, but no entrypoint injects one).

| Method | Path | Request | Response | Errors | Source |
|---|---|---|---|---|---|
| GET | `/healthz` | none | `{"status": "ok"}` | none | `apps/api/wsw_brain/app.py:22-24` |
| GET | `/api/status` | none | `{"status": "ok", "product": <product name>}` | none | `apps/api/wsw_brain/app.py:26-28` |
| GET | `/api/capabilities` | none | `{"product", "api_version": "v1", "features": ["status", "documents", "events"]}`, plus `"agent"` when an agent is mounted | none | `apps/api/wsw_brain/app.py:30-39` |
| GET | `/api/events` | query `since_id` integer ≥ 0 (default 0), `meeting_id` string (optional) | `text/event-stream` (see [Server-Sent Events](#server-sent-events)) | 422 for `since_id < 0` (validation) or when the bus rejects the subscription | `apps/api/wsw_brain/event_stream.py:45-67` |
| POST | `/api/agent/ask` (agent mounted only) | JSON `AskRequest`: `question` 1-2000 chars, `session_id` 1-100 chars (default `"default"`), `meeting_id` ≤ 200 chars or null, `k` 1-20 (default 8) | JSON `AskResponse`: `answer`, `citations[]`, `actions[]`, `tool_trace[]`, `cypher[]`, `model`, `provider`, `session_id`, `timings`, `transcript?`, `transcript_provider?` | 422 validation. Exceptions from `MeetingAgent.ask` are not caught by the router; their status code is [unverified] | `apps/api/wsw_brain/brain/agent_api.py:13-48` |

`/api/capabilities` always lists `"documents"` (`apps/api/wsw_brain/app.py:32`), but the main app does not serve `/api/documents`. Clients should not read that feature flag as meaning the route exists on the same server.

## Documents app routes

All paths are under the `/api/documents` prefix (`apps/api/wsw_brain/documents/api.py:31`). Status: Implemented. Route order matters: `/status`, `/jobs` and `/search` are declared before `/{doc_id}`, so they are not captured as document ids.

| Method | Path | Request | Response | Errors | Source |
|---|---|---|---|---|---|
| GET | `/api/documents/status` | none | `sarvam_configured`, `digitiser`, `llm {provider, model}`, `embedder`, `part_pages`, `max_pages`, `max_mb`, `language` | none | `apps/api/wsw_brain/documents/api.py:124-138` |
| POST | `/api/documents/split` | multipart `file` | `filename`, `kind`, `pages`, `part_pages`, `parts[]`; does not call Sarvam | 413 file too large, 400 empty file, 400 `DocumentError` | `apps/api/wsw_brain/documents/api.py:141-156` |
| POST | `/api/documents` | multipart `file`, form `title` (default `""`), `language` (default `""`) | `{"job": <job view>, "pages", "parts"}`; ingestion continues as a background asyncio task | 413, 400, 400 `DocumentError`, 503 without `SARVAM_API_KEY` | `apps/api/wsw_brain/documents/api.py:159-194` |
| GET | `/api/documents/jobs` | query `status` (`running`, `done`, `failed`, optional), `limit` 1-100 (default 50) | list of job views | 422 validation | `apps/api/wsw_brain/documents/api.py:197-207` |
| GET | `/api/documents/jobs/{job_id}` | path `job_id` | job view, with the last 50 events | 404 no such job | `apps/api/wsw_brain/documents/api.py:210-215` |
| DELETE | `/api/documents/jobs/{job_id}` | path `job_id` | `{"deleted": true}` | 404 no such job, 409 job still running | `apps/api/wsw_brain/documents/api.py:218-226` |
| GET | `/api/documents` | none | list of document dicts | 503 graph database unavailable | `apps/api/wsw_brain/documents/api.py:229-231` |
| GET | `/api/documents/search` | query `q` (required), `doc_id` (optional), `k` (default 8, clamped to 1-20) | list of chunk hits | 503 graph database unavailable | `apps/api/wsw_brain/documents/api.py:234-237` |
| POST | `/api/documents/ask` | JSON `AskBody`: `question` 1-2000 chars, `doc_id?`, `k` 1-20 (default 6), `language` matching `^[a-z]{2,3}-IN$`, `include_meetings` boolean | answer dict, plus `translated_answer`, `answer_language`, `translated_by` or `translation_error`, and `timings.translate_ms` when a translation is requested | 422 validation, 503 graph unavailable, 503 translation requested without a Sarvam key. A failed or timed-out translation is not an error: the answer returns with `translation_error` | `apps/api/wsw_brain/documents/api.py:59-66`, `apps/api/wsw_brain/documents/api.py:240-262` |
| POST | `/api/documents/speak` | JSON `SpeakBody`: `text` 1-5000 chars, `language` (default `en-IN`), `speaker` `^[a-z_]{2,40}$` (default `priya`), `pace` 0.5-2.0 | `audio/wav` body, header `x-spoken-by: Sarvam Bulbul v3` | 422 validation, 400 `ValueError`, 502 `SarvamSpeechError`, 503 without a Sarvam key | `apps/api/wsw_brain/documents/api.py:69-73`, `apps/api/wsw_brain/documents/api.py:265-274` |
| GET | `/api/documents/{doc_id}` | path `doc_id` | document with its chunks | 404 no such document, 503 graph unavailable | `apps/api/wsw_brain/documents/api.py:277-282` |
| DELETE | `/api/documents/{doc_id}` | path `doc_id` | `{"deleted": <bool>}` | 503 graph unavailable | `apps/api/wsw_brain/documents/api.py:285-287` |

Error bodies use FastAPI's `{"detail": ...}` shape. The 413 and 400 upload checks are in `apps/api/wsw_brain/documents/api.py:114-121`; the 503 for a missing key in `apps/api/wsw_brain/documents/api.py:86` (digitiser) and `apps/api/wsw_brain/documents/api.py:94` (translation and speech); graph errors become 503 in `apps/api/wsw_brain/documents/api.py:107-111`.

Ingestion jobs live in an in-process dict (`apps/api/wsw_brain/documents/api.py:51`), so they are lost on restart and are not shared between worker processes. Finished jobs older than `JOB_TTL_S = 3600` seconds are pruned (`apps/api/wsw_brain/documents/api.py:32`, `apps/api/wsw_brain/documents/api.py:290-294`).

## Server-Sent Events

`GET /api/events` on the main API streams events from the in-process `EventBus`. Status: Partial. The endpoint and bus work and are tested, but the only production publisher, `IngestPipeline` in `apps/api/wsw_brain/ingest/pipeline.py`, is not constructed by any entrypoint, so a running server publishes no events.

### Query parameters

| Parameter | Type | Default | Meaning | Source |
|---|---|---|---|---|
| `since_id` | integer ≥ 0 | 0 | Replay buffered events with an id greater than this before streaming new ones | `apps/api/wsw_brain/event_stream.py:48` |
| `meeting_id` | string | none | Deliver only events for this meeting | `apps/api/wsw_brain/event_stream.py:49` |

The bus keeps the last 500 events for replay and gives each subscriber a queue of 2000; when a subscriber's queue is full, new events for it are dropped (`apps/api/wsw_brain/events.py:53-55`, `apps/api/wsw_brain/events.py:64`, `apps/api/wsw_brain/events.py:108-109`).

### Response headers

`Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no` (`apps/api/wsw_brain/event_stream.py:59-66`).

### Frame format

Each event is one frame (`apps/api/wsw_brain/event_stream.py:20-23`):

```text
id: 42
event: meeting.started
data: {"title":"Planning"}

```

- `id:` is the event id and `event:` is the event type.
- `data:` carries only the event's `data` object, as compact JSON. The envelope fields `type`, `meeting_id` and `ts` are not in the `data` line. Read the type from the SSE event name and the id from `lastEventId`.
- The test pins this format (`apps/api/tests/test_app.py:63-67`).

The full envelope on the bus is `{"id": int, "type": str, "meeting_id": str | null, "ts": float, "data": {...}}`, with `ts` in epoch seconds (`apps/api/wsw_brain/events.py:3`).

### Keep-alive and disconnect

The stream polls its queue every `QUEUE_POLL_S = 1.0` seconds and sends the comment line `: keep-alive` after `KEEP_ALIVE_S = 15.0` seconds without events (`apps/api/wsw_brain/event_stream.py:16-17`, `apps/api/wsw_brain/event_stream.py:32-38`). The loop stops when the client disconnects, and the subscription is closed (`apps/api/wsw_brain/event_stream.py:31`, `apps/api/wsw_brain/event_stream.py:41-42`).

### Event types

From the docstring in `apps/api/wsw_brain/events.py:5-14`:

| Event type | `data` payload |
|---|---|
| `meeting.started` | MeetingSummary |
| `meeting.ended` | MeetingSummary |
| `utterance.created` | Utterance (graph dict, see `contracts.UtteranceOut`) |
| `speaker.merged` | `{"from": track, "to": track}` |
| `speaker.named` | `{"track": str, "name": str, "person_id": str}` |
| `insight.created` | `{"kind": "decision" \| "action_item" \| "topic", "item": {...}}` |
| `action.updated` | ActionItem dict |
| `graph.write` | `{"utterances": int, "ms": float, "totals": {label: count}}` |
| `listener.status` | `{"state": "listening" \| "processing" \| "idle" \| "error", "lag_s": float, "detail": str}` |

### Known client mismatch

The web client parses the `data` line as the whole envelope and reads `id` and `type` from it (`apps/web/src/api/events.ts:92-96`). Because the server sends only the payload there, handlers that filter on `e.type` never match, and the client's replay cursor does not advance. The client reconnects with `?since_id=` (`apps/web/src/api/events.ts:62`). [../ARCHITECTURE.md](../ARCHITECTURE.md) notes that the two sides still have to be reconciled before live mode can work.

## Client routes not served yet

`apps/web/src/api/client.ts` calls these routes in live mode. No module in `apps/api/wsw_brain` defines them; in demo mode the client uses bundled data instead (`apps/web/src/api/client.ts:107-110`).

| Method | Path | Request sent by the client | Status | Source |
|---|---|---|---|---|
| GET | `/api/health` | none | Planned | `apps/web/src/api/client.ts:58` |
| GET | `/api/stats` | none | Planned | `apps/web/src/api/client.ts:59` |
| GET | `/api/meetings` | none | Planned | `apps/web/src/api/client.ts:60` |
| POST | `/api/meetings` | JSON `{title}` | Planned | `apps/web/src/api/client.ts:61` |
| GET | `/api/meetings/{id}` | path | Planned | `apps/web/src/api/client.ts:62` |
| POST | `/api/meetings/{id}/end` | path | Planned | `apps/web/src/api/client.ts:63` |
| DELETE | `/api/meetings/{id}` | path | Planned | `apps/web/src/api/client.ts:64` |
| GET | `/api/meetings/{id}/utterances` | query `after_seq` | Planned | `apps/web/src/api/client.ts:65-66` |
| POST | `/api/meetings/upload` | multipart `file`, `title`, `pace` (`fast` or `realtime`) | Planned | `apps/web/src/api/client.ts:67-73` |
| GET | `/api/meetings/{id}/audio` | path (used as a media URL) | Planned | `apps/web/src/api/client.ts:74` |
| PATCH | `/api/meetings/{id}/speakers/{track}` | JSON `{name}` | Planned | `apps/web/src/api/client.ts:75-76` |
| GET | `/api/action-items` | query `status`, `owner`, `meeting_id` | Planned | `apps/web/src/api/client.ts:77-78` |
| PATCH | `/api/action-items/{id}` | JSON `{status}` | Planned | `apps/web/src/api/client.ts:79-80` |
| GET | `/api/decisions` | query `meeting_id` | Planned | `apps/web/src/api/client.ts:81-82` |
| GET | `/api/people` | none | Planned | `apps/web/src/api/client.ts:83` |
| GET | `/api/who-knows` | query `topic` | Planned | `apps/web/src/api/client.ts:84` |
| GET | `/api/graph` | query `meeting_id`, `utterance_ids` (comma-separated) | Planned | `apps/web/src/api/client.ts:85-90` |
| GET | `/api/search` | query `q`, `meeting_id` | Planned | `apps/web/src/api/client.ts:91-92` |
| POST | `/api/ask` | JSON `{session_id, question, meeting_id}` | Planned | `apps/web/src/api/client.ts:93-94` |
| POST | `/api/ask/voice` | multipart `audio` (`question.wav`), `session_id`, `meeting_id` | Planned | `apps/web/src/api/client.ts:95-101` |
| GET | `/api/sessions/{id}` | path | Planned | `apps/web/src/api/client.ts:102` |
| WebSocket | `/ws/meetings/{id}/audio` | audio stream | Planned | `apps/web/src/api/client.ts:112-118` |

The client's `POST /api/ask` is the nearest match to the server's `POST /api/agent/ask` (`apps/api/wsw_brain/brain/agent_api.py:38-40`), but the paths differ and the server route is mounted only with an injected agent. No server has a voice route. The same gaps are listed in [../ARCHITECTURE.md](../ARCHITECTURE.md) under "What is not in the repository yet".
