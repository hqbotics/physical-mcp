"""Camera creation from config.

Supported backends:
- usb: Local USB/webcam via OpenCV
- rtsp: RTSP/HTTP IP camera stream via OpenCV + ffmpeg
"""

from __future__ import annotations

from ..config import CameraConfig
from .base import CameraSource
from .rtsp import RTSPCamera
from .usb import USBCamera


def create_camera(config: CameraConfig) -> CameraSource:
    """Create a camera instance from configuration."""
    if config.type == "usb":
        return USBCamera(
            device_index=config.device_index,
            width=config.width,
            height=config.height,
        )
    if config.type in ("rtsp", "http"):
        return RTSPCamera(
            url=config.url or "",
            camera_id=config.id,
            width=config.width,
            height=config.height,
        )
    raise ValueError(
        f"Unknown camera type: {config.type!r}. Supported: usb, rtsp, http"
    )
