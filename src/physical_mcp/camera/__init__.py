"""Camera backends — USB and RTSP/HTTP cameras via OpenCV."""

from .base import CameraSource, Frame
from .factory import create_camera
from .rtsp import RTSPCamera
from .usb import USBCamera

__all__ = [
    "CameraSource",
    "Frame",
    "RTSPCamera",
    "USBCamera",
    "create_camera",
]
