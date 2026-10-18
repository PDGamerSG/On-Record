# ADR-0007: Demo mode in the web app

## Context

The web client expects a meeting API that "this repository does not include" yet (apps/web/src/api/mode.ts:3). No server in the repository answers `/api/health`, `/api/ask` or `/api/ask/voice` (docs/ARCHITECTURE.md:60-62). The interface still has to be usable and reviewable.

## Decision

`resolveMode()` decides once, before the first render, whether the UI talks to the API or to bundled demo data (apps/web/src/api/mode.ts:1-3). The `?demo=` query parameter or `VITE_DEMO` forces a mode; otherwise the app goes live only when `GET /api/health` returns JSON with a boolean `ok` within 2500 ms (apps/web/src/api/mode.ts:12-31). `api` is a proxy that routes each call to `demoApi` or `realApi` (apps/web/src/api/client.ts:107-110). `demoApi` serves two scripted meetings from memory, keeps writes in memory and answers questions by simple matching (apps/web/src/api/demo/demoApi.ts:1-3).

## Status

Accepted (retroactive)

## Consequences

Positive:

- The web app runs with no backend, so pages can be built and shown independently of the API.
- In demo mode the event hub opens no `EventSource` (apps/web/src/api/events.ts:41, apps/web/src/api/events.ts:61).

Negative:

- Today the meeting views always run on demo data (docs/ARCHITECTURE.md:62). Forcing live mode sends calls to routes no server provides.
- Demo answers are not grounded model answers; creating, uploading and spoken questions reject with 503 (apps/web/src/api/demo/demoApi.ts:373, apps/web/src/api/demo/demoApi.ts:395, apps/web/src/api/demo/demoApi.ts:439-440).
- Since PR #77 the only demo label left is the system status, "Demo data" (apps/web/src/components/shell/SystemStatus.tsx:116), so the mode is less visible.

## Alternatives

Not recorded in the repository.

## Sources

- apps/web/src/api/mode.ts:1-31
- apps/web/src/api/client.ts:107-110
- apps/web/src/api/demo/demoApi.ts:1-3
- apps/web/src/api/events.ts:41
- docs/ARCHITECTURE.md:60-62
