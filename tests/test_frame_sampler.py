"""Tests for the frame sampler cost-control logic."""

from datetime import datetime

import numpy as np

from physical_mcp.camera.base import Frame
from physical_mcp.perception.change_detector import ChangeDetector, ChangeLevel
from physical_mcp.perception.frame_sampler import FrameSampler


def _make_frame(seq: int = 1, timestamp: datetime | None = None) -> Frame:
    return Frame(
        image=np.random.randint(100, 200, (480, 640, 3), dtype=np.uint8),
        timestamp=timestamp or datetime.now(),
        source_id="test:0",
        sequence_number=seq,
        resolution=(640, 480),
    )


class TestFrameSampler:
    def test_no_rules_never_triggers(self):
        """Without active rules, LLM should NEVER be called."""
        detector = ChangeDetector()
        sampler = FrameSampler(detector, cooldown_seconds=0)
        frame = _make_frame()
        should, result = sampler.should_analyze(frame, has_active_rules=False)
        assert should is False  # Even initial frame — no rules = no LLM

    def test_with_rules_initial_frame_triggers(self):
        """With active rules, initial MAJOR change should trigger."""
        detector = ChangeDetector()
        sampler = FrameSampler(detector, cooldown_seconds=0)
        frame = _make_frame()
        should, result = sampler.should_analyze(frame, has_active_rules=True)
        assert should is True
        assert result.level == ChangeLevel.MAJOR

    def test_no_change_within_heartbeat(self):
        detector = ChangeDetector()
        sampler = FrameSampler(detector, heartbeat_interval=60, cooldown_seconds=0)
        frame = _make_frame()
        sampler.should_analyze(frame, has_active_rules=True)  # Initial
        # Same frame, within heartbeat
        should, result = sampler.should_analyze(frame, has_active_rules=True)
        assert should is False

    def test_cooldown_prevents_rapid_analysis(self):
        detector = ChangeDetector()
        sampler = FrameSampler(detector, cooldown_seconds=5.0)
        frame1 = _make_frame(seq=1)
        sampler.should_analyze(frame1, has_active_rules=True)  # Initial triggers

        # Different frame but within cooldown
        frame2 = Frame(
            image=np.random.randint(0, 50, (480, 640, 3), dtype=np.uint8),
            timestamp=datetime.now(),
            source_id="test:0",
            sequence_number=2,
            resolution=(640, 480),
        )
        should, result = sampler.should_analyze(frame2, has_active_rules=True)
        assert should is False

    def test_minor_change_does_not_trigger(self):
        """MINOR changes should NOT trigger LLM — not worth the cost."""
        detector = ChangeDetector()
        sampler = FrameSampler(detector, cooldown_seconds=0, heartbeat_interval=9999)
        frame1 = _make_frame()
        sampler.should_analyze(frame1, has_active_rules=True)  # Initial

        # Small change (MINOR level)
        frame2_img = frame1.image.copy()
        frame2_img[200:210, 300:310] = 255  # Tiny white square
        frame2 = Frame(
            image=frame2_img,
            timestamp=datetime.now(),
            source_id="test:0",
            sequence_number=2,
            resolution=(640, 480),
        )
        should, result = sampler.should_analyze(frame2, has_active_rules=True)
        # MINOR should not trigger (only MAJOR/MODERATE do)
        if result.level == ChangeLevel.MINOR:
            assert should is False
