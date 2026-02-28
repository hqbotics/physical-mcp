"""Camera backends — USB, RTSP/HTTP, and Cloud cameras via OpenCV."""

from .base import CameraSource, Frame
from .cloud import CloudCamera
from .factory import create_camera
from .rtsp import RTSPCamera
from .usb import USBCamera

__all__ = [
    "CameraSource",
    "CloudCamera",
    "Frame",
    "RTSPCamera",
    "USBCamera",
    "create_camera",
]
