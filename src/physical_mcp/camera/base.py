"""Camera abstraction layer — Frame dataclass and CameraSource ABC."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np


@dataclass
class Frame:
    """A single captured frame with metadata."""

    image: np.ndarray  # BGR numpy array from OpenCV
    timestamp: datetime
    source_id: str
    sequence_number: int
    resolution: tuple[int, int]  # (width, height)

    def to_jpeg_bytes(self, quality: int = 85) -> bytes:
        _, buf = cv2.imencode(".jpg", self.image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    def to_base64(self, quality: int = 85) -> str:
        return base64.b64encode(self.to_jpeg_bytes(quality)).decode("utf-8")

    def to_thumbnail(self, max_dim: int = 640, quality: int = 60) -> str:
        """Downscale and encode for API calls — saves tokens/cost."""
        h, w = self.image.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(self.image, (new_w, new_h))
        else:
            resized = self.image
        _, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buf.tobytes()).decode("utf-8")


class CameraSource(ABC):
    """Abstract interface for all camera backends."""

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def grab_frame(self) -> Frame: ...

    @abstractmethod
    def is_open(self) -> bool: ...

    @property
    @abstractmethod
    def source_id(self) -> str: ...
