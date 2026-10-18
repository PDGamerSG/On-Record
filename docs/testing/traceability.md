# Requirements traceability matrix

This matrix links every functional (FR) and quality (NFR) requirement in the [software requirements specification](../requirements/SRS.md) to its design description, the code that implements it and the tests that verify it, at commit `8943885`. The test levels and gaps are described in the [test plan](test-plan.md).

Columns:

- **Status**: Implemented, Partial or Planned, as defined in the SRS. The note in brackets says what is missing. G1 to G7 refer to the recurring gaps listed in the SRS: no meeting, voice or WebSocket routes in the main app (G1), the unserved `/api/health` probe (G2), the agent mounted only when injected (G3), `IngestPipeline` constructed by no entrypoint (G4), the SSE frame mismatch (G5), the documents router served only by the separate documents app (G6), and `GemmaClient` used only by the benchmark (G7).
- **Design**: the design document that describes the requirement: the [SDS](../design/SDS.md) for components and behaviour, the [data model](../design/data-model.md) for graph nodes and edges, and the [architecture](../architecture/README.md) for quality requirements.
- **Code**: the first implementing location, as `path:line` at `8943885`. The SRS lists further locations.
- **Tests**: the pytest modules (and test names or lines, where the SRS gives them) that cover the requirement, or "None" when it is verified by inspection or demonstration only. Web requirements marked "None" are covered by the manual cases in the test plan.

| ID | Status | Design | Code | Tests |
|---|---|---|---|---|
| FR-001 | Partial (library only, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/session.py:1-21` | apps/api/tests/test_session.py |
| FR-002 | Planned | [SDS](../design/SDS.md) | `apps/web/src/audio/mic.ts:1-2` | None |
| FR-003 | Partial (no audio route) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/audio.py:215-282` | apps/api/tests/test_audio.py; apps/api/tests/test_session.py |
| FR-004 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/pipeline.py:19-23` | apps/api/tests/test_session.py; apps/api/tests/test_audio.py |
| FR-005 | Planned | [SDS](../design/SDS.md) | `apps/web/src/components/meeting/UploadRecording.tsx:25` | None |
| FR-006 | Partial (no meeting routes, G1) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/store.py:267-342` | apps/api/tests/test_graph.py (meeting_lifecycle_and_listing apps/api/tests/test_graph.py:285, delete_meeting_cleans_up_and_reactivates apps/api/tests/test_graph.py:691) |
| FR-007 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/session.py:418-424` | apps/api/tests/test_session.py (session_survives_asr_errors, session_survives_a_failing_callback) |
| FR-008 | Partial (library only, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/speakers.py:19-55` | apps/api/tests/test_speakers.py; apps/api/tests/test_session.py |
| FR-009 | Partial (library only, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/speakers.py:146-167` | apps/api/tests/test_speakers.py (change_point_inside_a_segment, clusterer_merges_tracks_whose_centroids_converge); apps/api/tests/test_session.py (session_back_to_back_turns, session_borderline_interjection_does_not_open_a_phantom_track) |
| FR-010 | Partial (library only, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/session.py:19-20` | apps/api/tests/test_session.py (session_resumed_meeting_keeps_speaker_tracks); apps/api/tests/test_speakers.py (clusterer_state_carries_tracks_to_a_later_session) |
| FR-011 | Partial (route not served) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/store.py:397-459` | apps/api/tests/test_graph.py (apps/api/tests/test_graph.py:306, apps/api/tests/test_graph.py:327, corrected_speaker_name_hands_named_items_back) |
| FR-012 | Partial (adapter never constructed) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/asr.py:14-97` | apps/api/tests/test_asr.py; apps/api/tests/test_session.py (garbage_filter) |
| FR-013 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/listen/sarvam_asr.py:31-124` | apps/api/tests/test_sarvam_asr.py |
| FR-014 | Partial (no voice route; GemmaClient unwired, G7) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/gemma.py:169-186` | apps/api/tests/test_gemma.py (no transcription test; Inspection for the audio path) |
| FR-015 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/extract.py:16-46` | apps/api/tests/test_extract.py |
| FR-016 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/extract.py:599-658` | apps/api/tests/test_extract.py (test_extractor_falls_back_on_invalid_json_and_fake apps/api/tests/test_extract.py:199) |
| FR-017 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/extract.py:49-52` | apps/api/tests/test_graph.py (supersession_across_meetings apps/api/tests/test_graph.py:444); apps/api/tests/test_extract.py |
| FR-018 | Partial (unwired, G4) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/store.py:461-665` | apps/api/tests/test_graph.py (write_insights_dedupes_and_returns_new_items_only apps/api/tests/test_graph.py:404); apps/api/tests/test_contracts.py |
| FR-019 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/summary.py:15-123` | apps/api/tests/test_summary.py |
| FR-060 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/pipeline.py:36-37` | apps/api/tests/test_pipeline.py (test_live_extraction_runs_every_extract_every_utterances apps/api/tests/test_pipeline.py:211, test_overlapping_windows_do_not_repeat_insights apps/api/tests/test_pipeline.py:261) |
| FR-061 | Partial (unwired, G4) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/pipeline.py:186-240` | apps/api/tests/test_pipeline.py (test_ending_a_meeting_runs_the_final_extraction_and_the_summary apps/api/tests/test_pipeline.py:231) |
| FR-020 | Partial (unwired, G4; seed script writes) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/store.py:345-395` | apps/api/tests/test_graph.py (write_batches_out_of_order_builds_next_chain apps/api/tests/test_graph.py:216) |
| FR-021 | Implemented | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/store.py:213-247` | apps/api/tests/test_graph.py (ensure_schema_is_idempotent_and_complete apps/api/tests/test_graph.py:180); apps/api/tests/test_graph_schema.py |
| FR-022 | Partial (route not served) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/store.py:676-789` | apps/api/tests/test_graph.py (apps/api/tests/test_graph.py:472, apps/api/tests/test_graph.py:586, apps/api/tests/test_graph.py:603, apps/api/tests/test_graph.py:681) |
| FR-023 | Partial (route not served) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/store.py:889-907` | apps/api/tests/test_graph.py (turns_round_trip apps/api/tests/test_graph.py:644) |
| FR-062 | Partial (unwired, G4) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/pipeline.py:55-183` | apps/api/tests/test_pipeline.py (apps/api/tests/test_pipeline.py:164, apps/api/tests/test_pipeline.py:184, apps/api/tests/test_pipeline.py:200, apps/api/tests/test_pipeline.py:250) |
| FR-024 | Implemented (through /api/documents/ask) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/retrieve.py:16` | apps/api/tests/test_retrieve.py; apps/api/tests/test_retrieve_graph.py |
| FR-025 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/retrieve.py:17-21` | apps/api/tests/test_retrieve_graph.py (confirmed_incompatible_vectors_are_excluded_and_verdict_is_cached) |
| FR-026 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/graph/text.py:101-121` | apps/api/tests/test_graph.py (fulltext_falls_back_to_contains_scan apps/api/tests/test_graph.py:530) |
| FR-027 | Partial (agent not mounted, G3) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/agent.py:18-24` | apps/api/tests/test_agent.py; apps/api/tests/test_agent_api.py |
| FR-028 | Partial (agent not mounted, G3) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/agent.py:30-36` | apps/api/tests/test_agent.py (test_agent_keeps_recent_history_per_session apps/api/tests/test_agent.py:65) |
| FR-029 | Partial (agent not mounted, G3) | [SDS](../design/SDS.md) | `apps/web/src/components/ask/AskDrawer.tsx:1` | None (no web tests) |
| FR-030 | Partial (needs unserved /api/ask/voice) | [SDS](../design/SDS.md) | `apps/web/src/components/ask/useVoiceQuestion.ts:1-4` | None |
| FR-031 | Implemented | [SDS](../design/SDS.md) | `apps/web/src/components/ask/speech.ts:1-5` | None |
| FR-032 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/documents/split.py:22` | apps/api/tests/test_documents_split.py; apps/api/tests/test_documents_api.py |
| FR-033 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/documents/sarvam.py:51-162` | apps/api/tests/test_documents_sarvam.py; apps/api/tests/test_documents_ingest.py (apps/api/tests/test_documents_ingest.py:79) |
| FR-034 | Implemented (documents app only) | [Data model](../design/data-model.md) | `apps/api/wsw_brain/documents/split.py:199-288` | apps/api/tests/test_documents_split.py; apps/api/tests/test_documents_ingest.py |
| FR-035 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/documents/api.py:32-51` | apps/api/tests/test_documents_api.py |
| FR-036 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/documents/vision.py:15-43` | apps/api/tests/test_documents_ingest.py (test_image_uploads_get_a_gemma_description apps/api/tests/test_documents_ingest.py:190) |
| FR-037 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/documents/answer.py:60-77` | apps/api/tests/test_documents_ingest.py (test_questions_in_indian_scripts_match_document_text apps/api/tests/test_documents_ingest.py:208) |
| FR-038 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/documents/answer.py:30-50` | apps/api/tests/test_documents_ingest.py (apps/api/tests/test_documents_ingest.py:122, apps/api/tests/test_documents_ingest.py:147) |
| FR-039 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/documents/answer.py:26` | apps/api/tests/test_documents_ingest.py |
| FR-040 | Planned | [SDS](../design/SDS.md) | `apps/web/src/App.tsx:40-47` | None |
| FR-041 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/sarvam.py:12-27` | apps/api/tests/test_sarvam_speech.py; apps/api/tests/test_documents_api.py (apps/api/tests/test_documents_api.py:145, apps/api/tests/test_documents_api.py:154, apps/api/tests/test_documents_api.py:177) |
| FR-042 | Implemented (documents app only) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/sarvam.py:18-24` | apps/api/tests/test_sarvam_speech.py; apps/api/tests/test_documents_api.py (test_speak_returns_wav apps/api/tests/test_documents_api.py:188) |
| FR-043 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/events.py:1-139` | apps/api/tests/test_events.py |
| FR-044 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/event_stream.py:14-67` | apps/api/tests/test_app.py (apps/api/tests/test_app.py:54, apps/api/tests/test_app.py:71, apps/api/tests/test_app.py:88, apps/api/tests/test_app.py:96) |
| FR-045 | Partial (client cannot read frames, G5) | [SDS](../design/SDS.md) | `apps/web/src/api/events.ts:1-11` | apps/api/tests/test_app.py pins the server frame format only |
| FR-046 | Implemented | [SDS](../design/SDS.md) | `apps/web/src/main.tsx:9` | None |
| FR-047 | Implemented | [SDS](../design/SDS.md) | `apps/web/src/api/demo/demoApi.ts:1-3` | None |
| FR-048 | Partial (demo data only) | [SDS](../design/SDS.md) | `apps/web/src/pages/MeetingsPage.tsx:25-118` | None |
| FR-049 | Partial (demo data only) | [SDS](../design/SDS.md) | `apps/web/src/pages/MeetingRoom.tsx:1-2` | None |
| FR-050 | Partial (demo data only) | [SDS](../design/SDS.md) | `apps/web/src/pages/CommitmentsPage.tsx:1-2` | None |
| FR-051 | Partial (demo data only) | [SDS](../design/SDS.md) | `apps/web/src/pages/DecisionsPage.tsx:1-2` | None |
| FR-052 | Partial (demo data only) | [SDS](../design/SDS.md) | `apps/web/src/pages/PeoplePage.tsx:13-20` | None |
| FR-053 | Partial (demo data only) | [SDS](../design/SDS.md) | `apps/web/src/pages/GraphPage.tsx:1-2` | None |
| FR-054 | Implemented | [SDS](../design/SDS.md) | `apps/web/src/components/CommandPalette.tsx:1` | None |
| FR-055 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/config.py:15-93` | apps/api/tests/test_config.py |
| FR-056 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/llm.py:856-895` | apps/api/tests/test_llm.py; apps/api/tests/test_gemini_llm.py; apps/api/tests/test_openai_llm.py; apps/api/tests/test_documents_sarvam.py |
| FR-057 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/embed.py:18-186` | apps/api/tests/test_gemma_embed.py; apps/api/tests/test_embed.py |
| FR-058 | Implemented | [SDS](../design/SDS.md) | `apps/api/wsw_brain/app.py:22-39` | apps/api/tests/test_app.py; apps/api/tests/test_cli.py |
| FR-059 | Planned | [SDS](../design/SDS.md) | `apps/api/wsw_brain/config.py:55` | None |
| FR-063 | Partial (unwired, G7) | [SDS](../design/SDS.md) | `apps/api/wsw_brain/brain/gemma.py:1-337` | apps/api/tests/test_gemma.py |
| FR-064 | Implemented | [SDS](../design/SDS.md) | `scripts/bench_gemma.py:1-125` | apps/api/tests/test_bench_gemma.py |
| FR-065 | Implemented | [SDS](../design/SDS.md) | `scripts/gemma.sh:1-40` | None |
| NFR-001 | Planned (claim only) | [Architecture](../architecture/README.md) | `apps/web/src/landing/LinerNotes.tsx:20-25` | None |
| NFR-002 | Planned (claim only) | [Architecture](../architecture/README.md) | `apps/web/src/landing/LinerNotes.tsx:14-18` | apps/api/tests/test_session.py and apps/api/tests/test_speakers.py use a two-speaker fixture but do not assert these figures |
| NFR-003 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/llm.py:58-164` | apps/api/tests/test_model_gate.py; apps/api/tests/test_summary.py (apps/api/tests/test_summary.py:129) |
| NFR-004 | Partial (library only, G4) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/listen/session.py:11-17` | apps/api/tests/test_session.py |
| NFR-005 | Partial (unwired, G4) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/llm.py:875-887` | apps/api/tests/test_llm.py (select_llm_auto_falls_back_to_fake_when_ollama_is_unavailable); apps/api/tests/test_embed.py |
| NFR-006 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/documents/sarvam.py:52` | apps/api/tests/test_documents_sarvam.py |
| NFR-007 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/llm.py:856-887` | apps/api/tests/test_llm.py; apps/api/tests/test_gemma_embed.py |
| NFR-008 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/retrieve.py:101-113` | apps/api/tests/test_retrieve_graph.py (query_embedding_failure_preserves_text_results, one_failed_source_does_not_discard_other_results) |
| NFR-009 | Partial (unwired, G4) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/extract.py:709-715` | apps/api/tests/test_extract.py; apps/api/tests/test_summary.py; apps/api/tests/test_documents_ingest.py |
| NFR-010 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/graph/store.py:139-191` | apps/api/tests/test_graph.py (ping_never_raises_when_unreachable); apps/api/tests/test_documents_api.py |
| NFR-011 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/documents/sarvam.py:30-32` | apps/api/tests/test_documents_sarvam.py; apps/api/tests/test_llm.py; apps/api/tests/test_openai_llm.py; apps/api/tests/test_gemini_llm.py |
| NFR-012 | Partial (client cannot read frames, G5) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/events.py:53-55` | apps/api/tests/test_events.py; apps/api/tests/test_app.py |
| NFR-026 | Partial (unwired, G4) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/pipeline.py:39-40` | apps/api/tests/test_pipeline.py (test_utterances_are_kept_when_embedding_fails apps/api/tests/test_pipeline.py:200) |
| NFR-013 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/llm.py:35-39` | apps/api/tests/test_prompts.py; apps/api/tests/test_extract.py (apps/api/tests/test_extract.py:216); apps/api/tests/test_summary.py (apps/api/tests/test_summary.py:145) |
| NFR-014 | Implemented (documents); Partial (agent, extractor: unwired) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/agent.py:148-163` | apps/api/tests/test_agent.py (apps/api/tests/test_agent.py:37); apps/api/tests/test_extract.py; apps/api/tests/test_documents_ingest.py |
| NFR-015 | Implemented | [Data model](../design/data-model.md) | `apps/api/wsw_brain/graph/cypher.py:1-2` | apps/api/tests/test_graph.py |
| NFR-016 | Implemented | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/agent_api.py:13-17` | apps/api/tests/test_documents_api.py; apps/api/tests/test_documents_split.py; apps/api/tests/test_gemini_llm.py (gemini_rejects_remote_images_and_unknown_parts); apps/api/tests/test_agent_api.py (apps/api/tests/test_agent_api.py:43) |
| NFR-017 | Planned | [Architecture](../architecture/README.md) | `.env.example:56-61` | None |
| NFR-027 | Partial (GemmaClient puts the Gemini key in the URL) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/brain/llm.py:356` | None |
| NFR-018 | Implemented | [Architecture](../architecture/README.md) | `apps/web/src/components/ask/AskDrawer.tsx:318` | None |
| NFR-019 | Implemented | [Architecture](../architecture/README.md) | `apps/web/src/components/ask/AskDrawer.tsx:296` | None |
| NFR-020 | Implemented | [Architecture](../architecture/README.md) | `apps/web/src/styles/base.css:335-340` | None |
| NFR-021 | Implemented | [Architecture](../architecture/README.md) | `apps/web/src/pages/CommitmentsPage.tsx:186` | None |
| NFR-022 | Implemented | [Architecture](../architecture/README.md) | `.github/workflows/checks.yml:16-57` | all of apps/api/tests |
| NFR-023 | Partial (not run in CI) | [Architecture](../architecture/README.md) | `apps/web/package.json:6-11` | None |
| NFR-024 | Partial (hand-kept web mirror) | [Architecture](../architecture/README.md) | `apps/api/wsw_brain/contracts.py:1-13` | apps/api/tests/test_contracts.py |
| NFR-025 | Implemented | [Architecture](../architecture/README.md) | `apps/api/pyproject.toml:6` | apps/api/tests/test_graph.py |
| NFR-028 | Implemented | [Architecture](../architecture/README.md) | `scripts/bench_gemma.py:63-88` | apps/api/tests/test_bench_gemma.py |

Rows: 93 (65 FR, 28 NFR). Rows follow the order of the SRS, so FR-060 to FR-065 and NFR-026 to NFR-028 appear within their sections.
