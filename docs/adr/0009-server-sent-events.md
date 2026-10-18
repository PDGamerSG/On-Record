# ADR-0009: Server-Sent Events for live updates

## Context

While a meeting runs, the browser needs new utterances, speaker merges, insights and listener status as they happen. These flow one way, from server to browser.

## Decision

Writers publish to an in-process event bus, and the Server-Sent Events (SSE) endpoint `GET /api/events` fans events out to browsers (apps/api/wsw_brain/events.py:1-3). `format_sse` writes the id on the `id:` line, the type on the `event:` line and only the payload on the `data:` line (apps/api/wsw_brain/routes/event_stream.py:20-23). A `: keep-alive` comment goes out after 15 s without events (apps/api/wsw_brain/routes/event_stream.py:16-17). The web client uses `EventSource` and reconnects with `?since_id=` (apps/web/src/api/events.ts:60-63). The event list is in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Status

Accepted (retroactive)

## Consequences

Positive:

- SSE runs over plain HTTP and the browser's `EventSource`, with no extra client library.
- The bus keeps the last 500 events for replay, so a reconnecting client can catch up from its last id (apps/api/wsw_brain/events.py:53-55).

Negative:

- The two sides disagree on the frame format: the client parses the `data:` line as the whole event, so "the two sides have to be reconciled before live mode can work" (docs/ARCHITECTURE.md:86-88).
- The only production publisher is the ingest pipeline, which no entry point constructs yet, so a running server publishes no events.
- The bus is in-process, so events do not cross server processes.

## Alternatives

Not recorded in the repository.

## Sources

- apps/api/wsw_brain/events.py:1-3
- apps/api/wsw_brain/routes/event_stream.py:16-23
- apps/web/src/api/events.ts:60-63
- docs/ARCHITECTURE.md:86-88
