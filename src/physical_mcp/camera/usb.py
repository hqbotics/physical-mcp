"""USB camera implementation using OpenCV with background capture thread."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Optional

import cv2

from .base import CameraSource, Frame


class USBCamera(CameraSource):
    """OpenCV-based USB camera with background capture thread.

    OpenCV's VideoCapture.read() is blocking, so we run a dedicated
    capture thread that continuously grabs frames into a latest-frame
    slot. The async grab_frame() reads from this slot without blocking
    the asyncio event loop.
    """

    def __init__(self, device_index: int = 0, width: int = 1280, height: int = 720):
        self._device_index = device_index
        self._width = width
        self._height = height
        self._cap: Optional[cv2.VideoCapture] = None
        self._latest_frame: Optional[Frame] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sequence = 0

    async def open(self) -> None:
        self._cap = cv2.VideoCapture(self._device_index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera at index {self._device_index}")
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        # Wait for first frame
        for _ in range(50):  # 5 seconds max
            await asyncio.sleep(0.1)
            with self._lock:
                if self._latest_frame is not None:
                    return
        raise RuntimeError("Camera opened but no frames received within 5 seconds")

    def _capture_loop(self) -> None:
        while self._running and self._cap is not None:
            ret, img = self._cap.read()
            if ret:
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

    async def grab_frame(self) -> Frame:
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(None, self._get_latest)
        if frame is None:
            raise RuntimeError("No frame available")
        return frame

    def _get_latest(self) -> Optional[Frame]:
        with self._lock:
            return self._latest_frame

    async def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._cap:
            self._cap.release()
            self._cap = None

    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def source_id(self) -> str:
        return f"usb:{self._device_index}"

    @staticmethod
    def enumerate_cameras(max_index: int = 5) -> list[dict]:
        """Probe available camera indices. Useful for setup."""
        cameras = []
        for i in range(max_index):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cameras.append({"index": i, "width": w, "height": h})
                cap.release()
        return cameras
