"""Physical MCP — Ambient perception MCP server."""

__version__ = "1.1.0"

from .exceptions import (
    CameraConnectionError,
    CameraError,
    CameraTimeoutError,
    ConfigError,
    PhysicalMCPError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)

__all__ = [
    "__version__",
    "PhysicalMCPError",
    "CameraError",
    "CameraConnectionError",
    "CameraTimeoutError",
    "ProviderError",
    "ProviderAuthError",
    "ProviderRateLimitError",
    "ConfigError",
]
