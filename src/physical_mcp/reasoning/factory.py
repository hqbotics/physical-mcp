"""Vision provider factory — creates the configured provider instance."""

from __future__ import annotations

import logging

from ..config import PhysicalMCPConfig
from .providers.base import VisionProvider

logger = logging.getLogger("physical-mcp")


def create_provider(config: PhysicalMCPConfig) -> VisionProvider | None:
    """Create the configured vision provider, or None if not configured."""
    r = config.reasoning
    if not r.provider or not r.api_key:
        return None

    if r.provider == "anthropic":
        from .providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=r.api_key, model=r.model)
    elif r.provider == "openai":
        from .providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(api_key=r.api_key, model=r.model)
    elif r.provider == "openai-compatible":
        from .providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key=r.api_key, model=r.model, base_url=r.base_url
        )
    elif r.provider == "google":
        from .providers.google import GoogleProvider

        return GoogleProvider(api_key=r.api_key, model=r.model)
    else:
        logger.warning(f"Unknown provider: {r.provider}")
        return None
