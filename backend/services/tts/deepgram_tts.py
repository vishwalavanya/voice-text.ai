from __future__ import annotations

import asyncio
import logging

from deepgram import DeepgramClient

from backend.config.settings import get_settings


logger = logging.getLogger(__name__)


class DeepgramTTSService:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = DeepgramClient(api_key=settings.DEEPGRAM_API_KEY)
        self.default_model = settings.DEEPGRAM_TTS_MODEL
        self.language_voice_map = {
            "en": settings.DEEPGRAM_TTS_MODEL,
            "hi": settings.DEEPGRAM_TTS_MODEL,
            "ta": settings.DEEPGRAM_TTS_MODEL,
        }

    def _generate_audio_sync(self, text: str, model: str) -> bytes:
        response = self.client.speak.v1.audio.generate(
            text=text,
            model=model,
            encoding="mp3",
        )

        if hasattr(response, "stream") and response.stream is not None:
            return bytes(response.stream.getvalue())

        if isinstance(response, (bytes, bytearray)):
            return bytes(response)

        try:
            return b"".join(response)
        except TypeError as exc:
            raise RuntimeError(f"Unexpected Deepgram TTS response format: {type(response)}") from exc

    async def synthesize(self, text: str, language: str = "en") -> bytes:
        content = (text or "").strip()
        if not content:
            return b""
        model = self.language_voice_map.get(language, self.default_model)
        try:
            return await asyncio.to_thread(self._generate_audio_sync, content, model)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Deepgram TTS failed")
            raise RuntimeError(f"TTS synthesis failed: {exc}") from exc

