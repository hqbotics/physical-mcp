"""Google Gemini vision provider."""

from __future__ import annotations

import base64
import json

from .base import VisionProvider


class GoogleProvider(VisionProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        try:
            from google import genai
        except ImportError:
            raise ImportError(
                "Google GenAI SDK not installed. Run: pip install physical-mcp[google]"
            )
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def analyze_image(self, image_b64: str, prompt: str) -> str:
        from google.genai import types

        image_bytes = base64.b64decode(image_b64)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        text_part = types.Part.from_text(text=prompt)

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[image_part, text_part],
            config=types.GenerateContentConfig(max_output_tokens=500),
        )
        return response.text

    async def analyze_image_json(self, image_b64: str, prompt: str) -> dict:
        text = await self.analyze_image(image_b64, prompt)
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def model_name(self) -> str:
        return self._model
