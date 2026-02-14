"""Anthropic (Claude) vision provider."""

from __future__ import annotations

import json

from .base import VisionProvider


class AnthropicProvider(VisionProvider):
    def __init__(self, api_key: str, model: str = "claude-haiku-4-20250414"):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "Anthropic SDK not installed. Run: pip install physical-mcp[anthropic]"
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def analyze_image(self, image_b64: str, prompt: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return response.content[0].text

    async def analyze_image_json(self, image_b64: str, prompt: str) -> dict:
        text = await self.analyze_image(image_b64, prompt)
        # Extract JSON from response — handle markdown code blocks
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model
