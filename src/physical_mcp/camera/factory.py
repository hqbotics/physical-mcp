"""Camera creation from config.

Supported backends:
- usb: Local USB/webcam via OpenCV
- rtsp: RTSP/HTTP IP camera stream via OpenCV + ffmpeg
- cloud: Receives pushed JPEG frames via HTTP POST from a relay agent
"""

from __future__ import annotations

from ..config import CameraConfig
from .base import CameraSource
from .cloud import CloudCamera
from .rtsp import RTSPCamera
from .usb import USBCamera


def create_camera(config: CameraConfig) -> CameraSource:
    """Create a camera instance from configuration.

    Auto-detects the backend when a URL is provided but type is "usb" (default).
    This covers the common case where a user adds ``url: rtsp://...`` to their
    config without explicitly changing ``type: rtsp``.
    """
    cam_type = config.type

    # Auto-detect: if a URL is set, infer the camera type from the scheme
    if config.url and cam_type == "usb":
        url_lower = config.url.lower()
        if url_lower.startswith("rtsp://"):
            cam_type = "rtsp"
        elif url_lower.startswith(("http://", "https://")):
            cam_type = "http"

    if cam_type == "usb":
        return USBCamera(
            device_index=config.device_index,
            width=config.width,
            height=config.height,
        )
    if cam_type in ("rtsp", "http"):
        return RTSPCamera(
            url=config.url or "",
            camera_id=config.id,
            width=config.width,
            height=config.height,
        )
    if cam_type == "cloud":
        return CloudCamera(
            camera_id=config.id,
            auth_token=config.auth_token,
        )
    raise ValueError(
        f"Unknown camera type: {cam_type!r}. Supported: usb, rtsp, http, cloud"
    )
