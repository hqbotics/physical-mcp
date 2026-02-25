"""Anthropic (Claude) vision provider."""

from __future__ import annotations

from .base import VisionProvider
from .json_extract import extract_json


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
            max_tokens=1024,
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
        return extract_json(text)

    async def analyze_images(self, images_b64: list[str], prompt: str) -> str:
        """Send multiple images in a single API call for temporal context."""
        content: list[dict] = []
        for img in images_b64:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": img,
                    },
                }
            )
        content.append({"type": "text", "text": prompt})
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text

    async def analyze_images_json(self, images_b64: list[str], prompt: str) -> dict:
        text = await self.analyze_images(images_b64, prompt)
        return extract_json(text)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model
