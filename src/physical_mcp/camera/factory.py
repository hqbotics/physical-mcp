"""Camera creation from config.

Today: USB only (OpenCV).
Future: add RTSP, GoPro, HTTP by implementing CameraSource + one elif here.
"""

from __future__ import annotations

from ..config import CameraConfig
from .base import CameraSource
from .usb import USBCamera


def create_camera(config: CameraConfig) -> CameraSource:
    """Create a camera instance from configuration.

    Supported types:
    - "usb" -> USBCamera (OpenCV VideoCapture)

    Future types (implement CameraSource + add elif):
    - "rtsp" -> RTSP/IP camera streams
    - "gopro" -> GoPro wireless API
    - "http" -> HTTP MJPEG streams
    """
    if config.type == "usb":
        return USBCamera(
            device_index=config.device_index,
            width=config.width,
            height=config.height,
        )
    raise ValueError(
        f"Unknown camera type: {config.type!r}. Supported: usb"
    )
