# ADR-0004: Provider-agnostic Gemma 4 text adapters behind contracts.LLM

## Context

The same Gemma 4 models can be reached locally through Ollama, through the Gemini API, through Sarvam, or through an OpenAI-compatible endpoint. Extraction, summaries, the assistant and document answers should not depend on which one is configured, and tests must run with no model at all.

## Decision

Callers depend on the `LLM` protocol in `contracts.py` (apps/api/wsw_brain/contracts.py:283-305). `brain/llm.py` implements it for Ollama, Gemini, OpenAI-compatible endpoints, Sarvam and a deterministic fake (apps/api/wsw_brain/brain/llm.py:1-3). `select_llm` picks one from `WSW_LLM_PROVIDER` without making inference requests: with `auto` it prefers Gemini when a key is set, then Sarvam, then probes the local Ollama model, then falls back to the fake (apps/api/wsw_brain/brain/llm.py:856-887). `get_llm()` caches the choice per process (apps/api/wsw_brain/brain/llm.py:890-895). Provider settings are in [CONFIGURATION.md](../CONFIGURATION.md).

## Status

Accepted (retroactive)

## Consequences

Positive:

- One tool-call exchange format is shared by every adapter (apps/api/wsw_brain/brain/llm.py:5-6).
- `auto` stays usable offline: a failed probe selects the fake rather than failing (apps/api/wsw_brain/brain/llm.py:879-887).
- Hosted credentials without an explicit provider raise an error instead of being used silently (apps/api/wsw_brain/brain/llm.py:875-878).

Negative:

- Capabilities differ per adapter (`supports_audio`, image support), so callers must check flags (apps/api/wsw_brain/contracts.py:289).
- A second, separate Gemma client exists in `brain/gemma.py` with its own `LLMError`, used only by the benchmark script and tests (apps/api/wsw_brain/brain/gemma.py:1-6, apps/api/wsw_brain/brain/gemma.py:24).

## Alternatives

README.md:240 recommends the cached `get_llm()` factory "instead of constructing an adapter directly". For the separate client, Ollama's native `/api/chat` endpoint was chosen over "an OpenAI compatibility layer" (apps/api/wsw_brain/brain/gemma.py:3-5). No other alternatives are recorded in the repository.

## Sources

- apps/api/wsw_brain/contracts.py:283-305
- apps/api/wsw_brain/brain/llm.py:1-6
- apps/api/wsw_brain/brain/llm.py:856-895
- apps/api/wsw_brain/brain/gemma.py:1-6
- README.md:240
