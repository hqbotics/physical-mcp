"""RTSP/IP camera implementation using OpenCV with background capture thread.

Supports any RTSP stream URL, including:
- Reolink: rtsp://admin:password@192.168.1.100:554/h264Preview_01_main
- TP-Link Tapo: rtsp://user:pass@192.168.1.100:554/stream1
- Hikvision: rtsp://admin:pass@192.168.1.100:554/Streaming/Channels/101
- Generic: rtsp://host:port/path
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

# OpenCV RTSP transport preference: TCP is more reliable than UDP for most cameras
_RTSP_ENV = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
_RTSP_TCP = "rtsp_transport;tcp"


class RTSPCamera(CameraSource):
    """RTSP/IP camera with background capture thread and auto-reconnect.

    Uses the same pattern as USBCamera: a background thread continuously
    grabs frames into a latest-frame slot, so async grab_frame() never
    blocks the event loop.

    Adds network-resilience features:
    - Auto-reconnect on stream loss (up to ``max_reconnect_attempts``)
    - Configurable reconnect delay with backoff
    - TCP transport by default (more reliable than UDP over WiFi)
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
        tcp_transport: bool = True,
    ):
        if not url:
            raise ValueError("RTSP URL is required")
        self._url = url
        self._camera_id = camera_id or _id_from_url(url)
        self._width = width
        self._height = height
        self._max_reconnect = max_reconnect_attempts
        self._reconnect_delay = reconnect_delay
        self._tcp_transport = tcp_transport

        self._cap: Optional[cv2.VideoCapture] = None
        self._latest_frame: Optional[Frame] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sequence = 0
        self._consecutive_failures = 0

    # ── CameraSource interface ──────────────────────────────────

    async def open(self) -> None:
        self._cap = self._create_capture()
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open RTSP stream: {self._safe_url}")
        logger.info("RTSP stream opened: %s", self._safe_url)

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        # Wait for first frame (network streams may be slower than USB)
        for _ in range(100):  # 10 seconds max
            await asyncio.sleep(0.1)
            with self._lock:
                if self._latest_frame is not None:
                    return
        raise RuntimeError(
            f"RTSP stream opened but no frames received within 10s: {self._safe_url}"
        )

    async def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("RTSP stream closed: %s", self._safe_url)

    async def grab_frame(self) -> Frame:
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(None, self._get_latest)
        if frame is None:
            raise RuntimeError(f"No frame available from RTSP: {self._safe_url}")
        return frame

    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened() and self._running

    @property
    def source_id(self) -> str:
        return self._camera_id

    # ── Internal ────────────────────────────────────────────────

    def _create_capture(self) -> cv2.VideoCapture:
        """Create an OpenCV VideoCapture for the RTSP URL."""
        # Force TCP transport for reliability over WiFi
        if self._tcp_transport:
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize latency
        else:
            cap = cv2.VideoCapture(self._url)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        return cap

    def _capture_loop(self) -> None:
        """Background thread: grab frames, auto-reconnect on failure."""
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                if not self._try_reconnect():
                    break
                continue

            ret, img = self._cap.read()
            if ret:
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
                if self._consecutive_failures > 30:  # ~30 consecutive read failures
                    logger.warning(
                        "RTSP stream stalled (%d failures), reconnecting: %s",
                        self._consecutive_failures,
                        self._safe_url,
                    )
                    if not self._try_reconnect():
                        break
                else:
                    time.sleep(0.1)  # Brief pause before retry

    def _try_reconnect(self) -> bool:
        """Attempt to reconnect to the RTSP stream. Returns True on success."""
        for attempt in range(1, self._max_reconnect + 1):
            if not self._running:
                return False
            logger.info(
                "RTSP reconnect attempt %d/%d: %s",
                attempt,
                self._max_reconnect,
                self._safe_url,
            )
            if self._cap:
                self._cap.release()
            time.sleep(self._reconnect_delay * attempt)  # Linear backoff
            self._cap = self._create_capture()
            if self._cap.isOpened():
                self._consecutive_failures = 0
                logger.info("RTSP reconnected: %s", self._safe_url)
                return True
        logger.error(
            "RTSP reconnect failed after %d attempts: %s",
            self._max_reconnect,
            self._safe_url,
        )
        self._running = False
        return False

    def _get_latest(self) -> Optional[Frame]:
        with self._lock:
            return self._latest_frame

    @property
    def _safe_url(self) -> str:
        """URL with password masked for logging."""
        return _mask_credentials(self._url)


def _id_from_url(url: str) -> str:
    """Generate a camera ID from an RTSP URL.

    rtsp://admin:pass@192.168.1.100:554/stream → rtsp:192.168.1.100
    """
    # Strip scheme
    stripped = url.split("://", 1)[-1] if "://" in url else url
    # Strip credentials (user:pass@)
    if "@" in stripped:
        stripped = stripped.split("@", 1)[1]
    # Take host part only
    host = stripped.split("/", 1)[0].split(":", 1)[0]
    return f"rtsp:{host}"


def _mask_credentials(url: str) -> str:
    """Mask password in RTSP URL for safe logging.

    rtsp://admin:secret@host → rtsp://admin:***@host
    """
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    creds, host_path = rest.split("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host_path}"
    return url
