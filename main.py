from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agent.orchestrator import VoiceAgentOrchestrator
from backend.api.routes import router as api_router
from backend.config.settings import get_settings
from backend.database.db import close_db, init_db
from backend.memory.redis_memory import RedisMemoryStore
from backend.services.tts.deepgram_tts import DeepgramTTSService
from backend.websocket.socket import router as websocket_router


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def validate_required_settings() -> None:
    settings = get_settings()
    required = {
        "SAMBANOVA_API_KEY": settings.SAMBANOVA_API_KEY,
        "DEEPGRAM_API_KEY": settings.DEEPGRAM_API_KEY,
        "REDIS_URL": settings.REDIS_URL,
        "DATABASE_URL": settings.DATABASE_URL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    if settings.APP_ENV.lower() == "test":
        yield
        return

    validate_required_settings()

    await init_db()

    memory_store = RedisMemoryStore()
    await memory_store.ping()

    app.state.memory_store = memory_store
    app.state.orchestrator = VoiceAgentOrchestrator(memory_store=memory_store)
    app.state.tts_service = DeepgramTTSService()
    app.state.settings = settings

    yield

    await memory_store.close()
    await close_db()


settings = get_settings()
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1", tags=["api"])
app.include_router(websocket_router, tags=["realtime"])


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Realtime Multilingual Voice AI Agent backend is running."}
