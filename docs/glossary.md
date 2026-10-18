# Glossary

Terms used across the On Record code and documentation, with the file that defines or uses each one. Line numbers are as of commit `8943885`. For how the parts fit together, see the [documentation index](README.md).

| Term | Meaning | Source |
| --- | --- | --- |
| Action item (commitment) | A concrete task someone committed to, with owner, free-text due date, status open or done | `apps/api/wsw_brain/contracts.py:129-130`; `apps/api/wsw_brain/brain/extract.py:34-35`; `apps/web/src/pages/CommitmentsPage.tsx:1-2` |
| Ask drawer | The voice-first question panel in the web app | `apps/web/src/components/ask/AskDrawer.tsx:1` |
| AskResult | The answer contract: answer, citations, actions, tool trace, Cypher, model, provider, session, timings, transcript | `apps/api/wsw_brain/contracts.py:328-346`; `apps/web/src/api/types.ts:119-131` |
| ASR / FileASR | Speech-to-text contract for clips or files (faster-whisper, Saaras) | `apps/api/wsw_brain/contracts.py:87-105` |
| Bulbul | Sarvam text-to-speech model (`bulbul:v3`) | `apps/api/wsw_brain/sarvam.py:14`; `apps/api/wsw_brain/sarvam.py:108-109` |
| Change point | A sample offset where the voice changes inside one VAD segment | `apps/api/wsw_brain/listen/speakers.py:283-303` |
| Decision | Something the group settled on; status `active` or `superseded`, with evidence and proposer | `apps/api/wsw_brain/contracts.py:127-128`; `apps/api/wsw_brain/brain/extract.py:31-33` |
| Demo mode | Web mode that serves bundled scripted meetings instead of the API | `apps/web/src/api/mode.ts:1-3`; `apps/web/src/api/demo/demoApi.ts:1-3` |
| DocChunk | A heading-aware document passage with a page range, cited as `[d:<doc_id>:cNNNN]` | `apps/api/wsw_brain/documents/split.py:62-70`; `apps/api/wsw_brain/documents/store.py:198`; `apps/api/wsw_brain/documents/answer.py:30-33` |
| Document AI (Sarvam Vision) | Sarvam digitisation jobs that turn PDF or image parts into page text | `apps/api/wsw_brain/documents/sarvam.py:1-6` |
| Document part | A slice of 10 pages or fewer sent as one Document AI job | `apps/api/wsw_brain/documents/split.py:38-51` |
| Embedding space check | Verifying that a meeting's stored vectors come from the current embedder | `apps/api/wsw_brain/brain/retrieve.py:124-129` |
| EmbeddingGemma | 300M-parameter ONNX text-embedding model run on the CPU, with query and document prompts | `apps/api/wsw_brain/brain/embed.py:18-19`; `apps/api/wsw_brain/brain/embed.py:43-46` |
| Energy VAD | The browser-side voice detector for hands-free questions, with no model | `apps/web/src/audio/vad.ts:1-2` |
| Event bus / BusEvent | In-process publish/subscribe of `{id, type, meeting_id, ts, data}` events | `apps/api/wsw_brain/events.py:1-15`; `apps/web/src/api/types.ts:171-186` |
| Evidence | Utterance ids that support an item or an answer (`EVIDENCED_BY`) | `apps/api/wsw_brain/contracts.py:144`; `apps/api/wsw_brain/graph/store.py:548` |
| FakeLLM | Deterministic offline model that quotes the first evidence line | `apps/api/wsw_brain/brain/llm.py:796-834` |
| FalkorDB | Graph database (Redis module) holding meetings, people, utterances and insights; run with Docker Compose | `docker-compose.yml:1-13` |
| GemmaClient | The PR #76 provider-neutral Gemma client (Ollama, Gemini REST, OpenAI-compatible), separate from apps/api/wsw_brain/brain/llm.py adapters | `apps/api/wsw_brain/brain/gemma.py:1-6`; `apps/api/wsw_brain/brain/gemma.py:81-82` |
| GraphStore | The only module that talks to FalkorDB; records `last_cypher` for "Why this answer" | `apps/api/wsw_brain/graph/store.py:1-13`; `apps/api/wsw_brain/graph/store.py:114-118` |
| HashEmbedder | Deterministic offline embedder using signed feature hashing of words and bigrams | `apps/api/wsw_brain/brain/embed.py:140-141` |
| Held part | A short, ambiguous speech part kept until a neighbouring speaker decides it | `apps/api/wsw_brain/listen/session.py:7-10` |
| Heuristic extraction | Cue-phrase fallback used when no model is usable | `apps/api/wsw_brain/brain/extract.py:599-605` |
| Hit / Citation | A retrieval result dict (utterance, meeting, speaker, times, text, score, `via`) | `apps/api/wsw_brain/contracts.py:132-133` |
| Hybrid retrieval | Full-text, vector, speaker and recency sources fused by reciprocal-rank fusion | `apps/api/wsw_brain/brain/retrieve.py:1-2`; `apps/api/wsw_brain/brain/retrieve.py:74-77` |
| IngestPipeline | Live ingest that writes listener utterances to the graph in batches, publishes events, extracts insights every N utterances and summarises ended meetings | `apps/api/wsw_brain/pipeline.py:1-10`; `apps/api/wsw_brain/pipeline.py:55` |
| Insights | Everything one extraction pass found: decisions, action items, topics, entities, mentions | `apps/api/wsw_brain/contracts.py:221-246` |
| ListenerOverloaded | Error raised when more than `max_queued_s` of audio waits for the worker | `apps/api/wsw_brain/listen/session.py:56-57` |
| LiveSession | Listener that turns an audio stream into speaker-attributed utterances on a worker thread | `apps/api/wsw_brain/listen/session.py:1-21`; `apps/api/wsw_brain/listen/session.py:101` |
| LLM provider | A text-model adapter: ollama, gemini, openai, sarvam or fake | `apps/api/wsw_brain/contracts.py:269`; `apps/api/wsw_brain/contracts.py:283-286` |
| llm_priority | Context marker that moves model work ahead of ordinary queued questions | `apps/api/wsw_brain/brain/llm.py:57-64` |
| Mayura / sarvam-translate | Sarvam translation models; Mayura detects the source language for its 11 languages | `apps/api/wsw_brain/sarvam.py:12-24`; `apps/api/wsw_brain/sarvam.py:78-82` |
| MeetingAgent | Orchestrator that retrieves evidence and asks the model for a grounded, cited answer | `apps/api/wsw_brain/brain/agent.py:1-6`; `apps/api/wsw_brain/brain/agent.py:27-28` |
| ModelGate | Per-endpoint limiter on concurrent model calls, with a priority queue | `apps/api/wsw_brain/brain/llm.py:67-76` |
| On Record | Product name, read from `/brand.json` by both the API and the web app | `brand.json:2`; `apps/api/wsw_brain/brand.py:1-3` |
| OnlineClusterer | Greedy online clustering of voice embeddings into tracks, with merging and carry-over between sessions | `apps/api/wsw_brain/listen/speakers.py:71-85` |
| Person | A named individual linked from speakers by `IS`, with id `slug(name)` | `apps/api/wsw_brain/graph/cypher.py:184-195`; `apps/api/wsw_brain/graph/text.py:40-42` |
| RRF (reciprocal-rank fusion) | Score = Σ 1/(k+rank) with k=60, normalised so the best hit is 1.0 | `apps/api/wsw_brain/brain/retrieve.py:16`; `apps/api/wsw_brain/brain/retrieve.py:29-65` |
| Saaras | Sarvam speech-recognition model (`saaras:v4`) for Indian and code-mixed speech | `apps/api/wsw_brain/listen/sarvam_asr.py:1-9`; `apps/api/wsw_brain/config.py:72` |
| Seconds vs epoch ms | Meeting-relative times are seconds; wall-clock times are epoch ms; event `ts` is epoch seconds | `apps/api/wsw_brain/contracts.py:10-11` |
| Session | `session_id` grouping Ask turns; history is kept in agent memory, or `Turn` nodes | `apps/api/wsw_brain/brain/agent.py:36`; `apps/api/wsw_brain/brain/agent.py:100-103`; `apps/api/wsw_brain/graph/cypher.py:591-603` |
| Smoke benchmark (gemma-smoke-v1) | Five-case structured-output corpus for checking Gemma JSON replies; "not a quality benchmark" | `benchmarks/gemma_smoke.json:2-3` |
| Speaker confidence | How sure the listener is about who spoke (not transcription confidence), 0-1 | `apps/web/src/api/types.ts:40`; `apps/api/wsw_brain/contracts.py:46` |
| Speaker label | Display form "Speaker N" of a track | `apps/api/wsw_brain/graph/text.py:86-88` |
| Speaker track | Meeting-scoped voice label `S1`, `S2`, … assigned by clustering | `apps/api/wsw_brain/contracts.py:42`; `apps/api/wsw_brain/listen/speakers.py:264` |
| SSE | Server-Sent Events stream at `/api/events` | `apps/api/wsw_brain/event_stream.py:1`; `apps/api/wsw_brain/event_stream.py:45-51` |
| Supersession | A later decision replacing an earlier one: `(new)-[:SUPERSEDES]->(old)`, with the old one marked superseded | `apps/api/wsw_brain/graph/store.py:461-466`; `apps/api/wsw_brain/graph/store.py:555-578` |
| Talkback / hands-free | Voice-question capture modes: hold, toggle, or VAD-triggered | `apps/web/src/components/ask/useVoiceQuestion.ts:1-4` |
| Topic / Entity / Mention | Short noun phrases and named things (product, customer, vendor, org, other) linked from utterances by `MENTIONS` | `apps/api/wsw_brain/brain/extract.py:27-29`; `apps/api/wsw_brain/graph/store.py:64`; `apps/api/wsw_brain/graph/store.py:653-665` |
| UNTRUSTED_NOTE | Prompt suffix telling the model to ignore instructions inside evidence | `apps/api/wsw_brain/brain/llm.py:35-39` |
| Utterance | One speaker turn from the listener: meeting id, sequence number, speaker track, start and end seconds, text, speaker confidence | `apps/api/wsw_brain/contracts.py:33-46` |
| Utterance id | `<meeting_id>:u<seq, 5 digits>`, cited as `[u:…]` | `apps/api/wsw_brain/contracts.py:67-70` |
| VAD (Silero) | Voice activity detection that finds speech segments; the Silero model is run through sherpa-onnx | `apps/api/wsw_brain/listen/session.py:665-680` |
