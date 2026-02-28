"""Cloud camera — receives pushed frames via HTTP POST.

Unlike USB/RTSP cameras which pull frames from a device or stream,
CloudCamera accepts JPEG frames pushed by a remote relay agent.
The relay (e.g. LuckFox Pico inside a WOSEE camera) captures RTSP
locally and POSTs compressed JPEGs to the cloud server.

No background capture thread is needed — frames arrive via HTTP.
The existing FrameBuffer + perception loop work unchanged because
they poll grab_frame() which returns the latest pushed frame.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import cv2
import numpy as np

from ..exceptions import CameraTimeoutError
from .base import CameraSource, Frame

logger = logging.getLogger("physical-mcp")


class CloudCamera(CameraSource):
    """Camera that receives frames pushed from a remote relay agent.

    Usage:
        camera = CloudCamera(camera_id="cloud:living-room")
        await camera.open()

        # Called by POST /push/frame/{camera_id} endpoint:
        camera.push_frame(jpeg_bytes)

        # Called by perception loop (same as USB/RTSP cameras):
        frame = await camera.grab_frame()
    """

    def __init__(self, camera_id: str = "cloud:0", auth_token: str = ""):
        self._camera_id = camera_id
        self._auth_token = auth_token  # Per-camera token for relay auth
        self._latest_frame: Frame | None = None
        self._lock = asyncio.Lock()
        self._opened = False
        self._sequence = 0
        self._last_push_time: float = 0.0
        self._total_pushed: int = 0
        self._new_frame_event = asyncio.Event()

    async def open(self) -> None:
        """Mark the cloud camera as ready to receive frames."""
        self._opened = True
        logger.info(f"[{self._camera_id}] Cloud camera opened (waiting for frames)")

    async def close(self) -> None:
        """Close the cloud camera."""
        self._opened = False
        self._latest_frame = None
        logger.info(f"[{self._camera_id}] Cloud camera closed")

    def is_open(self) -> bool:
        return self._opened

    @property
    def source_id(self) -> str:
        return self._camera_id

    def push_frame(self, jpeg_bytes: bytes) -> Frame:
        """Decode JPEG bytes and store as the latest frame.

        Called synchronously from the HTTP endpoint handler.
        Returns the decoded Frame for immediate use.

        Raises:
            ValueError: If the JPEG data is invalid or cannot be decoded.
        """
        if not self._opened:
            raise ValueError(f"Cloud camera {self._camera_id} is not open")

        # Decode JPEG bytes → numpy array
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Invalid JPEG data — could not decode frame")

        self._sequence += 1
        self._total_pushed += 1
        self._last_push_time = time.monotonic()

        frame = Frame(
            image=image,
            timestamp=datetime.now(),
            source_id=self._camera_id,
            sequence_number=self._sequence,
            resolution=(image.shape[1], image.shape[0]),
        )

        # Store frame (sync — called from async context via run_in_executor
        # or directly in the aiohttp handler which is async-safe for simple
        # attribute assignments)
        self._latest_frame = frame

        # Signal anyone waiting for a new frame.
        # Use set() only — waiters clear the event themselves via wait_for_frame.
        self._new_frame_event.set()

        return frame

    async def push_frame_async(self, jpeg_bytes: bytes) -> Frame:
        """Async wrapper around push_frame for use in async handlers."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.push_frame, jpeg_bytes)

    async def grab_frame(self) -> Frame:
        """Return the latest pushed frame.

        Called by the perception loop, just like USB/RTSP cameras.
        """
        if self._latest_frame is None:
            raise CameraTimeoutError(
                f"No frame available from cloud camera {self._camera_id}"
            )
        return self._latest_frame

    async def wait_for_frame(self, timeout: float = 30.0) -> Frame | None:
        """Wait for the next pushed frame, or return latest after timeout."""
        try:
            await asyncio.wait_for(self._new_frame_event.wait(), timeout)
            self._new_frame_event.clear()  # Reset for next wait
        except asyncio.TimeoutError:
            pass
        return self._latest_frame

    def verify_token(self, token: str) -> bool:
        """Check if the provided token matches this camera's auth token."""
        if not self._auth_token:
            return True  # No token configured — allow any push
        return token == self._auth_token

    @property
    def stats(self) -> dict:
        """Return push statistics for monitoring."""
        return {
            "camera_id": self._camera_id,
            "total_pushed": self._total_pushed,
            "last_push_age_seconds": (
                round(time.monotonic() - self._last_push_time, 1)
                if self._last_push_time > 0
                else None
            ),
            "has_frame": self._latest_frame is not None,
            "sequence": self._sequence,
        }
