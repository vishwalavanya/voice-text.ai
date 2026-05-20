# Realtime Multilingual Voice AI Agent (Clinical Appointment Booking)

Production-style FastAPI backend for a real-time voice AI assistant that:

- Receives live microphone audio over WebSocket
- Streams audio to Deepgram realtime STT (`flux-general-en`)
- Detects `en`, `hi`, `ta`
- Uses SambaNova LLM (`Meta-Llama-3.3-70B-Instruct`) with real tool-calling
- Books/cancels/reschedules appointments in PostgreSQL (Supabase)
- Stores session memory in Redis Cloud with TTL
- Converts assistant responses to speech (Deepgram TTS)
- Returns synthesized audio through WebSocket
- Logs stage-by-stage latency

## 1. Project Overview

This backend is designed for low-latency clinical voice interactions and supports persistent scheduling workflows with tool-based reasoning rather than static chatbot responses.

## 2. Architecture Diagram Explanation

Flow:

1. Frontend mic audio chunks -> `/ws/audio`
2. Backend -> Deepgram realtime STT stream
3. Transcript -> language detection (`en|hi|ta`)
4. Transcript + context -> SambaNova LLM
5. LLM decides and calls tools
6. Tool layer -> async PostgreSQL CRUD
7. Session state/messages -> Redis memory
8. Assistant text -> Deepgram TTS
9. Audio response -> WebSocket (base64 MP3)
10. Latency metrics logged per turn

## 3. Folder Structure

```text
voice-ai-agent/
├── backend/
│   ├── __init__.py
│   ├── agent/
│   │   ├── __init__.py
│   │   └── orchestrator.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   └── models.py
│   ├── latency/
│   │   ├── __init__.py
│   │   └── logger.py
│   ├── memory/
│   │   ├── __init__.py
│   │   └── redis_memory.py
│   ├── models/
│   │   └── __init__.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── appointment_schema.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── language/
│   │   │   ├── __init__.py
│   │   │   └── detect_language.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   └── sambanova_service.py
│   │   ├── stt/
│   │   │   ├── __init__.py
│   │   │   └── deepgram_service.py
│   │   └── tts/
│   │       ├── __init__.py
│   │       └── deepgram_tts.py
│   ├── tools/
│   │   ├── __init__.py
│   │   └── appointment_tools.py
│   ├── utils/
│   │   └── __init__.py
│   └── websocket/
│       ├── __init__.py
│       └── socket.py
├── docker/
├── docs/
│   └── ARCHITECTURE.md
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 20260520_0001_create_core_tables.py
├── tests/
│   ├── __init__.py
│   └── test_health.py
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── main.py
├── README.md
└── requirements.txt
```

## 4. Environment Variables

Required (your exact keys):

- `SAMBANOVA_API_KEY`
- `DEEPGRAM_API_KEY`
- `REDIS_URL`
- `DATABASE_URL`

Optional:

- `APP_ENV`, `APP_HOST`, `APP_PORT`, `LOG_LEVEL`
- `SAMBANOVA_BASE_URL`, `SAMBANOVA_MODEL`
- `DEEPGRAM_STT_MODEL`, `DEEPGRAM_TTS_MODEL`
- `AUDIO_ENCODING`, `AUDIO_SAMPLE_RATE`
- `REDIS_TTL_SECONDS`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `SQL_ECHO`
- `CORS_ORIGINS`

## 5. Installation Steps

1. Copy `.env.example` to `.env`
2. Fill real secrets
3. Install Python dependencies
4. Run DB migration
5. Start server

## 6. Running Locally

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 7. Running with Docker

```bash
docker compose up --build
```

API:

- [http://localhost:8000](http://localhost:8000)
- [http://localhost:8000/docs](http://localhost:8000/docs)

## 8. Render Deployment

1. Push this folder to GitHub.
2. Create a new **Web Service** in Render.
3. Runtime: Docker.
4. Root Directory: `voice-ai-agent`.
5. Add environment variables in Render dashboard:
   - `SAMBANOVA_API_KEY`
   - `DEEPGRAM_API_KEY`
   - `REDIS_URL`
   - `DATABASE_URL`
6. Set health check path: `/api/v1/health`.
7. Deploy.

If using Supabase + Redis Cloud, do not attach local postgres/redis services on Render.

## 9. Supabase Setup

1. Create Supabase project.
2. Copy connection string.
3. Use async SQLAlchemy format:

```text
postgresql+asyncpg://USER:PASSWORD@HOST:5432/postgres
```

4. Set as `DATABASE_URL`.
5. Run:

```bash
alembic upgrade head
```

## 10. Redis Cloud Setup

1. Create Redis Cloud database.
2. Copy Redis URI.
3. Set `REDIS_URL`.
4. Memory keys are TTL-managed (`REDIS_TTL_SECONDS`).

## 11. Deepgram Setup

1. Create Deepgram API key.
2. Set `DEEPGRAM_API_KEY`.
3. Realtime STT uses:
   - `DeepgramClient`
   - `EventType`
   - `client.listen.v2.connect()`
   - model `flux-general-en`

## 12. SambaNova Setup

1. Generate SambaNova API key.
2. Set `SAMBANOVA_API_KEY`.
3. Client config:
   - base URL: `https://api.sambanova.ai/v1`
   - model: `Meta-Llama-3.3-70B-Instruct`
4. Tool calling is enabled with concrete appointment functions.

## 13. WebSocket Testing

Endpoint:

```text
ws://localhost:8000/ws/audio
```

Use `wscat` quick test (text/control path):

```bash
npm install -g wscat
wscat -c ws://localhost:8000/ws/audio
```

Example control packet:

```json
{"type":"ping"}
```

For audio testing, send binary PCM chunks (`linear16`, 16kHz) from your frontend app.

## 14. API Endpoints

- `GET /` -> root service check
- `GET /api/v1/health` -> health
- `POST /api/v1/appointments/check` -> availability
- `POST /api/v1/appointments/book` -> book
- `POST /api/v1/appointments/cancel` -> cancel
- `POST /api/v1/appointments/reschedule` -> reschedule
- `WS /ws/audio` -> realtime voice pipeline

## 15. Future Improvements

1. Add OpenTelemetry traces and Prometheus metrics.
2. Replace simple language heuristics with robust multilingual ID model.
3. Add authenticated patient identity and RBAC.
4. Add doctor timezone-aware scheduling templates and recurrence rules.
5. Add queue-backed async workers for burst handling.
6. Add integration tests for websocket audio streaming.

