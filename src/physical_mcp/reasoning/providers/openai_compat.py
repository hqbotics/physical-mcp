"""OpenAI-compatible vision provider.

Covers: OpenAI (GPT-4o), Kimi, DeepSeek, Together, Groq, and any service
that implements the OpenAI chat completions API with vision support.
"""

from __future__ import annotations

import asyncio
import logging

from .base import VisionProvider
from .json_extract import extract_json

logger = logging.getLogger("physical-mcp")


class OpenAICompatProvider(VisionProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "OpenAI SDK not installed. Run: pip install physical-mcp[openai]"
            )
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = model
        self._base_url = base_url

    async def analyze_image(self, image_b64: str, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "low",
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        content = response.choices[0].message.content
        if content is None:
            # Some providers return None for content (e.g. refusal, empty response)
            raise ValueError("Provider returned empty content (None)")
        return content

    async def analyze_image_json(self, image_b64: str, prompt: str) -> dict:
        text = await self.analyze_image(image_b64, prompt)
        return extract_json(text)

    @property
    def provider_name(self) -> str:
        if self._base_url:
            return f"openai-compatible ({self._base_url})"
        return "openai"

    async def warmup(self) -> None:
        """Pre-establish HTTP connection to reduce first-call latency."""
        try:
            await asyncio.wait_for(self._client.models.list(), timeout=5.0)
            logger.info("API connection warmed up (%s)", self._base_url or "openai")
        except Exception:
            # Best-effort — connection pool is warmed even if the call fails
            logger.debug("Warmup call failed (connection may still be pooled)")

    @property
    def model_name(self) -> str:
        return self._model
