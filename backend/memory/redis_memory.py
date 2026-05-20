from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from backend.config.settings import get_settings


class RedisMemoryStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.ttl = settings.REDIS_TTL_SECONDS
        self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    @staticmethod
    def _key(session_id: str, suffix: str) -> str:
        return f"voice-agent:{session_id}:{suffix}"

    async def set_session_state(self, session_id: str, payload: dict[str, Any]) -> None:
        key = self._key(session_id, "state")
        await self._redis.set(key, json.dumps(payload, ensure_ascii=False), ex=self.ttl)

    async def get_session_state(self, session_id: str) -> dict[str, Any]:
        key = self._key(session_id, "state")
        raw = await self._redis.get(key)
        if not raw:
            return {}
        return json.loads(raw)

    async def update_state_fields(self, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get_session_state(session_id)
        existing.update(updates)
        await self.set_session_state(session_id, existing)
        return existing

    async def set_language(self, session_id: str, language: str) -> None:
        await self.update_state_fields(session_id, {"language_preference": language})

    async def get_language(self, session_id: str) -> str | None:
        state = await self.get_session_state(session_id)
        value = state.get("language_preference")
        return str(value) if value else None

    async def add_conversation_message(self, session_id: str, role: str, content: str) -> None:
        key = self._key(session_id, "messages")
        payload = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.rpush(key, payload)
            await pipe.ltrim(key, -30, -1)
            await pipe.expire(key, self.ttl)
            await pipe.execute()

    async def set_temporary_context(self, session_id: str, context: dict[str, Any]) -> None:
        await self.update_state_fields(session_id, {"temporary_context": context})

    async def get_temporary_context(self, session_id: str) -> dict[str, Any]:
        state = await self.get_session_state(session_id)
        context = state.get("temporary_context")
        if isinstance(context, dict):
            return context
        return {}

    async def get_conversation_messages(self, session_id: str) -> list[dict[str, str]]:
        key = self._key(session_id, "messages")
        values = await self._redis.lrange(key, 0, -1)
        messages: list[dict[str, str]] = []
        for item in values:
            try:
                parsed = json.loads(item)
                if isinstance(parsed, dict):
                    messages.append(
                        {
                            "role": str(parsed.get("role", "user")),
                            "content": str(parsed.get("content", "")),
                        }
                    )
            except json.JSONDecodeError:
                continue
        return messages

    async def clear_session(self, session_id: str) -> None:
        keys = [
            self._key(session_id, "state"),
            self._key(session_id, "messages"),
        ]
        await self._redis.delete(*keys)
