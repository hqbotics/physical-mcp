"""RTSP/HTTP camera implementation using OpenCV with auto-reconnect.

Supports IP cameras that expose RTSP or HTTP MJPEG streams.
Uses the same background-thread pattern as USBCamera to avoid
blocking the asyncio event loop.

Examples:
    - RTSP: rtsp://admin:password@192.168.1.100:554/h264Preview_01_main
    - HTTP MJPEG: http://192.168.1.100:8080/video
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime

import cv2

from ..exceptions import CameraConnectionError, CameraTimeoutError
from .base import CameraSource, Frame

logger = logging.getLogger("physical-mcp")

# Reconnection constants
_INITIAL_RETRY_DELAY = 2.0
_MAX_RETRY_DELAY = 30.0
_CONSECUTIVE_FAILURES_BEFORE_LOG = 3


class RTSPCamera(CameraSource):
    """RTSP/HTTP stream camera with background capture and auto-reconnect.

    OpenCV's VideoCapture handles RTSP decoding via ffmpeg/gstreamer.
    A background thread continuously grabs frames, and auto-reconnects
    on stream drops with exponential backoff.
    """

    def __init__(
        self,
        url: str,
        camera_id: str = "rtsp:0",
        width: int = 1280,
        height: int = 720,
    ):
        if not url:
            raise CameraConnectionError("RTSP/HTTP camera URL is required")
        self._url = url
        self._camera_id = camera_id
        self._width = width
        self._height = height
        self._cap: cv2.VideoCapture | None = None
        self._latest_frame: Frame | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._sequence = 0
        self._consecutive_failures = 0
        self._use_ffmpeg_subprocess = False

    async def open(self) -> None:
        self._cap = self._create_capture()
        if not self._use_ffmpeg_subprocess and not self._cap.isOpened():
            raise CameraConnectionError(f"Cannot open stream: {self._safe_url}")
        # For ffmpeg subprocess mode, verify we can grab at least one frame.
        # Retry a few times — the camera may briefly reject connections after
        # the OpenCV probes above left stale RTSP sessions.
        if self._use_ffmpeg_subprocess:
            test_frame = None
            for attempt in range(3):
                test_frame = self._ffmpeg_grab_frame()
                if test_frame is not None:
                    break
                logger.info(
                    f"[{self._camera_id}] ffmpeg test grab attempt "
                    f"{attempt + 1}/3 failed, retrying in 2s..."
                )
                await asyncio.sleep(2)
            if test_frame is None:
                raise CameraConnectionError(
                    f"Cannot open stream via ffmpeg: {self._safe_url}"
                )
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        # Wait for first frame (20s — network cameras can be slow to start)
        for _ in range(200):
            await asyncio.sleep(0.1)
            with self._lock:
                if self._latest_frame is not None:
                    return
        raise CameraTimeoutError(
            f"Stream opened but no frames received within 20 seconds: {self._safe_url}"
        )

    def _create_capture(self) -> cv2.VideoCapture:
        """Create a new VideoCapture with optimized settings for network streams.

        Tries TCP transport first (more reliable on most networks), then falls
        back to UDP if the camera rejects TCP (e.g. "Nonmatching transport").
        """
        import os

        for transport in ("tcp", "udp"):
            # timeout is in microseconds — 5s per attempt instead of 30s default
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                f"rtsp_transport;{transport}|stimeout;5000000|timeout;5000000"
            )
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            if cap.isOpened():
                logger.info(f"[{self._camera_id}] Connected via {transport.upper()}")
                return cap
            cap.release()
            logger.info(
                f"[{self._camera_id}] {transport.upper()} transport failed, "
                f"{'trying UDP...' if transport == 'tcp' else 'trying ffmpeg subprocess...'}"
            )

        # Both TCP and UDP failed with OpenCV — fall back to ffmpeg subprocess.
        # This is more reliable because OpenCV's built-in ffmpeg sometimes
        # ignores OPENCV_FFMPEG_CAPTURE_OPTIONS.
        logger.info(f"[{self._camera_id}] OpenCV RTSP failed, using ffmpeg subprocess")
        self._use_ffmpeg_subprocess = True
        # Return a dummy capture that won't be used — _capture_loop checks
        # _use_ffmpeg_subprocess and calls _ffmpeg_grab_frame instead.
        return _DummyCapture()

    def _ffmpeg_grab_frame(self) -> "cv2.typing.MatLike | None":
        """Grab a single frame using ffmpeg subprocess (UDP transport).

        More reliable than OpenCV's built-in RTSP for cameras that reject
        TCP transport (like Yoosee).  Returns a decoded numpy image or None.
        """
        import subprocess

        import numpy as np

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-rtsp_transport",
                    "udp",
                    "-i",
                    self._url,
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "-q:v",
                    "5",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0 or not result.stdout:
                return None
            jpg_data = np.frombuffer(result.stdout, dtype=np.uint8)
            img = cv2.imdecode(jpg_data, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            logger.debug(f"[{self._camera_id}] ffmpeg grab failed: {e}")
            return None

    def _capture_loop(self) -> None:
        """Background thread: grab frames, auto-reconnect on failure."""
        retry_delay = _INITIAL_RETRY_DELAY

        while self._running:
            # ffmpeg subprocess mode — grab one frame at a time
            if self._use_ffmpeg_subprocess:
                img = self._ffmpeg_grab_frame()
                if img is not None:
                    self._consecutive_failures = 0
                    retry_delay = _INITIAL_RETRY_DELAY
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
                    time.sleep(retry_delay)
                # Pace to ~1 fps for subprocess mode (each call is ~0.5-1s)
                time.sleep(0.5)
                continue

            if self._cap is None or not self._cap.isOpened():
                self._reconnect(retry_delay)
                retry_delay = min(retry_delay * 2, _MAX_RETRY_DELAY)
                continue

            ret, img = self._cap.read()
            if not ret:
                self._consecutive_failures += 1
                if self._consecutive_failures >= _CONSECUTIVE_FAILURES_BEFORE_LOG:
                    logger.warning(
                        f"[{self._camera_id}] Stream read failed "
                        f"({self._consecutive_failures} consecutive). Reconnecting..."
                    )
                self._release_capture()
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, _MAX_RETRY_DELAY)
                continue

            # Success — reset backoff
            self._consecutive_failures = 0
            retry_delay = _INITIAL_RETRY_DELAY
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

    def _reconnect(self, delay: float) -> None:
        """Attempt to reconnect to the stream."""
        self._release_capture()
        if not self._running:
            return
        logger.info(
            f"[{self._camera_id}] Reconnecting to {self._safe_url} "
            f"(backoff {delay:.1f}s)..."
        )
        time.sleep(delay)
        if not self._running:
            return
        try:
            self._cap = self._create_capture()
            if self._cap.isOpened():
                logger.info(f"[{self._camera_id}] Reconnected successfully")
            else:
                self._release_capture()
        except Exception as e:
            logger.debug(f"[{self._camera_id}] Reconnect failed: {e}")
            self._release_capture()

    def _release_capture(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    async def grab_frame(self) -> Frame:
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(None, self._get_latest)
        if frame is None:
            raise CameraTimeoutError(f"No frame available from {self._safe_url}")
        return frame

    def _get_latest(self) -> Frame | None:
        with self._lock:
            return self._latest_frame

    async def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self._release_capture()

    def is_open(self) -> bool:
        if self._use_ffmpeg_subprocess:
            return self._running
        return self._running and self._cap is not None and self._cap.isOpened()

    @property
    def source_id(self) -> str:
        return self._camera_id

    @property
    def _safe_url(self) -> str:
        """URL with password masked for logging."""
        if "@" in self._url:
            # rtsp://user:pass@host → rtsp://user:***@host
            proto_rest = self._url.split("://", 1)
            if len(proto_rest) == 2:
                proto, rest = proto_rest
                if "@" in rest:
                    creds, host = rest.rsplit("@", 1)
                    user = creds.split(":", 1)[0]
                    return f"{proto}://{user}:***@{host}"
        return self._url


class _DummyCapture:
    """Placeholder for when ffmpeg subprocess mode is used instead of OpenCV."""

    def isOpened(self) -> bool:  # noqa: N802
        return True

    def release(self) -> None:
        pass

    def read(self) -> tuple[bool, None]:
        return False, None

    def set(self, prop: int, val: float) -> bool:
        return True
