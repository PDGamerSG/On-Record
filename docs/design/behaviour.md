# Behaviour diagrams

This document shows how the main flows of On Record behave at run time, as the code stands at commit `8943885`. It covers sequence diagrams, activity diagrams (drawn as Mermaid flowcharts) and state diagrams. Each diagram has a status note:

- **Implemented**: the flow runs end to end from a route or entrypoint in the repository.
- **Partial**: the code exists but is not wired end to end. The note says what is missing.
- **Planned**: only the web client, docs or contracts expect it.

The structure behind these flows is in the [software design specification](SDS.md) and the [data model](data-model.md). Requirement IDs are in the [SRS](../requirements/SRS.md). The typed meeting Ask sequence is already drawn in [docs/ARCHITECTURE.md, "Asking a question"](../ARCHITECTURE.md#asking-a-question) and is not repeated here.

## Sequence diagrams

### Meeting capture

**Status: Partial.** `LiveSession` and `IngestPipeline` work together in tests, but no entrypoint builds the pipeline and no HTTP or WebSocket route feeds a listener. The web client streams to `/ws/meetings/{id}/audio`, which no server in the repository serves. `MeetingAgent` and the meeting routes (`/api/meetings…`) are also missing.

*Sequence view: audio from a listener becomes utterances, graph writes, bus events and extracted insights, as the classes are wired at `8943885`.*

```mermaid
sequenceDiagram
    autonumber
    participant Web as Web client (mic.ts)
    participant LS as LiveSession (worker thread)
    participant IP as IngestPipeline (writer thread)
    participant Emb as Embedder
    participant GS as GraphStore (FalkorDB)
    participant Bus as EventBus
    participant Ex as Extractor
    Note over Web,LS: Planned: no server serves WebSocket /ws/meetings/{id}/audio
    Web-)LS: PCM16 frames, feed_pcm16()
    LS->>LS: queue 1 s pieces (ListenerOverloaded past max_queued_s)
    LS->>LS: VAD, speaker attribution, ASR transcribe
    LS-)IP: on_utterance(Utterance)
    IP->>IP: queue, batch every flush_interval_s or batch_size
    IP->>Emb: embed utterance texts
    Emb-->>IP: vectors (or None: text kept)
    IP->>GS: write_utterances (UNWIND batch, retried)
    IP-)Bus: utterance.created, graph.write
    alt extract_every new utterances
        IP-)Ex: _scheduled_extraction on the asyncio loop
        Ex->>GS: get_meeting, list_decisions
        Ex->>Ex: extract_with_meta (model, or heuristic fallback)
        Ex->>GS: write_insights (repeats dropped)
        Ex-)Bus: insight.created per decision, action item, topic
    end
    LS-)IP: on_speaker_merged (queued behind earlier utterances)
    IP->>GS: merge_speakers
    IP-)Bus: speaker.merged
```

Sources: apps/web/src/api/client.ts:112-118; apps/api/wsw_brain/listen/session.py:196-222, apps/api/wsw_brain/listen/session.py:386-396, apps/api/wsw_brain/listen/session.py:526-547, apps/api/wsw_brain/listen/session.py:562-593; apps/api/wsw_brain/pipeline.py:118-149, apps/api/wsw_brain/pipeline.py:251-318, apps/api/wsw_brain/pipeline.py:328-361, apps/api/wsw_brain/pipeline.py:373-447; apps/api/wsw_brain/brain/extract.py:683-722. `IngestPipeline` is only constructed in apps/api/tests/test_pipeline.py:142; README.md:346 says no HTTP route starts it.

Ending a meeting (`IngestPipeline.end_meeting`) flushes the queue, sets the meeting to `ended`, publishes `meeting.ended`, then runs the final extraction and the summary in the background and publishes a second `meeting.ended` with the summary (apps/api/wsw_brain/pipeline.py:186-240). It has the same status: no route calls it.

### Spoken question

**Status: Planned.** The web client records the question and posts it, but no server route answers `POST /api/ask/voice`. The typed route the agent does have is `POST /api/agent/ask`, and it exists only when a `MeetingAgent` is injected into `create_app`, which the module-level app does not do.

*Sequence view: a spoken question from the Ask drawer; the dashed box marks the steps that have no server route.*

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Drawer as AskDrawer (web)
    participant Rec as question.ts recorder
    participant Srv as "Server: POST /api/ask/voice"
    participant Speech as Browser speechSynthesis
    User->>Drawer: hold to speak
    Drawer->>Rec: record microphone
    Rec-->>Drawer: 16 kHz PCM16 WAV, at most 30 s
    Drawer->>Srv: askVoice(session_id, wav, meeting_id)
    rect rgba(128,128,128,0.15)
        Note over Srv: No route in the repository. No server-side speech to text is wired
        Srv-->>Drawer: transcript and answer (expected by the client)
    end
    Drawer->>Speech: speak the answer (optional)
    User->>Drawer: barge in
    Drawer->>Speech: cancel
```

Sources: apps/web/src/audio/question.ts:1-6; apps/web/src/api/client.ts:95-100; apps/web/src/components/ask/AskDrawer.tsx:157-195, apps/web/src/components/ask/AskDrawer.tsx:219-268; apps/web/src/components/ask/speech.ts:1-5; apps/api/wsw_brain/brain/agent_api.py:38-40; apps/api/wsw_brain/app.py:19-20, apps/api/wsw_brain/app.py:44.

### Document ingest

**Status: Implemented** in the documents app (`apps/api/wsw_brain/documents/app.py`). Jobs live in process memory only, so they are lost on restart.

*Sequence view: an upload starts a background ingestion job that the client polls.*

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as "POST /api/documents"
    participant Job as IngestJob (memory)
    participant Ing as DocumentIngestor
    participant DocAI as Sarvam Document AI
    participant Gemma as LLM (vision, summary)
    participant Emb as Embedder
    participant DS as DocumentStore (FalkorDB)
    Client->>API: multipart file, title, language
    API->>API: size check, plan() split into parts
    API->>Job: create (status running)
    API-)Ing: asyncio task: ingest()
    API-->>Client: job view, pages, parts
    par each part, up to doc_concurrency at once
        Ing->>DocAI: digitise(part)
        DocAI-->>Ing: pages
        opt image part and the model takes images
            Ing->>Gemma: describe_image
            Gemma-->>Ing: visual description
        end
    end
    Ing->>Ing: chunk pages
    Ing->>Emb: embed_documents(chunks)
    Ing->>DS: ensure_schema (once), write_document
    opt summarise
        Ing->>Gemma: summarise_document
        Ing->>DS: set_summary
    end
    Ing-->>Job: result, status done (or failed with error)
    loop until done or failed
        Client->>API: GET /api/documents/jobs/{id}
        API-->>Client: job view with progress events
    end
```

Sources: apps/api/wsw_brain/documents/api.py:35-51, apps/api/wsw_brain/documents/api.py:91-121, apps/api/wsw_brain/documents/api.py:159-215; apps/api/wsw_brain/documents/ingest.py:69-75, apps/api/wsw_brain/documents/ingest.py:87-160, apps/api/wsw_brain/documents/ingest.py:186-190; apps/api/wsw_brain/documents/app.py:25.

### Document Ask with translation and speech

**Status: Implemented** in the documents app. Translation and speech need `SARVAM_API_KEY`; without it those routes return 503. Speech is a separate request, made by the client after the answer arrives.

*Sequence view: a document question answered in English, translated when another Indian language is asked for, then read aloud on request.*

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Ask as "POST /api/documents/ask"
    participant Ret as DocumentRetriever
    participant MR as "Meeting Retriever (optional)"
    participant LLM as LLM
    participant Sv as SarvamSpeech
    participant Speak as "POST /api/documents/speak"
    Client->>Ask: question, doc_id, k, language, include_meetings
    Ask->>Ret: retrieve(question, k, doc_id)
    opt include_meetings
        Ask->>MR: meeting lines (failure ignored)
    end
    alt no passages and no meeting lines
        Ask-->>Ask: fixed answer, no model call
    else evidence found
        Ask->>LLM: chat(passages, question)
        LLM-->>Ask: answer with citations (unknown ids removed)
    end
    opt language is not en-IN
        Ask->>Sv: translate(answer, language), 20 s timeout
        Sv-->>Ask: translated_answer, or translation_error
    end
    Ask-->>Client: answer, citations, timings
    Client->>Speak: text, language, speaker, pace
    Speak->>Sv: speak (citations stripped, Bulbul v3)
    Sv-->>Speak: WAV clips joined
    Speak-->>Client: audio/wav
```

Sources: apps/api/wsw_brain/documents/api.py:56, apps/api/wsw_brain/documents/api.py:91-95, apps/api/wsw_brain/documents/api.py:240-274; apps/api/wsw_brain/documents/answer.py:118-167; apps/api/wsw_brain/sarvam.py:34-38, apps/api/wsw_brain/sarvam.py:78-130, apps/api/wsw_brain/sarvam.py:156-158.

## Activity diagrams

These are UML activity views drawn as Mermaid flowcharts.

### Extraction cycle

**Status: Partial.** The cycle is exercised by tests (apps/api/tests/test_pipeline.py:211), but it only runs inside `IngestPipeline`, which no entrypoint builds.

*Activity view: one scheduled extraction of a meeting, from the trigger to published insights.*

```mermaid
flowchart TD
    A([Batch written]) --> B{"new utterances since last extraction >= extract_every and none scheduled?"}
    B -- no --> Z([Wait for the next batch])
    B -- yes --> C[Mark scheduled, take the meeting's extract_lock]
    C --> D[Load meeting detail and all decisions]
    D --> E{Pending utterances?}
    E -- no --> R
    E -- yes --> F["Take next chunk of MAX_NEW_PER_CALL, add context up to WINDOW"]
    F --> G{LLM provider is fake?}
    G -- yes --> H[Heuristic extraction]
    G -- no --> I["chat(json_mode) under llm_priority"]
    I --> J{LLMError?}
    J -- yes --> H
    J -- no --> K{Valid JSON object?}
    K -- no --> H
    K -- yes --> L["insights_from_json (map supersedes to earlier decisions)"]
    H --> M[Drop repeats of items already held]
    L --> M
    M --> N[write_insights to the graph]
    N --> O[Publish insight.created per item]
    O --> P[Advance extracted_seq]
    P --> E
    R[Release lock] --> S{More arrived meanwhile?}
    S -- yes --> C
    S -- no --> Z
```

Sources: apps/api/wsw_brain/pipeline.py:373-447, apps/api/wsw_brain/pipeline.py:478-547; apps/api/wsw_brain/brain/extract.py:260, apps/api/wsw_brain/brain/extract.py:348, apps/api/wsw_brain/brain/extract.py:683-757.

### Document ingestion

**Status: Implemented.**

*Activity view: the steps of `DocumentIngestor.ingest` and how a job ends.*

```mermaid
flowchart TD
    A([Upload received]) --> B{"Within doc_max_mb and not empty?"}
    B -- no --> X1["HTTP 413 or 400"]
    B -- yes --> C["plan(): split into parts"]
    C --> D{DocumentError?}
    D -- yes --> X2[HTTP 400]
    D -- no --> E[Create job, status running, start task]
    E --> F["Digitise parts with Sarvam Document AI, doc_concurrency at once"]
    F --> G{Image part and model takes images?}
    G -- yes --> H["Add visual description (failure logged, skipped)"]
    G -- no --> I
    H --> I[Collect pages, chunk them]
    I --> J{Any chunks?}
    J -- no --> FAIL
    J -- yes --> K[Embed chunks]
    K --> L["ensure_schema once, write_document"]
    L --> M{Summarise and LLM present?}
    M -- yes --> N["summarise_document, set_summary (failure logged)"]
    M -- no --> DONE
    N --> DONE([Job done with result])
    F -. "SarvamError, GraphError, ValueError, other" .-> FAIL([Job failed with error])
    K -. error .-> FAIL
    L -. error .-> FAIL
```

Sources: apps/api/wsw_brain/documents/api.py:114-121, apps/api/wsw_brain/documents/api.py:159-194; apps/api/wsw_brain/documents/ingest.py:87-160, apps/api/wsw_brain/documents/ingest.py:186-191.

### Ask with no-evidence fallback

**Status:** the document path is **Implemented**. The meeting path (`MeetingAgent.ask`) is **Partial**: the code and `POST /api/agent/ask` exist, but the shipped app is created without an agent, so the route is not mounted.

*Activity view: both Ask paths answer without calling the model when retrieval finds nothing.*

```mermaid
flowchart TD
    subgraph Meeting["MeetingAgent.ask (Partial)"]
        M1([Question]) --> M2{Blank?}
        M2 -- yes --> M3[ValueError]
        M2 -- no --> M4["retrieve(question, meeting_id, k)"]
        M4 --> M5{Any hits?}
        M5 -- no --> M6["Fallback: no supporting evidence"]
        M5 -- yes --> M7["chat(evidence, session history)"]
        M7 --> M8[Ground citations against hits]
        M8 --> M9{Answer left?}
        M9 -- no --> M6
        M9 -- yes --> M10[Remember turn in session]
        M10 --> M11([AskResult with citations])
        M6 --> M12([AskResult, no citations])
    end
    subgraph Docs["answer_question (Implemented)"]
        D1([Question]) --> D2[Retrieve passages]
        D2 --> D3{include_meetings?}
        D3 -- yes --> D4["Retrieve meeting lines (errors ignored)"]
        D3 -- no --> D5
        D4 --> D5{Passages or meeting lines?}
        D5 -- no --> D6["Fixed answer: documents do not mention that"]
        D5 -- yes --> D7[chat with passages]
        D7 --> D8[Remove citations to unknown ids]
        D8 --> D9([Answer with citations])
    end
```

Sources: apps/api/wsw_brain/brain/agent.py:19, apps/api/wsw_brain/brain/agent.py:38-94, apps/api/wsw_brain/brain/agent.py:148-163; apps/api/wsw_brain/documents/answer.py:118-167; apps/api/wsw_brain/app.py:19-20, apps/api/wsw_brain/app.py:44.

## State diagrams

### Meeting

**Status: Partial.** The graph store sets both states. Only `IngestPipeline.end_meeting` drives the transition, and nothing calls it outside tests.

*State view: a meeting is created live and becomes ended once; deleting removes it.*

```mermaid
stateDiagram-v2
    [*] --> live: create_meeting (MERGE, ON CREATE)
    live --> ended: end_meeting (flush, set ended_at, duration_s)
    ended --> ended: end_meeting again returns it unchanged
    ended --> summarised: final extraction and summary
    live --> [*]: delete_meeting
    ended --> [*]: delete_meeting
    summarised --> [*]: delete_meeting
    note right of summarised
        Still status ended in the graph.
        summary is set and a second meeting.ended is published.
    end note
```

Sources: apps/api/wsw_brain/graph/cypher.py:50-61; apps/api/wsw_brain/graph/store.py:267-335; apps/api/wsw_brain/pipeline.py:186-240.

### Action item

**Status: Partial.** `set_action_item_status` exists in the graph store, but no server route calls it. The web client's `PATCH /api/action-items/{id}` has no server.

*State view: an action item is created open and can move between open and done.*

```mermaid
stateDiagram-v2
    [*] --> open: write_insights (ON CREATE)
    open --> done: set_action_item_status("done"), done_at set if empty
    done --> open: set_action_item_status("open"), done_at cleared
    open --> [*]: meeting deleted
    done --> [*]: meeting deleted
```

Sources: apps/api/wsw_brain/graph/cypher.py:439-442, apps/api/wsw_brain/graph/cypher.py:544; apps/api/wsw_brain/graph/store.py:63, apps/api/wsw_brain/graph/store.py:693-699; apps/web/src/api/client.ts:79-80.

### Decision

**Status: Partial.** Supersession is written by `write_insights`, which runs only from the unwired extraction cycle.

*State view: a decision is active until a later decision supersedes it, and becomes active again if the superseding meeting is deleted.*

```mermaid
stateDiagram-v2
    [*] --> active: write_insights (ON CREATE)
    active --> superseded: SUPERSEDE (new decision names it)
    superseded --> active: REACTIVATE_UNSUPERSEDED after delete_meeting removes every superseder
    active --> [*]: own meeting deleted
    superseded --> [*]: own meeting deleted
```

Sources: apps/api/wsw_brain/graph/cypher.py:100-107, apps/api/wsw_brain/graph/cypher.py:429, apps/api/wsw_brain/graph/cypher.py:463-470; apps/api/wsw_brain/graph/store.py:323-335, apps/api/wsw_brain/graph/store.py:578.

### Document ingest job

**Status: Implemented.** Jobs are held in a process-local dictionary.

*State view: a job runs once and ends done or failed; only a finished job can be deleted.*

```mermaid
stateDiagram-v2
    [*] --> running: POST /api/documents
    running --> done: ingest() returned
    running --> failed: DocumentError, SarvamError, GraphError, ValueError or other
    running --> running: DELETE refused with 409
    done --> [*]: DELETE /api/documents/jobs/{id} or pruned
    failed --> [*]: DELETE /api/documents/jobs/{id} or pruned
```

Sources: apps/api/wsw_brain/documents/api.py:35-51, apps/api/wsw_brain/documents/api.py:159-194, apps/api/wsw_brain/documents/api.py:218-226, apps/api/wsw_brain/documents/api.py:290-293.

### ModelGate slot

**Status: Implemented.** Every Ollama, Gemini and OpenAI-compatible call goes through the gate for its endpoint. `GemmaClient` (apps/api/wsw_brain/brain/gemma.py) does not use it.

*State view: one caller's request for a model slot, from asking to release.*

```mermaid
stateDiagram-v2
    [*] --> requested: slot()
    requested --> running: busy < slots and no live waiters
    requested --> refused: priority 0 and max_waiting ordinary callers queued
    requested --> waiting: pushed on heap (priority, then arrival)
    waiting --> running: a released slot is granted
    waiting --> timed_out: still waiting after wait_s
    waiting --> cancelled: caller cancelled
    running --> released: call finished
    released --> [*]: slot passed to next waiter, or busy - 1
    refused --> [*]: LLMError "busy"
    timed_out --> [*]: LLMError, slot given back if granted late
    cancelled --> [*]: slot given back if granted late
```

Sources: apps/api/wsw_brain/brain/llm.py:67-150, apps/api/wsw_brain/brain/llm.py:157-164, apps/api/wsw_brain/brain/llm.py:312, apps/api/wsw_brain/brain/llm.py:443, apps/api/wsw_brain/brain/llm.py:626; apps/api/wsw_brain/config.py:51-53.
