from __future__ import annotations

import json
from typing import Any

import dateparser
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
        "You support English, Hindi, and Tamil.\n"
        "Always respond naturally.\n"
        "Collect ALL required booking details before booking.\n"
        "Required fields are:\n"
        "1. Doctor type\n"
        "2. Appointment date\n"
        "3. Appointment time\n"
        "Never skip required details.\n"
        "Never repeat the same question if user already answered.\n"
        "For appointment operations, use tools."
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
    def _tool_calls_to_message(
        tool_calls: list[dict[str, str]],
        content: str,
    ) -> dict[str, Any]:
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

        preferred_language = (
            state.get("language_preference")
            or detected_language
            or "en"
        )

        booking_state = state.get("booking_state", {})

        transcript_lower = transcript.lower()

        await self.memory_store.update_state_fields(
            session_id,
            {
                "language_preference": preferred_language,
            },
        )

        doctor_keywords = {
            "cardiologist": "Cardiologist",
            "heart": "Cardiologist",
            "skin": "Dermatologist",
            "dermatologist": "Dermatologist",
            "eye": "Ophthalmologist",
            "ent": "ENT Specialist",
            "general": "General Physician",
            "orthopedic": "Orthopedic",
            "ortho": "Orthopedic",
            "child": "Pediatrician",
            "pediatrician": "Pediatrician",
        }

        detected_doctor = None

        for keyword, doctor in doctor_keywords.items():
            if keyword in transcript_lower:
                detected_doctor = doctor
                break

        if detected_doctor:
            booking_state["doctor_name"] = detected_doctor

        parsed_datetime = dateparser.parse(
            transcript,
            settings={"PREFER_DATES_FROM": "future"},
        )

        if parsed_datetime:
            if (
                "appointment_date" not in booking_state
                or booking_state.get("appointment_date") is None
            ):
                booking_state["appointment_date"] = parsed_datetime.date().isoformat()

            booking_state["appointment_time"] = parsed_datetime.isoformat()

        booking_keywords = [
            "book",
            "appointment",
            "doctor",
            "schedule",
        ]

        is_booking_flow = (
            any(word in transcript_lower for word in booking_keywords)
            or booking_state
        )

        await self.memory_store.update_state_fields(
            session_id,
            {
                "booking_state": booking_state,
            },
        )

        if is_booking_flow:

            if not booking_state.get("doctor_name"):
                return {
                    "response_text": "Which type of doctor would you like to consult?",
                    "language": preferred_language,
                    "tool_results": [],
                    "intent": "collect_doctor",
                }

            if not booking_state.get("appointment_date"):
                return {
                    "response_text": "Which date would you prefer for the appointment?",
                    "language": preferred_language,
                    "tool_results": [],
                    "intent": "collect_date",
                }

            if not booking_state.get("appointment_time"):
                return {
                    "response_text": "What time would you prefer?",
                    "language": preferred_language,
                    "tool_results": [],
                    "intent": "collect_time",
                }

        history = await self.memory_store.get_conversation_messages(session_id)

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{self.SYSTEM_PROMPT}\n"
                    f"User preferred language: "
                    f"{get_language_name(preferred_language)}.\n"
                    f"Current booking state: {json.dumps(booking_state)}"
                ),
            }
        ]

        messages.extend(history)

        messages.append(
            {
                "role": "user",
                "content": transcript,
            }
        )

        llm_started = latency.start_stage()

        first_completion = await self.llm_service.create_chat_completion(
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        first_llm_ms = latency.end_stage(
            "llm_initial_latency",
            llm_started,
        )

        assistant_message = self.llm_service.extract_assistant_message(
            first_completion
        )

        assistant_content = self.llm_service.extract_content(
            assistant_message
        )

        tool_calls = self.llm_service.extract_tool_calls(
            assistant_message
        )

        tool_results: list[dict[str, Any]] = []

        current_intent = "general_query"

        total_db_latency_ms = 0.0

        if tool_calls:

            current_intent = tool_calls[0]["name"]

            messages.append(
                self._tool_calls_to_message(
                    tool_calls,
                    assistant_content,
                )
            )

            for call in tool_calls:

                try:
                    parsed_args = json.loads(
                        call["arguments"] or "{}"
                    )

                except json.JSONDecodeError:
                    parsed_args = {}

                db_started = latency.start_stage()

                tool_result = await self._execute_tool(
                    db=db,
                    tool_name=call["name"],
                    arguments=parsed_args,
                )

                total_db_latency_ms += latency.end_stage(
                    "db_call_latency",
                    db_started,
                )

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
                        "content": json.dumps(
                            tool_result,
                            ensure_ascii=False,
                        ),
                    }
                )

            llm_followup_started = latency.start_stage()

            follow_up = await self.llm_service.create_chat_completion(
                messages=messages,
                tools=None,
            )

            followup_ms = latency.end_stage(
                "llm_followup_latency",
                llm_followup_started,
            )

            latency.stages_ms["llm_latency"] = round(
                first_llm_ms + followup_ms,
                2,
            )

            final_message = self.llm_service.extract_assistant_message(
                follow_up
            )

            final_text = self.llm_service.extract_content(
                final_message
            )

        else:
            latency.stages_ms["llm_latency"] = first_llm_ms
            final_text = assistant_content

        if not final_text:
            final_text = (
                "I need a few more details to continue your appointment booking."
            )

        await self.memory_store.add_conversation_message(
            session_id,
            "user",
            transcript,
        )

        await self.memory_store.add_conversation_message(
            session_id,
            "assistant",
            final_text,
        )

        await self.memory_store.update_state_fields(
            session_id,
            {
                "current_intent": current_intent,
                "booking_state": booking_state,
                "temporary_context": {
                    "tool_results": tool_results[-2:],
                    "booking_state": booking_state,
                },
            },
        )

        latency.stages_ms["db_latency"] = round(
            total_db_latency_ms,
            2,
        )

        return {
            "response_text": final_text,
            "language": preferred_language,
            "tool_results": tool_results,
            "intent": current_intent,
        }