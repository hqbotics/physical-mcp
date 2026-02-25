"""Shared camera health utilities — used by both MCP server and Vision API."""

from __future__ import annotations

from typing import Any


def default_camera_health(camera_id: str) -> dict[str, Any]:
    """Consistent fallback shape for unknown/malformed camera health."""
    return {
        "camera_id": camera_id,
        "camera_name": camera_id,
        "consecutive_errors": 0,
        "backoff_until": None,
        "last_success_at": None,
        "last_error": "",
        "last_frame_at": None,
        "status": "unknown",
        "message": "No health data yet. Start monitoring first.",
    }


def normalize_camera_health(
    camera_id: str, health: dict[str, Any] | None
) -> dict[str, Any]:
    """Fill missing camera-health keys with safe defaults."""
    base = default_camera_health(camera_id)
    if not isinstance(health, dict):
        return base
    merged = {**base, **health}
    merged["camera_id"] = str(merged.get("camera_id") or camera_id)
    if not merged.get("camera_name"):
        merged["camera_name"] = merged["camera_id"]
    return merged
