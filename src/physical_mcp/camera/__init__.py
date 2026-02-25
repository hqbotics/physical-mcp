"""Camera backends — USB, RTSP, HTTP MJPEG, Cloud push, and LAN auto-discovery."""

from .base import CameraSource, Frame
from .cloud import CloudCamera
from .discovery import DiscoveredCamera, discover_cameras
from .factory import create_camera
from .http_mjpeg import HTTPCamera
from .rtsp import RTSPCamera
from .usb import USBCamera

__all__ = [
    "CameraSource",
    "Frame",
    "USBCamera",
    "RTSPCamera",
    "HTTPCamera",
    "CloudCamera",
    "create_camera",
    "discover_cameras",
    "DiscoveredCamera",
]
