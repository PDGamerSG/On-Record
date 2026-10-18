# ADR-0008: Limit concurrent model calls with ModelGate

## Context

Live extraction, end-of-meeting summaries, questions and document answers can all call the same model endpoint at once. A local model serves few requests in parallel, and an unbounded queue would leave callers waiting indefinitely. The settings comment states the aim: "These keep local inference responsive under concurrent clients." (apps/api/wsw_brain/config.py:50).

## Decision

`ModelGate` "limits concurrent generations per endpoint" for the adapters in `brain/llm.py` (apps/api/wsw_brain/brain/llm.py:1-3). Up to `slots` calls run at once; the rest wait in a heap ordered by priority, then arrival. Once `max_waiting` ordinary callers are queued, further ones fail at once, but work marked with `llm_priority()` is never refused. A caller still waiting after `wait_s` gets `LLMError` (apps/api/wsw_brain/brain/llm.py:67-76). There is one process-wide gate per endpoint key (apps/api/wsw_brain/brain/llm.py:157-164). Defaults are 2 slots, 6 waiting and 90 s (apps/api/wsw_brain/config.py:51-53).

## Status

Accepted (retroactive)

## Consequences

Positive:

- Load on a model endpoint is bounded and callers get a clear error instead of an open-ended wait.
- Important work moves ahead of ordinary questions (apps/api/wsw_brain/brain/llm.py:57-64).
- A slot is not lost when a waiter times out or is cancelled as it is granted (apps/api/wsw_brain/brain/llm.py:74-75).

Negative:

- Under load, ordinary questions fail fast with an error the client must handle.
- Limits are per process, so several server processes multiply the load on one endpoint.
- The separate `GemmaClient` in `brain/gemma.py` has no gate.

## Alternatives

Not recorded in the repository.

## Sources

- apps/api/wsw_brain/brain/llm.py:57-80
- apps/api/wsw_brain/brain/llm.py:157-164
- apps/api/wsw_brain/config.py:50-53
