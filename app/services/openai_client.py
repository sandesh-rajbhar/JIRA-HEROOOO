from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings

LOGGER = logging.getLogger(__name__)

JSON_SYSTEM_PROMPT = (
    "You are a backend service that must respond with valid JSON only. "
    "Never wrap JSON in markdown fences. Never add explanations outside JSON."
)


class OpenAIJSONClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("OpenAI client is not configured.")

        LOGGER.debug("Sending JSON prompt to OpenAI model %s", self._settings.openai_model)
        response = await self._client.chat.completions.create(
            model=self._settings.openai_model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": JSON_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            timeout=self._settings.llm_timeout_seconds,
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty response.")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            LOGGER.exception("Failed to decode OpenAI JSON response: %s", content)
            raise RuntimeError("OpenAI returned invalid JSON.") from exc
