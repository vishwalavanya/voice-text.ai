from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.agent.orchestrator import VoiceAgentOrchestrator
from backend.database.db import AsyncSessionLocal
from backend.latency.logger import LatencyTracker
from backend.memory.redis_memory import RedisMemoryStore
from backend.services.language.detect_language import detect_language
from backend.services.stt.deepgram_service import DeepgramRealtimeSTTService
from backend.services.tts.deepgram_tts import DeepgramTTSService


logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/audio")
async def audio_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id = websocket.query_params.get("session_id") or str(uuid4())

    memory_store: RedisMemoryStore = websocket.app.state.memory_store
    orchestrator: VoiceAgentOrchestrator = websocket.app.state.orchestrator
    tts_service: DeepgramTTSService = websocket.app.state.tts_service

    stt_service = DeepgramRealtimeSTTService()
    transcript_queue: asyncio.Queue[tuple[float, str]] = asyncio.Queue()
    stop_event = asyncio.Event()
    last_audio_at = time.perf_counter()

    async def on_transcript(transcript: str) -> None:
        nonlocal last_audio_at
        cleaned = transcript.strip()
        if cleaned:
            stt_latency_ms = round((time.perf_counter() - last_audio_at) * 1000, 2)
            await transcript_queue.put((stt_latency_ms, cleaned))

    async def on_stt_error(message: str) -> None:
        logger.error("STT error | session=%s | message=%s", session_id, message)
        if not stop_event.is_set():
            await websocket.send_json({"type": "error", "source": "stt", "message": message})

    async def process_transcripts() -> None:
        async with AsyncSessionLocal() as db:
            while not stop_event.is_set():
                stt_latency_ms, transcript = await transcript_queue.get()
                turn_id = str(uuid4())
                latency = LatencyTracker(session_id=session_id, turn_id=turn_id)
                try:
                    latency.stages_ms["stt_latency"] = stt_latency_ms

                    language_started = latency.start_stage()
                    cached_language = await memory_store.get_language(session_id) or "en"
                    detected_language = detect_language(transcript, fallback=cached_language)
                    latency.end_stage("language_detection_latency", language_started)

                    await websocket.send_json(
                        {
                            "type": "transcript",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "text": transcript,
                            "language": detected_language,
                        }
                    )

                    agent_result = await orchestrator.handle_turn(
                        session_id=session_id,
                        transcript=transcript,
                        detected_language=detected_language,
                        db=db,
                        latency=latency,
                    )

                    tts_started = latency.start_stage()
                    tts_audio = await tts_service.synthesize(
                        text=agent_result["response_text"],
                        language=agent_result["language"],
                    )
                    latency.end_stage("tts_latency", tts_started)
                    latency.log_summary(extra={"intent": str(agent_result.get("intent", ""))})

                    await websocket.send_json(
                        {
                            "type": "assistant_response",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "language": agent_result["language"],
                            "intent": agent_result.get("intent"),
                            "text": agent_result["response_text"],
                            "tool_results": agent_result.get("tool_results", []),
                        }
                    )
                    await websocket.send_json(
                        {
                            "type": "audio_response",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "audio_format": "mp3",
                            "encoding": "base64",
                            "audio_data": base64.b64encode(tts_audio).decode("ascii"),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Pipeline failure | session=%s", session_id)
                    await websocket.send_json({"type": "error", "source": "pipeline", "message": str(exc)})
                finally:
                    transcript_queue.task_done()

    await stt_service.start(transcript_callback=on_transcript, error_callback=on_stt_error)
    worker_task = asyncio.create_task(process_transcripts())

    await websocket.send_json(
        {
            "type": "session_started",
            "session_id": session_id,
            "message": "Realtime voice session started.",
        }
    )

    try:
        while True:
            packet = await websocket.receive()
            if packet.get("type") == "websocket.disconnect":
                break

            binary_data = packet.get("bytes")
            if binary_data:
                last_audio_at = time.perf_counter()
                await stt_service.send_audio(binary_data)
                continue

            text_data = packet.get("text")
            if not text_data:
                continue

            try:
                payload = json.loads(text_data)
            except json.JSONDecodeError:
                payload = {"type": "raw_text", "text": text_data}

            packet_type = payload.get("type")
            if packet_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif packet_type == "audio_chunk_base64":
                encoded = payload.get("data", "")
                if encoded:
                    last_audio_at = time.perf_counter()
                    chunk = base64.b64decode(encoded)
                    await stt_service.send_audio(chunk)
            elif packet_type == "end_stream":
                break
            else:
                await websocket.send_json(
                    {
                        "type": "warning",
                        "message": f"Unsupported websocket message type: {packet_type}",
                    }
                )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected | session=%s", session_id)
    finally:
        stop_event.set()
        worker_task.cancel()
        await stt_service.stop()
        await memory_store.update_state_fields(session_id, {"pending_confirmations": False})
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
