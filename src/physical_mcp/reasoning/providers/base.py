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

    async def analyze_images(self, images_b64: list[str], prompt: str) -> str:
        """Send multiple images + prompt. Default: use last (most recent) frame."""
        return await self.analyze_image(images_b64[-1], prompt)

    async def analyze_images_json(self, images_b64: list[str], prompt: str) -> dict:
        """Send multiple images + prompt, return JSON. Default: use last frame."""
        return await self.analyze_image_json(images_b64[-1], prompt)

    async def warmup(self) -> None:
        """Pre-establish HTTP connections. Override in subclasses for real warmup."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
