"""OpenAI-compatible vision provider.

Covers: OpenAI (GPT-4o), Kimi, DeepSeek, Together, Groq, and any service
that implements the OpenAI chat completions API with vision support.
"""

from __future__ import annotations

import json

from .base import VisionProvider


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
        return self._extract_json(text)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from LLM response, handling markdown fences and noise.

        Tries multiple strategies:
        1. Strip markdown code fences (```json ... ```)
        2. Direct JSON parse
        3. Find outermost { } boundaries and parse
        4. Truncation repair (close open brackets/braces)
        """
        text = text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            end = -1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[1:end]).strip()

        # Strategy 1: Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Find JSON object boundaries (handles leading/trailing noise)
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
            # Strategy 3: Truncation repair on the extracted substring
            fragment = text[start:].rstrip().rstrip(",")
            open_brackets = fragment.count("[") - fragment.count("]")
            fragment += "]" * open_brackets
            open_braces = fragment.count("{") - fragment.count("}")
            fragment += "}" * open_braces
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                pass

        # Nothing worked
        raise json.JSONDecodeError("Could not extract JSON from LLM response", text, 0)

    @property
    def provider_name(self) -> str:
        if self._base_url:
            return f"openai-compatible ({self._base_url})"
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model
