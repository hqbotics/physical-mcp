"""Custom exception hierarchy for physical-mcp.

All physical-mcp exceptions inherit from PhysicalMCPError, allowing users
to catch broad or specific errors:

    try:
        camera = RTSPCamera(url="rtsp://...")
        await camera.open()
    except CameraError as e:
        print(f"Camera problem: {e}")
    except PhysicalMCPError as e:
        print(f"physical-mcp error: {e}")
"""

from __future__ import annotations


class PhysicalMCPError(Exception):
    """Base exception for all physical-mcp errors."""


class CameraError(PhysicalMCPError):
    """Raised when a camera operation fails (open, capture, reconnect)."""


class CameraConnectionError(CameraError):
    """Raised when a camera cannot be opened or connection is lost."""


class CameraTimeoutError(CameraError):
    """Raised when a camera operation times out."""


class ProviderError(PhysicalMCPError):
    """Raised when a vision LLM provider call fails."""


class ProviderAuthError(ProviderError):
    """Raised when provider authentication fails (invalid API key)."""


class ProviderRateLimitError(ProviderError):
    """Raised when a provider rate-limits the request."""


class ConfigError(PhysicalMCPError):
    """Raised when configuration is invalid or missing."""
