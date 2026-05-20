from __future__ import annotations

import asyncio
from typing import Any

from sambanova import SambaNova

from backend.config.settings import get_settings


class SambaNovaService:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.SAMBANOVA_MODEL
        self.client = SambaNova(
            api_key=settings.SAMBANOVA_API_KEY,
            base_url=settings.SAMBANOVA_BASE_URL,
        )

    async def create_chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.1,
        max_tokens: int = 500,
    ) -> Any:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        return await asyncio.to_thread(self.client.chat.completions.create, **payload)

    @staticmethod
    def extract_assistant_message(completion: Any) -> Any:
        choices = getattr(completion, "choices", None) or []
        if not choices:
            return None
        return getattr(choices[0], "message", None)

    @staticmethod
    def extract_content(message: Any) -> str:
        if message is None:
            return ""
        content = getattr(message, "content", None)
        return str(content or "").strip()

    @staticmethod
    def extract_tool_calls(message: Any) -> list[dict[str, str]]:
        tool_calls = getattr(message, "tool_calls", None) or []
        parsed: list[dict[str, str]] = []
        for call in tool_calls:
            call_id = str(getattr(call, "id", ""))
            function = getattr(call, "function", None)
            name = str(getattr(function, "name", ""))
            arguments = str(getattr(function, "arguments", "{}"))
            if name:
                parsed.append(
                    {
                        "id": call_id,
                        "name": name,
                        "arguments": arguments,
                    }
                )
        return parsed

