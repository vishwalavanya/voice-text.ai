from __future__ import annotations

import json
import logging
import re
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

logger = logging.getLogger(__name__)


class VoiceAgentOrchestrator:

    SYSTEM_PROMPT = """
You are a multilingual clinical voice AI assistant.

Supported languages:
- English
- Tamil
- Hindi

Your responsibilities:
1. Book appointments
2. Cancel appointments
3. Reschedule appointments
4. Answer clinic queries

BOOKING RULES:
- ALWAYS collect:
    1. doctor specialization
    2. appointment date
    3. appointment time
- NEVER skip fields
- NEVER ask already answered fields
- NEVER repeat same question unnecessarily
- Understand mixed language input
- Understand natural speech

Examples:
- "tomorrow night eye doctor"
- "இரவு cardiologist"
- "कल सुबह skin doctor"

Extract intelligently from user sentences.
"""

    EXTRACTION_PROMPT = """
Extract appointment booking fields from the user message.

Return ONLY valid JSON.

Fields:
- doctor_name
- appointment_date
- appointment_time

Rules:
- If not found return null
- Understand English Tamil Hindi mixed language
- Convert doctor meaning intelligently

Doctor mapping:
eye -> Ophthalmologist
skin -> Dermatologist
heart -> Cardiologist
bone -> Orthopedic
ear/nose/throat -> ENT Specialist
women/pregnancy -> Gynecologist
child/baby -> Pediatrician

Example response:
{
  "doctor_name": "Cardiologist",
  "appointment_date": "tomorrow",
  "appointment_time": "evening"
}
"""

    def __init__(
        self,
        memory_store: RedisMemoryStore,
    ) -> None:

        self.memory_store = memory_store
        self.llm_service = SambaNovaService()

    async def _extract_booking_fields(
        self,
        transcript: str,
    ) -> dict[str, Any]:

        messages = [
            {
                "role": "system",
                "content": self.EXTRACTION_PROMPT,
            },
            {
                "role": "user",
                "content": transcript,
            },
        ]

        completion = await self.llm_service.create_chat_completion(
            messages=messages,
            tools=None,
            temperature=0.0,
            max_tokens=200,
        )

        message = self.llm_service.extract_assistant_message(
            completion
        )

        content = self.llm_service.extract_content(
            message
        )

        try:

            cleaned = re.sub(
                r"```json|```",
                "",
                content,
            ).strip()

            parsed = json.loads(cleaned)

            return {
                "doctor_name": parsed.get("doctor_name"),
                "appointment_date": parsed.get("appointment_date"),
                "appointment_time": parsed.get("appointment_time"),
            }

        except Exception as exc:
            logger.debug("Failed to extract booking fields | error=%s", str(exc))

            return {
                "doctor_name": None,
                "appointment_date": None,
                "appointment_time": None,
            }

    async def _execute_tool(
        self,
        db: AsyncSession,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:

        if tool_name == "check_availability":

            return await check_availability(
                db=db,
                **arguments,
            )

        if tool_name == "book_appointment":

            return await book_appointment(
                db=db,
                **arguments,
            )

        if tool_name == "cancel_appointment":

            return await cancel_appointment(
                db=db,
                **arguments,
            )

        if tool_name == "reschedule_appointment":

            return await reschedule_appointment(
                db=db,
                **arguments,
            )

        return {
            "success": False,
            "message": f"Unknown tool {tool_name}",
        }

    async def handle_turn(
        self,
        session_id: str,
        transcript: str,
        detected_language: str,
        db: AsyncSession,
        latency: LatencyTracker,
    ) -> dict[str, Any]:

        # ============================================================
        # LOAD EXISTING SESSION STATE
        # ============================================================
        
        state = await self.memory_store.get_session_state(session_id)
        
        logger.info(
            "Session state loaded | session=%s | has_booking_state=%s",
            session_id,
            "booking_state" in state
        )

        transcript_lower = transcript.lower().strip()

        preferred_language = (
            state.get("language_preference")
            or detected_language
            or "en"
        )

        # ============================================================
        # RESET FLOW (NEW BOOKING TRIGGER)
        # ============================================================

        new_booking_phrases = [

            # English
            "book appointment",
            "book a appointment",
            "schedule appointment",
            "new appointment",

            # Tamil
            "அப்பாயின்மென்ட் புக்",

            # Hindi
            "अपॉइंटमेंट बुक",
        ]

        is_new_booking = any(
            phrase in transcript_lower
            for phrase in new_booking_phrases
        )

        if is_new_booking:
            logger.info(
                "New booking detected | session=%s | clearing previous state",
                session_id
            )

            await self.memory_store.clear_session(
                session_id
            )

            booking_state = {}

        else:

            booking_state = state.get(
                "booking_state",
                {},
            )
            
            logger.debug(
                "Continuing booking | session=%s | current_state=%s",
                session_id,
                {
                    "doctor": booking_state.get("doctor_name"),
                    "date": booking_state.get("appointment_date"),
                    "time": booking_state.get("appointment_time"),
                }
            )

        # ============================================================
        # AI EXTRACTION (LLM-based)
        # ============================================================

        extracted = await self._extract_booking_fields(
            transcript
        )
        
        logger.debug(
            "Extracted booking fields | session=%s | extracted=%s",
            session_id,
            {
                "doctor": extracted.get("doctor_name"),
                "date": extracted.get("appointment_date"),
                "time": extracted.get("appointment_time"),
            }
        )

        # Update booking state with extracted fields
        if extracted.get("doctor_name"):

            booking_state["doctor_name"] = (
                extracted["doctor_name"]
            )
            logger.debug(
                "Updated doctor | session=%s | doctor=%s",
                session_id,
                extracted["doctor_name"]
            )

        if extracted.get("appointment_date"):

            booking_state["appointment_date"] = (
                extracted["appointment_date"]
            )
            logger.debug(
                "Updated date | session=%s | date=%s",
                session_id,
                extracted["appointment_date"]
            )

        if extracted.get("appointment_time"):

            booking_state["appointment_time"] = (
                extracted["appointment_time"]
            )
            logger.debug(
                "Updated time | session=%s | time=%s",
                session_id,
                extracted["appointment_time"]
            )

        # ============================================================
        # SAVE STATE TO REDIS (PERSISTENCE)
        # ============================================================

        await self.memory_store.update_state_fields(
            session_id,
            {
                "booking_state": booking_state,
                "language_preference": preferred_language,
                "current_intent": "book_appointment",
            },
        )
        
        logger.info(
            "State saved | session=%s | booking_state=%s",
            session_id,
            {
                "doctor": booking_state.get("doctor_name"),
                "date": booking_state.get("appointment_date"),
                "time": booking_state.get("appointment_time"),
            }
        )

        # ============================================================
        # SLOT FILLING (What's missing?)
        # ============================================================

        if not booking_state.get("doctor_name"):
            logger.info("Missing doctor | session=%s", session_id)

            if preferred_language == "ta":

                response = (
                    "எந்த doctor அல்லது specialization வேண்டும்?"
                )

            elif preferred_language == "hi":

                response = (
                    "आप किस प्रकार के डॉक्टर से परामर्श करना चाहते हैं?"
                )

            else:

                response = (
                    "Which type of doctor would you like to consult?"
                )

            return {
                "response_text": response,
                "language": preferred_language,
                "intent": "collect_doctor",
                "tool_results": [],
            }

        if not booking_state.get("appointment_date"):
            logger.info("Missing date | session=%s", session_id)

            if preferred_language == "ta":

                response = (
                    "எந்த தேதிக்கு appointment வேண்டும்?"
                )

            elif preferred_language == "hi":

                response = (
                    "आप किस तारीख के लिए appointment चाहते हैं?"
                )

            else:

                response = (
                    "Which date would you prefer for the appointment?"
                )

            return {
                "response_text": response,
                "language": preferred_language,
                "intent": "collect_date",
                "tool_results": [],
            }

        if not booking_state.get("appointment_time"):
            logger.info("Missing time | session=%s", session_id)

            if preferred_language == "ta":

                response = (
                    "உங்களுக்கு preferred time ஏதாவது இருக்கிறதா?"
                )

            elif preferred_language == "hi":

                response = (
                    "क्या आपको कोई preferred time चाहिए?"
                )

            else:

                response = (
                    "What time would you prefer?"
                )

            return {
                "response_text": response,
                "language": preferred_language,
                "intent": "collect_time",
                "tool_results": [],
            }

        # ============================================================
        # ALL FIELDS COLLECTED - CHECK AVAILABILITY
        # ============================================================

        logger.info(
            "All fields collected | session=%s | doctor=%s | date=%s | time=%s",
            session_id,
            booking_state.get("doctor_name"),
            booking_state.get("appointment_date"),
            booking_state.get("appointment_time"),
        )

        tool_args = {
            "intent": "book_appointment",
            "doctor_specialization": booking_state.get(
                "doctor_name"
            ),
            "preferred_date": booking_state.get(
                "appointment_date"
            ),
            "preferred_time": booking_state.get(
                "appointment_time"
            ),
        }

        availability_result = await check_availability(
            db=db,
            **tool_args,
        )

        logger.info(
            "Availability checked | session=%s | success=%s",
            session_id,
            availability_result.get("success")
        )

        # ============================================================
        # TOOL RESPONSE
        # ============================================================

        tool_results = [
            {
                "tool_name": "check_availability",
                "result": availability_result,
            }
        ]

        # ============================================================
        # FINAL RESPONSE FROM LLM
        # ============================================================

        messages = [
            {
                "role": "system",
                "content": (
                    f"{self.SYSTEM_PROMPT}\n"
                    f"Preferred language: "
                    f"{get_language_name(preferred_language)}"
                ),
            },
            {
                "role": "user",
                "content": transcript,
            },
            {
                "role": "tool",
                "content": json.dumps(
                    availability_result,
                    ensure_ascii=False,
                ),
            },
        ]

        completion = await self.llm_service.create_chat_completion(
            messages=messages,
            tools=None,
            temperature=0.2,
            max_tokens=300,
        )

        assistant_message = (
            self.llm_service.extract_assistant_message(
                completion
            )
        )

        final_text = (
            self.llm_service.extract_content(
                assistant_message
            )
        )

        logger.debug(
            "Final response generated | session=%s | length=%d",
            session_id,
            len(final_text)
        )

        # ============================================================
        # SAVE CONVERSATION TO HISTORY
        # ============================================================

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

        logger.info(
            "Turn completed | session=%s | intent=book_appointment",
            session_id
        )

        return {
            "response_text": final_text,
            "language": preferred_language,
            "intent": "book_appointment",
            "tool_results": tool_results,
        }