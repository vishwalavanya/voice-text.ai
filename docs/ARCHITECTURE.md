# Realtime Clinical Voice Agent Architecture

## Pipeline

1. Frontend streams microphone PCM chunks to `/ws/audio`.
2. Backend forwards chunks to Deepgram realtime STT (`listen.v2.connect` with `flux-general-en`).
3. Transcript is language-detected (`en`, `hi`, `ta`).
4. Orchestrator sends context + transcript to SambaNova model.
5. Model performs tool-calling when booking flow actions are needed.
6. Tool layer executes async CRUD against PostgreSQL.
7. Session memory and language preference are kept in Redis with TTL.
8. Assistant text is synthesized using Deepgram TTS.
9. Audio is returned over WebSocket as base64 MP3.
10. Latency stages are logged for observability.

## Latency Stages

- `stt_latency`
- `language_detection_latency`
- `llm_initial_latency`
- `llm_followup_latency`
- `llm_latency` (aggregate)
- `db_call_latency`
- `db_latency` (aggregate)
- `tts_latency`
- `total_pipeline_latency_ms`

