"""Camera creation from config.

Supported backends:
- usb: Local USB/webcam via OpenCV
- rtsp: RTSP/IP camera streams (Reolink, Tapo, Hikvision, etc.)
- http: HTTP MJPEG streams (ESP32-CAM, OctoPrint, cheap IP cams)
"""

from __future__ import annotations

from ..config import CameraConfig
from .base import CameraSource
from .http_mjpeg import HTTPCamera
from .rtsp import RTSPCamera
from .usb import USBCamera


def create_camera(config: CameraConfig) -> CameraSource:
    """Create a camera instance from configuration.

    Supported types:
    - "usb"  -> USBCamera (OpenCV VideoCapture from device index)
    - "rtsp" -> RTSPCamera (RTSP/IP stream via OpenCV + FFmpeg)
    - "http" -> HTTPCamera (HTTP MJPEG stream)
    """
    if config.type == "usb":
        return USBCamera(
            device_index=config.device_index,
            width=config.width,
            height=config.height,
        )
    if config.type == "rtsp":
        if not config.url:
            raise ValueError(
                "RTSP camera requires a 'url' field "
                "(e.g. rtsp://admin:pass@192.168.1.100:554/stream)"
            )
        return RTSPCamera(
            url=config.url,
            camera_id=config.id,
            width=config.width,
            height=config.height,
        )
    if config.type == "http":
        if not config.url:
            raise ValueError(
                "HTTP camera requires a 'url' field "
                "(e.g. http://192.168.1.50:81/stream)"
            )
        return HTTPCamera(
            url=config.url,
            camera_id=config.id,
            width=config.width,
            height=config.height,
        )
    raise ValueError(
        f"Unknown camera type: {config.type!r}. Supported: usb, rtsp, http"
    )
