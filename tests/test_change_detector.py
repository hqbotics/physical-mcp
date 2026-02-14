"""Tests for the perceptual hash change detector."""

import numpy as np
import pytest

from physical_mcp.perception.change_detector import ChangeDetector, ChangeLevel


class TestChangeDetector:
    def test_initial_frame_is_major(self):
        detector = ChangeDetector()
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        result = detector.detect(frame)
        assert result.level == ChangeLevel.MAJOR

    def test_identical_frames_no_change(self):
        detector = ChangeDetector()
        frame = np.random.randint(100, 200, (480, 640, 3), dtype=np.uint8)
        detector.detect(frame)
        result = detector.detect(frame.copy())
        assert result.level == ChangeLevel.NONE
        assert result.hash_distance == 0

    def test_completely_different_frames_major(self):
        detector = ChangeDetector()
        frame_a = np.random.randint(0, 50, (480, 640, 3), dtype=np.uint8)
        detector.detect(frame_a)
        frame_b = np.random.randint(200, 255, (480, 640, 3), dtype=np.uint8)
        result = detector.detect(frame_b)
        assert result.level == ChangeLevel.MAJOR

    def test_small_region_change(self):
        detector = ChangeDetector()
        frame = np.random.randint(100, 200, (480, 640, 3), dtype=np.uint8)
        detector.detect(frame)
        modified = frame.copy()
        modified[200:230, 300:330] = 255
        result = detector.detect(modified)
        assert result.level in (ChangeLevel.MINOR, ChangeLevel.MODERATE)

    def test_reset(self):
        detector = ChangeDetector()
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        detector.detect(frame)
        detector.reset()
        result = detector.detect(frame)
        assert result.level == ChangeLevel.MAJOR  # Treated as initial after reset
