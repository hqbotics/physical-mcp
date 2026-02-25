"""Camera backends — USB cameras via OpenCV."""

from .base import CameraSource, Frame
from .factory import create_camera
from .usb import USBCamera

__all__ = [
    "CameraSource",
    "Frame",
    "USBCamera",
    "create_camera",
]
