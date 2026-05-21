from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)


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
        """Generate Redis key with consistent naming"""
        return f"voice-agent:{session_id}:{suffix}"

    async def set_session_state(self, session_id: str, payload: dict[str, Any]) -> None:
        """
        Store complete session state in Redis.
        TTL ensures auto-cleanup after inactivity.
        """
        key = self._key(session_id, "state")
        logger.debug("Saving session state | session=%s | keys=%s", session_id, list(payload.keys()))
        
        try:
            await self._redis.set(
                key,
                json.dumps(payload, ensure_ascii=False),
                ex=self.ttl
            )
        except Exception as e:
            logger.error("Failed to save session state | session=%s | error=%s", session_id, str(e))
            raise

    async def get_session_state(self, session_id: str) -> dict[str, Any]:
        """
        Retrieve complete session state from Redis.
        Returns empty dict if session doesn't exist (first connection).
        """
        key = self._key(session_id, "state")
        
        try:
            raw = await self._redis.get(key)
            if not raw:
                logger.debug("No existing session state | session=%s | new session", session_id)
                return {}
            
            state = json.loads(raw)
            logger.debug(
                "Retrieved session state | session=%s | booking_state=%s",
                session_id,
                state.get("booking_state", {})
            )
            return state
            
        except json.JSONDecodeError as e:
            logger.error("Corrupted session state | session=%s | error=%s", session_id, str(e))
            return {}
        except Exception as e:
            logger.error("Failed to retrieve session state | session=%s | error=%s", session_id, str(e))
            return {}

    async def update_state_fields(
        self,
        session_id: str,
        updates: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Merge updates into existing session state.
        Preserves all existing data, only updates specified fields.
        
        CRITICAL: Never lose data on partial updates.
        """
        try:
            # Fetch existing state to preserve it
            existing = await self.get_session_state(session_id)
            
            # Deep merge for nested dicts (especially booking_state)
            for key, value in updates.items():
                if key in existing and isinstance(existing[key], dict) and isinstance(value, dict):
                    # Merge nested dicts
                    existing[key].update(value)
                else:
                    # Overwrite for primitives
                    existing[key] = value
            
            # Save merged state
            await self.set_session_state(session_id, existing)
            
            logger.debug(
                "Updated session state | session=%s | updates=%s",
                session_id,
                list(updates.keys())
            )
            
            return existing
            
        except Exception as e:
            logger.error(
                "Failed to update session state | session=%s | error=%s",
                session_id,
                str(e)
            )
            raise

    async def set_language(self, session_id: str, language: str) -> None:
        """Store language preference for the session"""
        await self.update_state_fields(session_id, {"language_preference": language})

    async def get_language(self, session_id: str) -> str | None:
        """Retrieve language preference or None if not set"""
        state = await self.get_session_state(session_id)
        value = state.get("language_preference")
        return str(value) if value else None

    async def add_conversation_message(self, session_id: str, role: str, content: str) -> None:
        """
        Append conversation message to session history.
        Keeps last 30 messages per session.
        """
        key = self._key(session_id, "messages")
        payload = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                # Add message
                await pipe.rpush(key, payload)
                # Keep only last 30
                await pipe.ltrim(key, -30, -1)
                # Refresh TTL
                await pipe.expire(key, self.ttl)
                await pipe.execute()
                
            logger.debug(
                "Added conversation message | session=%s | role=%s",
                session_id,
                role
            )
            
        except Exception as e:
            logger.error(
                "Failed to add conversation message | session=%s | error=%s",
                session_id,
                str(e)
            )
            raise

    async def set_temporary_context(self, session_id: str, context: dict[str, Any]) -> None:
        """Store temporary context (cleared when new booking starts)"""
        await self.update_state_fields(session_id, {"temporary_context": context})

    async def get_temporary_context(self, session_id: str) -> dict[str, Any]:
        """Retrieve temporary context"""
        state = await self.get_session_state(session_id)
        context = state.get("temporary_context")
        if isinstance(context, dict):
            return context
        return {}

    async def get_conversation_messages(self, session_id: str) -> list[dict[str, str]]:
        """Retrieve all stored conversation messages for the session"""
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
        
        logger.debug("Retrieved %d conversation messages | session=%s", len(messages), session_id)
        return messages

    async def get_booking_state(self, session_id: str) -> dict[str, Any]:
        """
        Convenience method to get just the booking state.
        Used by frontend to show current values.
        """
        state = await self.get_session_state(session_id)
        booking_state = state.get("booking_state", {})
        
        logger.debug(
            "Retrieved booking state | session=%s | doctor=%s | date=%s | time=%s",
            session_id,
            booking_state.get("doctor_name"),
            booking_state.get("appointment_date"),
            booking_state.get("appointment_time"),
        )
        
        return booking_state

    async def clear_session(self, session_id: str) -> None:
        """
        Clear ALL data for a session.
        Used when user explicitly starts new booking.
        """
        keys = [
            self._key(session_id, "state"),
            self._key(session_id, "messages"),
        ]
        
        try:
            await self._redis.delete(*keys)
            logger.info("Cleared session | session=%s", session_id)
        except Exception as e:
            logger.error("Failed to clear session | session=%s | error=%s", session_id, str(e))
            raise

    async def exists_session(self, session_id: str) -> bool:
        """Check if session exists in Redis"""
        key = self._key(session_id, "state")
        exists = await self._redis.exists(key)
        return bool(exists)

    async def get_session_expiry(self, session_id: str) -> int | None:
        """Get remaining TTL for session (in seconds)"""
        key = self._key(session_id, "state")
        ttl = await self._redis.ttl(key)
        return ttl if ttl > 0 else None