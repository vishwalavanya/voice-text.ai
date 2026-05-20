from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable

from deepgram import DeepgramClient
from deepgram.core.events import EventType

from backend.config.settings import get_settings


logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]


class DeepgramRealtimeSTTService:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = DeepgramClient(api_key=settings.DEEPGRAM_API_KEY)
        self.model = settings.DEEPGRAM_STT_MODEL
        self.encoding = settings.AUDIO_ENCODING
        self.sample_rate = settings.AUDIO_SAMPLE_RATE

        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._transcript_callback: TranscriptCallback | None = None
        self._error_callback: ErrorCallback | None = None

    def _safe_getattr(self, source: object, key: str, default: object = None) -> object:
        return getattr(source, key, default)

    def _extract_transcript(self, message: object) -> str:
        direct = self._safe_getattr(message, "transcript", "")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        channel = self._safe_getattr(message, "channel", None)
        alternatives = self._safe_getattr(channel, "alternatives", []) if channel else []
        if alternatives:
            top = alternatives[0]
            text = self._safe_getattr(top, "transcript", "")
            if isinstance(text, str) and text.strip():
                return text.strip()
        return ""

    def _dispatch_transcript(self, transcript: str) -> None:
        if not transcript or not self._loop or not self._transcript_callback:
            return
        asyncio.run_coroutine_threadsafe(self._transcript_callback(transcript), self._loop)

    def _dispatch_error(self, message: str) -> None:
        if not self._loop or not self._error_callback:
            logger.error("Deepgram error without callback: %s", message)
            return
        asyncio.run_coroutine_threadsafe(self._error_callback(message), self._loop)

    def _on_message(self, message: object) -> None:
        try:
            message_type = str(self._safe_getattr(message, "type", ""))
            if message_type == "TurnInfo":
                event_type = str(self._safe_getattr(message, "event", ""))
                if event_type in {"EndOfTurn", "EagerEndOfTurn"}:
                    self._dispatch_transcript(self._extract_transcript(message))
                return

            is_final = bool(self._safe_getattr(message, "is_final", False))
            speech_final = bool(self._safe_getattr(message, "speech_final", False))
            if is_final or speech_final:
                self._dispatch_transcript(self._extract_transcript(message))
        except Exception as exc:  # noqa: BLE001
            self._dispatch_error(f"Failed to process Deepgram message: {exc}")

    def _on_error(self, error: object) -> None:
        self._dispatch_error(f"Deepgram stream error: {error}")

    def _on_close(self, _: object) -> None:
        self._stopped.set()

    def _run(self) -> None:
        try:
            with self.client.listen.v2.connect(
                model=self.model,
                encoding=self.encoding,
                sample_rate=self.sample_rate,
            ) as connection:
                self._connection = connection
                connection.on(EventType.MESSAGE, self._on_message)
                connection.on(EventType.ERROR, self._on_error)
                connection.on(EventType.CLOSE, self._on_close)
                self._ready.set()
                connection.start_listening()
        except Exception as exc:  # noqa: BLE001
            self._dispatch_error(f"Could not start Deepgram realtime connection: {exc}")
        finally:
            self._stopped.set()

    async def start(
        self,
        transcript_callback: TranscriptCallback,
        error_callback: ErrorCallback,
    ) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._loop = asyncio.get_running_loop()
        self._transcript_callback = transcript_callback
        self._error_callback = error_callback
        self._ready.clear()
        self._stopped.clear()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        await asyncio.to_thread(self._ready.wait, 5.0)
        if not self._ready.is_set():
            raise RuntimeError("Timed out waiting for Deepgram realtime connection to become ready.")

    async def send_audio(self, audio_chunk: bytes) -> None:
        if not audio_chunk or self._connection is None:
            return
        await asyncio.to_thread(self._connection.send_media, audio_chunk)

    async def stop(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                if hasattr(connection, "send_close_stream"):
                    try:
                        await asyncio.to_thread(connection.send_close_stream)
                    except TypeError:
                        await asyncio.to_thread(connection.send_close_stream, {"type": "CloseStream"})
            except Exception:  # noqa: BLE001
                pass

        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._stopped.wait, 3.0)

