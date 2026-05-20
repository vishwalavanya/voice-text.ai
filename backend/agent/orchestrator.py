from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.latency.logger import LatencyTracker
from backend.memory.redis_memory import RedisMemoryStore
from backend.services.language.detect_language import get_language_name
from backend.services.llm.sambanova_service import SambaNovaService
from backend.tools.appointment_tools import (
    TOOL_SCHEMAS,
    book_appointment,
    cancel_appointment,
    check_availability,
    reschedule_appointment,
)


class VoiceAgentOrchestrator:
    SYSTEM_PROMPT = (
        "You are a clinical appointment booking voice assistant.\n"
        "You support English (en), Hindi (hi), and Tamil (ta).\n"
        "Always respond in the user's preferred language.\n"
        "For appointment operations, you MUST use tools.\n"
        "Available operations are: check, book, cancel, reschedule appointments.\n"
        "Be concise, medically safe, and confirm important details."
    )

    def __init__(self, memory_store: RedisMemoryStore) -> None:
        self.memory_store = memory_store
        self.llm_service = SambaNovaService()

    async def _execute_tool(
        self,
        db: AsyncSession,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "check_availability":
            return await check_availability(db=db, **arguments)
        if tool_name == "book_appointment":
            return await book_appointment(db=db, **arguments)
        if tool_name == "cancel_appointment":
            return await cancel_appointment(db=db, **arguments)
        if tool_name == "reschedule_appointment":
            return await reschedule_appointment(db=db, **arguments)
        return {"success": False, "message": f"Unknown tool: {tool_name}"}

    @staticmethod
    def _tool_calls_to_message(tool_calls: list[dict[str, str]], content: str) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {
                    "id": item["id"],
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "arguments": item["arguments"],
                    },
                }
                for item in tool_calls
            ],
        }

    async def handle_turn(
        self,
        session_id: str,
        transcript: str,
        detected_language: str,
        db: AsyncSession,
        latency: LatencyTracker,
    ) -> dict[str, Any]:
        state = await self.memory_store.get_session_state(session_id)
        preferred_language = state.get("language_preference") or detected_language or "en"

        await self.memory_store.update_state_fields(
            session_id,
            {
                "language_preference": preferred_language,
            },
        )

        history = await self.memory_store.get_conversation_messages(session_id)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{self.SYSTEM_PROMPT}\n"
                    f"User preferred language code: {preferred_language} ({get_language_name(preferred_language)})."
                ),
            }
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": transcript})

        llm_started = latency.start_stage()
        first_completion = await self.llm_service.create_chat_completion(
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        first_llm_ms = latency.end_stage("llm_initial_latency", llm_started)

        assistant_message = self.llm_service.extract_assistant_message(first_completion)
        assistant_content = self.llm_service.extract_content(assistant_message)
        tool_calls = self.llm_service.extract_tool_calls(assistant_message)

        tool_results: list[dict[str, Any]] = []
        current_intent = "general_query"
        total_db_latency_ms = 0.0

        if tool_calls:
            current_intent = tool_calls[0]["name"]
            messages.append(self._tool_calls_to_message(tool_calls, assistant_content))
            for call in tool_calls:
                try:
                    parsed_args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}

                db_started = latency.start_stage()
                tool_result = await self._execute_tool(db=db, tool_name=call["name"], arguments=parsed_args)
                total_db_latency_ms += latency.end_stage("db_call_latency", db_started)

                tool_results.append(
                    {
                        "tool_name": call["name"],
                        "tool_call_id": call["id"],
                        "result": tool_result,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

            llm_followup_started = latency.start_stage()
            follow_up = await self.llm_service.create_chat_completion(messages=messages, tools=None)
            followup_ms = latency.end_stage("llm_followup_latency", llm_followup_started)
            latency.stages_ms["llm_latency"] = round(first_llm_ms + followup_ms, 2)
            final_message = self.llm_service.extract_assistant_message(follow_up)
            final_text = self.llm_service.extract_content(final_message)
        else:
            latency.stages_ms["llm_latency"] = first_llm_ms
            final_text = assistant_content

        if not final_text:
            final_text = (
                "I heard you, but I need one more detail to continue. "
                "Please share doctor name and preferred date/time."
            )

        await self.memory_store.add_conversation_message(session_id, "user", transcript)
        await self.memory_store.add_conversation_message(session_id, "assistant", final_text)
        pending_confirmations = any(
            isinstance(item.get("result"), dict) and item["result"].get("success") is False
            for item in tool_results
        )
        await self.memory_store.update_state_fields(
            session_id,
            {
                "current_intent": current_intent,
                "pending_confirmations": pending_confirmations,
                "temporary_context": {"tool_results": tool_results[-2:]},
            },
        )

        latency.stages_ms["db_latency"] = round(total_db_latency_ms, 2)

        return {
            "response_text": final_text,
            "language": preferred_language,
            "tool_results": tool_results,
            "intent": current_intent,
        }
