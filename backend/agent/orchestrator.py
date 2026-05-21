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
        "You are a multilingual clinical appointment booking voice assistant.\n"
        "Supported languages: English, Tamil, Hindi.\n"
        "Always ask doctor specialization first.\n"
        "Then ask appointment date.\n"
        "Then ask appointment time.\n"
        "Never skip required booking fields.\n"
        "Never repeat already answered questions.\n"
        "Use appointment tools whenever required.\n"
        "Respond naturally in user's preferred language.\n"
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

        return {
            "success": False,
            "message": f"Unknown tool: {tool_name}",
        }

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

        # ---------------------------------------------------
        # INITIAL STATE
        # ---------------------------------------------------

        state = await self.memory_store.get_session_state(
            session_id
        )

        preferred_language = (
            state.get("language_preference")
            or detected_language
            or "en"
        )

        transcript_lower = transcript.lower().strip()

        # ---------------------------------------------------
        # NEW BOOKING RESET
        # ---------------------------------------------------

        new_booking_phrases = [

            # English
            "book appointment",
            "book a appointment",
            "new appointment",
            "schedule appointment",
            "appointment booking",

            # Tamil
            "அப்பாயின்மென்ட் புக்",
            "புதிய அப்பாயின்மென்ட்",

            # Hindi
            "अपॉइंटमेंट बुक",
            "नई अपॉइंटमेंट",
        ]

        is_new_booking = any(
            phrase in transcript_lower
            for phrase in new_booking_phrases
        )

        if is_new_booking:

            # FULL SESSION RESET
            await self.memory_store.clear_session(
                session_id
            )

            booking_state = {}

            state = {}

            await self.memory_store.update_state_fields(
                session_id,
                {
                    "booking_state": {},
                    "current_intent": "book_appointment",
                    "temporary_context": {},
                    "language_preference": preferred_language,
                },
            )

        else:

            booking_state = state.get(
                "booking_state",
                {},
            )

        # ---------------------------------------------------
        # SAVE LANGUAGE
        # ---------------------------------------------------

        await self.memory_store.update_state_fields(
            session_id,
            {
                "language_preference": preferred_language,
            },
        )

        # ---------------------------------------------------
        # MULTILINGUAL DOCTOR KEYWORDS
        # ---------------------------------------------------

        doctor_keywords = {

            # ---------------------------------------------------
            # CARDIOLOGIST
            # ---------------------------------------------------

            "cardiologist": "Cardiologist",
            "heart": "Cardiologist",
            "heart doctor": "Cardiologist",

            # Tamil
            "இதயம்": "Cardiologist",
            "இதய": "Cardiologist",

            # Hindi
            "दिल": "Cardiologist",

            # ---------------------------------------------------
            # DERMATOLOGIST
            # ---------------------------------------------------

            "skin": "Dermatologist",
            "skin doctor": "Dermatologist",
            "dermatologist": "Dermatologist",

            # Tamil
            "தோல்": "Dermatologist",

            # Hindi
            "त्वचा": "Dermatologist",

            # ---------------------------------------------------
            # EYE
            # ---------------------------------------------------

            "eye": "Ophthalmologist",
            "eye doctor": "Ophthalmologist",

            # Tamil
            "கண்": "Ophthalmologist",
            "கண்ணு": "Ophthalmologist",

            # Hindi
            "आंख": "Ophthalmologist",

            # ---------------------------------------------------
            # ORTHOPEDIC
            # ---------------------------------------------------

            "bone": "Orthopedic",
            "ortho": "Orthopedic",
            "orthopedic": "Orthopedic",

            # Tamil
            "எலும்பு": "Orthopedic",
            "மூட்டு": "Orthopedic",

            # Hindi
            "हड्डी": "Orthopedic",

            # ---------------------------------------------------
            # ENT
            # ---------------------------------------------------

            "ent": "ENT Specialist",
            "ear": "ENT Specialist",
            "nose": "ENT Specialist",
            "throat": "ENT Specialist",

            # Tamil
            "காது": "ENT Specialist",
            "மூக்கு": "ENT Specialist",
            "தொண்டை": "ENT Specialist",

            # Hindi
            "नाक": "ENT Specialist",
            "गला": "ENT Specialist",

            # ---------------------------------------------------
            # GYNECOLOGIST
            # ---------------------------------------------------

            "gynecologist": "Gynecologist",
            "pregnancy": "Gynecologist",
            "women": "Gynecologist",

            # Tamil
            "பெண்கள்": "Gynecologist",
            "கர்ப்பம்": "Gynecologist",

            # Hindi
            "महिला": "Gynecologist",

            # ---------------------------------------------------
            # PEDIATRICIAN
            # ---------------------------------------------------

            "child": "Pediatrician",
            "children": "Pediatrician",
            "baby": "Pediatrician",

            # Tamil
            "குழந்தை": "Pediatrician",

            # Hindi
            "बच्चा": "Pediatrician",

            # ---------------------------------------------------
            # GENERAL PHYSICIAN
            # ---------------------------------------------------

            "general": "General Physician",
            "fever": "General Physician",
            "cold": "General Physician",
            "cough": "General Physician",

            # Tamil
            "காய்ச்சல்": "General Physician",
            "சளி": "General Physician",

            # Hindi
            "बुखार": "General Physician",
        }

        # ---------------------------------------------------
        # SMART MULTILINGUAL DOCTOR DETECTION
        # ---------------------------------------------------

        detected_doctor = None

        normalized_text = (
            transcript_lower
            .replace(",", " ")
            .replace(".", " ")
            .replace("?", " ")
            .replace("!", " ")
            .strip()
        )

        words = normalized_text.split()

        for keyword, doctor in doctor_keywords.items():

            keyword_normalized = keyword.lower().strip()

            # Exact phrase match
            if keyword_normalized in normalized_text:
                detected_doctor = doctor
                break

            # Word-level match
            if keyword_normalized in words:
                detected_doctor = doctor
                break

        if detected_doctor:

            booking_state["doctor_name"] = detected_doctor

        # ---------------------------------------------------
        # DATE EXTRACTION
        # ---------------------------------------------------

        date_keywords = [

            # English
            "today",
            "tomorrow",
            "day after tomorrow",

            # Tamil
            "இன்று",
            "நாளை",

            # Hindi
            "आज",
            "कल",
        ]

        parsed_datetime = dateparser.parse(
            transcript,
            languages=["en", "ta", "hi"],
            settings={
                "PREFER_DATES_FROM": "future",
            },
        )

        if parsed_datetime:

            if any(
                word in transcript_lower
                for word in date_keywords
            ):

                booking_state["appointment_date"] = (
                    parsed_datetime.date().isoformat()
                )

        # ---------------------------------------------------
        # TIME EXTRACTION
        # ---------------------------------------------------

        time_keywords = {

            # English
            "morning": "morning",
            "afternoon": "afternoon",
            "evening": "evening",
            "night": "night",

            # Tamil
            "காலை": "morning",
            "மதியம்": "afternoon",
            "சாயங்காலம்": "evening",
            "இரவு": "night",

            # Hindi
            "सुबह": "morning",
            "दोपहर": "afternoon",
            "शाम": "evening",
            "रात": "night",
        }

        for keyword, value in time_keywords.items():

            if keyword in transcript_lower:

                booking_state["appointment_time"] = value
                break

        # ---------------------------------------------------
        # BOOKING FLOW DETECTION
        # ---------------------------------------------------

        booking_keywords = [

            # English
            "book",
            "appointment",
            "doctor",
            "schedule",
            "consult",

            # Tamil
            "அப்பாயின்மென்ட்",
            "டாக்டர்",
            "மருத்துவர்",

            # Hindi
            "अपॉइंटमेंट",
            "डॉक्टर",
            "परामर्श",
        ]

        is_booking_flow = (
            any(
                word in transcript_lower
                for word in booking_keywords
            )
            or state.get("current_intent")
            == "book_appointment"
            or bool(booking_state)
        )

        # ---------------------------------------------------
        # SAVE BOOKING STATE
        # ---------------------------------------------------

        await self.memory_store.update_state_fields(
            session_id,
            {
                "booking_state": booking_state,
            },
        )

        # ---------------------------------------------------
        # STRICT SLOT FILLING
        # ---------------------------------------------------

        if is_booking_flow:

            # ASK DOCTOR

            if not booking_state.get("doctor_name"):

                if preferred_language == "ta":

                    question = (
                        "எந்த doctor அல்லது "
                        "specialization வேண்டும்?"
                    )

                elif preferred_language == "hi":

                    question = (
                        "आप किस प्रकार के डॉक्टर "
                        "से परामर्श करना चाहते हैं?"
                    )

                else:

                    question = (
                        "Which type of doctor "
                        "would you like to consult?"
                    )

                return {
                    "response_text": question,
                    "language": preferred_language,
                    "tool_results": [],
                    "intent": "collect_doctor",
                }

            # ASK DATE

            if not booking_state.get("appointment_date"):

                if preferred_language == "ta":

                    question = (
                        "எந்த தேதிக்கு "
                        "appointment வேண்டும்?"
                    )

                elif preferred_language == "hi":

                    question = (
                        "आप किस तारीख के लिए "
                        "appointment चाहते हैं?"
                    )

                else:

                    question = (
                        "Which date would you prefer "
                        "for the appointment?"
                    )

                return {
                    "response_text": question,
                    "language": preferred_language,
                    "tool_results": [],
                    "intent": "collect_date",
                }

            # ASK TIME

            if not booking_state.get("appointment_time"):

                if preferred_language == "ta":

                    question = (
                        "உங்களுக்கு preferred time "
                        "ஏதாவது இருக்கிறதா?"
                    )

                elif preferred_language == "hi":

                    question = (
                        "क्या आपको कोई preferred "
                        "time चाहिए?"
                    )

                else:

                    question = (
                        "What time would you prefer?"
                    )

                return {
                    "response_text": question,
                    "language": preferred_language,
                    "tool_results": [],
                    "intent": "collect_time",
                }

        # ---------------------------------------------------
        # CONVERSATION HISTORY
        # ---------------------------------------------------

        history = (
            await self.memory_store.get_conversation_messages(
                session_id
            )
        )

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{self.SYSTEM_PROMPT}\n"
                    f"Preferred language: "
                    f"{get_language_name(preferred_language)}.\n"
                    f"Booking state: "
                    f"{json.dumps(booking_state)}"
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

        # ---------------------------------------------------
        # LLM CALL
        # ---------------------------------------------------

        llm_started = latency.start_stage()

        first_completion = (
            await self.llm_service.create_chat_completion(
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
        )

        first_llm_ms = latency.end_stage(
            "llm_initial_latency",
            llm_started,
        )

        assistant_message = (
            self.llm_service.extract_assistant_message(
                first_completion
            )
        )

        assistant_content = (
            self.llm_service.extract_content(
                assistant_message
            )
        )

        tool_calls = (
            self.llm_service.extract_tool_calls(
                assistant_message
            )
        )

        tool_results: list[dict[str, Any]] = []

        current_intent = "general_query"

        total_db_latency_ms = 0.0

        # ---------------------------------------------------
        # TOOL EXECUTION
        # ---------------------------------------------------

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

            follow_up = (
                await self.llm_service.create_chat_completion(
                    messages=messages,
                    tools=None,
                )
            )

            followup_ms = latency.end_stage(
                "llm_followup_latency",
                llm_followup_started,
            )

            latency.stages_ms["llm_latency"] = round(
                first_llm_ms + followup_ms,
                2,
            )

            final_message = (
                self.llm_service.extract_assistant_message(
                    follow_up
                )
            )

            final_text = (
                self.llm_service.extract_content(
                    final_message
                )
            )

        else:

            latency.stages_ms["llm_latency"] = (
                first_llm_ms
            )

            final_text = assistant_content

        if not final_text:

            final_text = (
                "I need a few more details "
                "to continue your appointment booking."
            )

        # ---------------------------------------------------
        # SAVE CONVERSATION
        # ---------------------------------------------------

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