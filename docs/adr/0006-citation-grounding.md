# ADR-0006: Keep only citations to retrieved evidence

## Context

Answers are only useful if each statement can be traced to a transcript line or document passage. A model can cite an id it was never shown, or answer from memory.

## Decision

The assistant's system prompt asks for answers from the provided evidence only, with an exact `[u:<utterance_id>]` marker per factual statement, and tells the model to say so when the evidence does not answer the question (apps/api/wsw_brain/brain/agent.py:20-24). After generation, `_ground` removes every citation whose id is not among the retrieved hits and returns only the hits that were cited (apps/api/wsw_brain/brain/agent.py:148-163). If nothing remains, the answer becomes "I couldn't find supporting evidence in the meeting record." (apps/api/wsw_brain/brain/agent.py:19, apps/api/wsw_brain/brain/agent.py:80-81). Document answers apply the same rule to `[d:<chunk id>]` citations (apps/api/wsw_brain/documents/answer.py:4-5, apps/api/wsw_brain/documents/answer.py:154-160).

## Status

Accepted (retroactive)

## Consequences

Positive:

- Every citation the user sees points at a line that was actually retrieved for the question.
- The prompt also carries `UNTRUSTED_NOTE`, so transcript text is treated as data (apps/api/wsw_brain/brain/agent.py:24, apps/api/wsw_brain/brain/llm.py:36).

Negative:

- The check is on ids, not content: a valid citation can still sit next to a statement the line does not support.
- Removing invalid markers can leave statements with no citation in the answer text.
- Answer quality depends on retrieval recall (see [ADR-0002](0002-hybrid-retrieval-rrf.md)).

## Alternatives

Not recorded in the repository.

## Sources

- apps/api/wsw_brain/brain/agent.py:18-24
- apps/api/wsw_brain/brain/agent.py:80-81
- apps/api/wsw_brain/brain/agent.py:148-163
- apps/api/wsw_brain/documents/answer.py:4-5
- apps/api/wsw_brain/documents/answer.py:154-160
- README.md:269
