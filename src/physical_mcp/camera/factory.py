"""Camera creation from config.

Supported backends:
- usb: Local USB/webcam via OpenCV

The CameraSource ABC in base.py allows adding new backends
(wireless, RTSP, cloud) by implementing the interface and
adding a branch here.
"""

from __future__ import annotations

from ..config import CameraConfig
from .base import CameraSource
from .usb import USBCamera


def create_camera(config: CameraConfig) -> CameraSource:
    """Create a camera instance from configuration.

    Currently supports:
    - "usb" -> USBCamera (OpenCV VideoCapture from device index)
    """
    if config.type == "usb":
        return USBCamera(
            device_index=config.device_index,
            width=config.width,
            height=config.height,
        )
    raise ValueError(f"Unknown camera type: {config.type!r}. Supported: usb")
