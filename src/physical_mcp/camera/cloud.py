"""Cloud camera backend — receives frames pushed via HTTP POST.

Unlike USB/RTSP/HTTP cameras where the server pulls frames, CloudCamera
is designed for wireless cameras that POST JPEG frames to the server.
This is the core of the cloud-hosted architecture where cameras push
frames to a cloud server rather than being polled on a LAN.

Usage:
    Camera hardware POSTs JPEG to ``POST /ingest/{camera_id}``
    → vision_api calls ``camera.receive_frame(jpeg_bytes)``
    → perception loop calls ``camera.grab_frame()`` and gets the frame
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import cv2
import numpy as np

from .base import CameraSource, Frame

logger = logging.getLogger("physical-mcp")


class CloudCameraError(Exception):
    """Raised when a cloud camera encounters an error."""


class CloudCamera(CameraSource):
    """Push-based camera: receives JPEG frames via HTTP POST.

    The ``grab_frame()`` method blocks until a frame is pushed via
    ``receive_frame()``, or returns the last received frame on timeout.
    This allows the existing perception loop to work unchanged — it just
    waits for frames instead of pulling them.
    """

    def __init__(
        self,
        camera_id: str,
        auth_token: str = "",
        name: str = "",
        queue_size: int = 10,
        grab_timeout: float = 30.0,
    ) -> None:
        self._camera_id = camera_id
        self._auth_token = auth_token
        self._name = name or camera_id
        self._queue: asyncio.Queue[Frame] = asyncio.Queue(maxsize=queue_size)
        self._is_open = False
        self._sequence = 0
        self._last_frame: Frame | None = None
        self._grab_timeout = grab_timeout

    async def open(self) -> None:
        """Open the cloud camera (no-op — camera initiates connection)."""
        self._is_open = True
        logger.info(
            "Cloud camera '%s' (%s) opened — waiting for frames",
            self._name,
            self._camera_id,
        )

    async def close(self) -> None:
        """Close the cloud camera."""
        self._is_open = False
        # Drain the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info("Cloud camera '%s' closed", self._name)

    async def grab_frame(self) -> Frame:
        """Wait for the next pushed frame.

        Blocks until a frame arrives via ``receive_frame()``.
        On timeout, returns the last received frame (stale is better
        than error for consumer use). Raises if no frame has ever
        been received.
        """
        try:
            frame = await asyncio.wait_for(
                self._queue.get(), timeout=self._grab_timeout
            )
            self._last_frame = frame
            return frame
        except asyncio.TimeoutError:
            if self._last_frame is not None:
                return self._last_frame
            raise CloudCameraError(
                f"No frames received for cloud camera '{self._camera_id}' "
                f"(waited {self._grab_timeout}s)"
            )

    def is_open(self) -> bool:
        return self._is_open

    @property
    def source_id(self) -> str:
        return self._camera_id

    async def receive_frame(self, jpeg_bytes: bytes) -> Frame:
        """Accept a JPEG frame pushed from the camera hardware.

        Called by the ``POST /ingest/{camera_id}`` endpoint.

        Args:
            jpeg_bytes: Raw JPEG image data.

        Returns:
            The decoded Frame object.

        Raises:
            ValueError: If the JPEG data is invalid or cannot be decoded.
        """
        if not jpeg_bytes:
            raise ValueError("Invalid JPEG data — empty payload")

        image = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Invalid JPEG data — could not decode image")

        self._sequence += 1
        frame = Frame(
            image=image,
            timestamp=datetime.now(),
            source_id=self._camera_id,
            sequence_number=self._sequence,
            resolution=(image.shape[1], image.shape[0]),
        )

        # Drop oldest frame if queue is full (camera pushes faster than analysis)
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        await self._queue.put(frame)
        return frame

    def validate_token(self, token: str) -> bool:
        """Validate a per-camera authentication token.

        If no auth_token is configured, all tokens are accepted.
        """
        if not self._auth_token:
            return True
        return token == self._auth_token
