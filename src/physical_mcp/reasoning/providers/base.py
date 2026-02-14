"""Vision provider abstraction — all LLM providers implement this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class VisionProvider(ABC):
    """Abstract interface for vision-capable LLM providers."""

    @abstractmethod
    async def analyze_image(self, image_b64: str, prompt: str) -> str:
        """Send an image + prompt and get a text response."""
        ...

    @abstractmethod
    async def analyze_image_json(self, image_b64: str, prompt: str) -> dict:
        """Send an image + prompt and get a parsed JSON response."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
