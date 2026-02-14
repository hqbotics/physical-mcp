"""Lightweight change detection using perceptual hashing + pixel diff."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import cv2
import imagehash
import numpy as np
from PIL import Image


class ChangeLevel(Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"


@dataclass
class ChangeResult:
    level: ChangeLevel
    hash_distance: int
    pixel_diff_pct: float
    description: str


class ChangeDetector:
    """Perceptual hash + pixel diff change detection.

    No ML models — runs in <5ms per comparison on any hardware.
    """

    def __init__(
        self,
        minor_threshold: int = 5,
        moderate_threshold: int = 12,
        major_threshold: int = 25,
    ):
        self._minor = minor_threshold
        self._moderate = moderate_threshold
        self._major = major_threshold
        self._prev_hash = None
        self._prev_gray = None

    def detect(self, frame_bgr: np.ndarray) -> ChangeResult:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, 64))
        pil_img = Image.fromarray(small)
        current_hash = imagehash.phash(pil_img)

        if self._prev_hash is None:
            self._prev_hash = current_hash
            self._prev_gray = gray
            return ChangeResult(
                level=ChangeLevel.MAJOR,
                hash_distance=64,
                pixel_diff_pct=1.0,
                description="Initial frame",
            )

        distance = current_hash - self._prev_hash

        if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            diff = cv2.absdiff(self._prev_gray, gray)
            pixel_diff_pct = float(np.count_nonzero(diff > 25) / diff.size)
        else:
            pixel_diff_pct = 1.0

        self._prev_hash = current_hash
        self._prev_gray = gray

        if distance >= self._major:
            level = ChangeLevel.MAJOR
        elif distance >= self._moderate:
            level = ChangeLevel.MODERATE
        elif distance >= self._minor or pixel_diff_pct > 0.05:
            level = ChangeLevel.MINOR
        else:
            level = ChangeLevel.NONE

        return ChangeResult(
            level=level,
            hash_distance=distance,
            pixel_diff_pct=pixel_diff_pct,
            description=f"Hash distance: {distance}, pixel diff: {pixel_diff_pct:.2%}",
        )

    def reset(self) -> None:
        self._prev_hash = None
        self._prev_gray = None
