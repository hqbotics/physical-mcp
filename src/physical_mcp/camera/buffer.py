"""Frame ring buffer for recent frame history."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime

from .base import Frame


class FrameBuffer:
    """Fixed-size ring buffer for recent frames with time-based queries."""

    def __init__(self, max_frames: int = 300):
        self._buffer: deque[Frame] = deque(maxlen=max_frames)
        self._lock = asyncio.Lock()
        self._new_frame_event = asyncio.Event()

    async def push(self, frame: Frame) -> None:
        async with self._lock:
            self._buffer.append(frame)
        # Wake up anyone waiting for a new frame (MJPEG stream, SSE, etc.)
        self._new_frame_event.set()
        self._new_frame_event.clear()

    async def wait_for_frame(self, timeout: float = 5.0) -> Frame | None:
        """Wait for the next new frame, or return latest after timeout."""
        try:
            await asyncio.wait_for(self._new_frame_event.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        return await self.latest()

    async def latest(self) -> Frame | None:
        async with self._lock:
            return self._buffer[-1] if self._buffer else None

    async def get_frames_since(self, since: datetime) -> list[Frame]:
        async with self._lock:
            return [f for f in self._buffer if f.timestamp >= since]

    async def get_sampled(self, count: int) -> list[Frame]:
        """Return `count` evenly-spaced frames from the buffer."""
        async with self._lock:
            if len(self._buffer) <= count:
                return list(self._buffer)
            step = len(self._buffer) / count
            return [self._buffer[int(i * step)] for i in range(count)]

    async def size(self) -> int:
        async with self._lock:
            return len(self._buffer)

    async def clear(self) -> None:
        async with self._lock:
            self._buffer.clear()
