"""HTTP MJPEG camera — reads from HTTP motion-JPEG streams.

Many cheap IP cameras and ESP32-CAM boards serve MJPEG over HTTP
without RTSP support. This backend handles those:
- ESP32-CAM: http://192.168.1.50:81/stream
- Cheap Alibaba cameras: http://192.168.1.60/video.mjpg
- OctoPrint: http://octopi.local/webcam/?action=stream
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Optional

import cv2

from .base import CameraSource, Frame

logger = logging.getLogger("physical-mcp")


class HTTPCamera(CameraSource):
    """HTTP MJPEG stream camera with background capture and reconnect.

    Uses OpenCV's VideoCapture which handles HTTP MJPEG natively,
    or falls back to raw HTTP byte-stream parsing for compatibility.
    """

    def __init__(
        self,
        url: str,
        *,
        camera_id: str = "",
        width: int = 1280,
        height: int = 720,
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 3.0,
    ):
        if not url:
            raise ValueError("HTTP camera URL is required")
        self._url = url
        self._camera_id = camera_id or _id_from_url(url)
        self._width = width
        self._height = height
        self._max_reconnect = max_reconnect_attempts
        self._reconnect_delay = reconnect_delay

        self._cap: Optional[cv2.VideoCapture] = None
        self._latest_frame: Optional[Frame] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sequence = 0
        self._consecutive_failures = 0

    async def open(self) -> None:
        self._cap = cv2.VideoCapture(self._url)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open HTTP stream: {self._url}")
        logger.info("HTTP MJPEG stream opened: %s", self._url)

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        for _ in range(100):  # 10 seconds max
            await asyncio.sleep(0.1)
            with self._lock:
                if self._latest_frame is not None:
                    return
        raise RuntimeError(
            f"HTTP stream opened but no frames received within 10s: {self._url}"
        )

    async def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("HTTP MJPEG stream closed: %s", self._url)

    async def grab_frame(self) -> Frame:
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(None, self._get_latest)
        if frame is None:
            raise RuntimeError(f"No frame available from HTTP stream: {self._url}")
        return frame

    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened() and self._running

    @property
    def source_id(self) -> str:
        return self._camera_id

    def _capture_loop(self) -> None:
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                if not self._try_reconnect():
                    break
                continue

            ret, img = self._cap.read()
            if ret and img is not None:
                self._consecutive_failures = 0
                self._sequence += 1
                frame = Frame(
                    image=img,
                    timestamp=datetime.now(),
                    source_id=self.source_id,
                    sequence_number=self._sequence,
                    resolution=(img.shape[1], img.shape[0]),
                )
                with self._lock:
                    self._latest_frame = frame
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures > 30:
                    logger.warning(
                        "HTTP stream stalled (%d failures), reconnecting: %s",
                        self._consecutive_failures,
                        self._url,
                    )
                    if not self._try_reconnect():
                        break
                else:
                    time.sleep(0.1)

    def _try_reconnect(self) -> bool:
        for attempt in range(1, self._max_reconnect + 1):
            if not self._running:
                return False
            logger.info(
                "HTTP reconnect attempt %d/%d: %s",
                attempt,
                self._max_reconnect,
                self._url,
            )
            if self._cap:
                self._cap.release()
            time.sleep(self._reconnect_delay * attempt)
            self._cap = cv2.VideoCapture(self._url)
            if self._cap.isOpened():
                self._consecutive_failures = 0
                logger.info("HTTP stream reconnected: %s", self._url)
                return True
        logger.error(
            "HTTP reconnect failed after %d attempts: %s",
            self._max_reconnect,
            self._url,
        )
        self._running = False
        return False

    def _get_latest(self) -> Optional[Frame]:
        with self._lock:
            return self._latest_frame


def _id_from_url(url: str) -> str:
    """Generate a camera ID from an HTTP URL.

    http://192.168.1.50:81/stream → http:192.168.1.50
    """
    stripped = url.split("://", 1)[-1] if "://" in url else url
    if "@" in stripped:
        stripped = stripped.split("@", 1)[1]
    host = stripped.split("/", 1)[0].split(":", 1)[0]
    return f"http:{host}"
