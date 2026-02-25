"""Tests for the frame sampler cost-control logic."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np

from physical_mcp.camera.base import Frame
from physical_mcp.perception.change_detector import (
    ChangeDetector,
    ChangeLevel,
    ChangeResult,
)
from physical_mcp.perception.frame_sampler import (
    FrameSampler,
    _MINOR_DEBOUNCE_MULTIPLIER,
)


def _make_frame(seq: int = 1, timestamp: datetime | None = None) -> Frame:
    return Frame(
        image=np.random.randint(100, 200, (480, 640, 3), dtype=np.uint8),
        timestamp=timestamp or datetime.now(),
        source_id="test:0",
        sequence_number=seq,
        resolution=(640, 480),
    )


def _make_result(level: ChangeLevel, distance: int = 0) -> ChangeResult:
    """Helper to build a ChangeResult with a given level."""
    return ChangeResult(
        level=level,
        hash_distance=distance,
        pixel_diff_pct=0.0,
        description=f"test-{level.name}",
    )


def _mock_detector(level: ChangeLevel) -> ChangeDetector:
    """Create a detector mock that always returns the given level."""
    detector = MagicMock(spec=ChangeDetector)
    detector.detect.return_value = _make_result(level)
    return detector


class TestFrameSampler:
    """Core sampler tests — no rules, initial trigger, cooldown."""

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


class TestMinorDebounce:
    """MINOR changes now trigger after a longer debounce (1.5x)."""

    def test_minor_sets_pending_not_immediate(self):
        """MINOR change should NOT trigger immediately — starts debounce."""
        detector = _mock_detector(ChangeLevel.MINOR)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=0.3,
            heartbeat_interval=9999,
        )
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        sampler._last_analysis = t0

        frame = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        should, _ = sampler.should_analyze(frame, has_active_rules=True)
        assert should is False
        assert sampler._pending_minor is True

    def test_minor_fires_after_debounce(self):
        """MINOR triggers after minor debounce (debounce * 1.5) elapses."""
        debounce = 0.3
        minor_debounce = debounce * _MINOR_DEBOUNCE_MULTIPLIER
        detector = _mock_detector(ChangeLevel.MINOR)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=debounce,
            heartbeat_interval=9999,
        )
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        sampler._last_analysis = t0

        # Frame 1: MINOR — sets pending
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        should1, _ = sampler.should_analyze(f1, has_active_rules=True)
        assert should1 is False

        # Frame 2: After minor debounce — should fire
        f2 = _make_frame(
            seq=2, timestamp=t0 + timedelta(seconds=1 + minor_debounce + 0.01)
        )
        should2, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should2 is True
        assert sampler._pending_minor is False

    def test_minor_does_not_fire_before_debounce(self):
        """MINOR should NOT fire if debounce hasn't elapsed."""
        debounce = 0.3
        detector = _mock_detector(ChangeLevel.MINOR)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=debounce,
            heartbeat_interval=9999,
        )
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        sampler._last_analysis = t0

        # Frame 1: MINOR — sets pending
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        sampler.should_analyze(f1, has_active_rules=True)

        # Frame 2: Just before minor debounce
        minor_debounce = debounce * _MINOR_DEBOUNCE_MULTIPLIER
        f2 = _make_frame(
            seq=2, timestamp=t0 + timedelta(seconds=1 + minor_debounce - 0.05)
        )
        should2, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should2 is False
        assert sampler._pending_minor is True  # Still pending


class TestPendingDebounce:
    """Core bug fix: pending changes fire even when the scene calms down."""

    def test_pending_moderate_fires_on_none_frame(self):
        """Brief MODERATE spike → NONE should still trigger after debounce.

        Scenario: Quick sip creates MODERATE for 1-2 frames, then scene
        returns to NONE. The pending moderate must fire on the NONE frame.
        """
        debounce = 0.3
        t0 = datetime(2026, 1, 1, 12, 0, 0)

        detector = _mock_detector(ChangeLevel.MODERATE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=debounce,
            heartbeat_interval=9999,
        )
        sampler._last_analysis = t0

        # Frame 1: MODERATE — sets pending
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        should1, _ = sampler.should_analyze(f1, has_active_rules=True)
        assert should1 is False
        assert sampler._pending_moderate is True

        # Frame 2: Scene calmed to NONE, but debounce elapsed → fires
        detector.detect.return_value = _make_result(ChangeLevel.NONE)
        f2 = _make_frame(seq=2, timestamp=t0 + timedelta(seconds=1 + debounce + 0.01))
        should2, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should2 is True
        assert sampler._pending_moderate is False

    def test_pending_minor_fires_on_none_frame(self):
        """MINOR pending should also fire when scene returns to NONE."""
        debounce = 0.3
        minor_debounce = debounce * _MINOR_DEBOUNCE_MULTIPLIER
        t0 = datetime(2026, 1, 1, 12, 0, 0)

        detector = _mock_detector(ChangeLevel.MINOR)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=debounce,
            heartbeat_interval=9999,
        )
        sampler._last_analysis = t0

        # Frame 1: MINOR — sets pending
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        sampler.should_analyze(f1, has_active_rules=True)
        assert sampler._pending_minor is True

        # Frame 2: NONE but minor debounce elapsed → fires
        detector.detect.return_value = _make_result(ChangeLevel.NONE)
        f2 = _make_frame(
            seq=2, timestamp=t0 + timedelta(seconds=1 + minor_debounce + 0.01)
        )
        should2, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should2 is True
        assert sampler._pending_minor is False

    def test_pending_moderate_not_lost_across_none_frames(self):
        """Multiple NONE frames shouldn't lose the pending moderate."""
        debounce = 0.5
        t0 = datetime(2026, 1, 1, 12, 0, 0)

        detector = _mock_detector(ChangeLevel.MODERATE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=debounce,
            heartbeat_interval=9999,
        )
        sampler._last_analysis = t0

        # Frame 1: MODERATE
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        sampler.should_analyze(f1, has_active_rules=True)

        # Frames 2-4: NONE, but debounce not yet elapsed
        detector.detect.return_value = _make_result(ChangeLevel.NONE)
        for i in range(2, 5):
            fi = _make_frame(seq=i, timestamp=t0 + timedelta(seconds=1 + (i - 1) * 0.1))
            should, _ = sampler.should_analyze(fi, has_active_rules=True)
            assert should is False
            assert sampler._pending_moderate is True  # Still pending!

        # Frame 5: After debounce → fires
        f5 = _make_frame(seq=5, timestamp=t0 + timedelta(seconds=1 + debounce + 0.01))
        should5, _ = sampler.should_analyze(f5, has_active_rules=True)
        assert should5 is True


class TestFlagInteractions:
    """MAJOR clears flags, MODERATE supersedes MINOR."""

    def test_major_clears_pending_moderate(self):
        """MAJOR immediately triggers and clears pending moderate."""
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.MODERATE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=0.3,
            heartbeat_interval=9999,
        )
        sampler._last_analysis = t0

        # Set up pending moderate
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        sampler.should_analyze(f1, has_active_rules=True)
        assert sampler._pending_moderate is True

        # MAJOR arrives before debounce
        detector.detect.return_value = _make_result(ChangeLevel.MAJOR, distance=30)
        f2 = _make_frame(seq=2, timestamp=t0 + timedelta(seconds=1.1))
        should, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should is True
        assert sampler._pending_moderate is False
        assert sampler._pending_minor is False

    def test_major_clears_pending_minor(self):
        """MAJOR immediately triggers and clears pending minor."""
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.MINOR)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=0.3,
            heartbeat_interval=9999,
        )
        sampler._last_analysis = t0

        # Set up pending minor
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        sampler.should_analyze(f1, has_active_rules=True)
        assert sampler._pending_minor is True

        # MAJOR arrives
        detector.detect.return_value = _make_result(ChangeLevel.MAJOR, distance=30)
        f2 = _make_frame(seq=2, timestamp=t0 + timedelta(seconds=1.1))
        should, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should is True
        assert sampler._pending_minor is False

    def test_moderate_supersedes_minor(self):
        """MODERATE should clear pending MINOR (more significant change)."""
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.MINOR)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=0.3,
            heartbeat_interval=9999,
        )
        sampler._last_analysis = t0

        # Frame 1: MINOR
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        sampler.should_analyze(f1, has_active_rules=True)
        assert sampler._pending_minor is True
        assert sampler._pending_moderate is False

        # Frame 2: MODERATE — supersedes minor
        detector.detect.return_value = _make_result(ChangeLevel.MODERATE, distance=8)
        f2 = _make_frame(seq=2, timestamp=t0 + timedelta(seconds=1.1))
        sampler.should_analyze(f2, has_active_rules=True)
        assert sampler._pending_moderate is True
        assert sampler._pending_minor is False

    def test_minor_does_not_override_pending_moderate(self):
        """MINOR should NOT replace a pending MODERATE (less significant)."""
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.MODERATE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=0.3,
            heartbeat_interval=9999,
        )
        sampler._last_analysis = t0

        # Frame 1: MODERATE
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=1))
        sampler.should_analyze(f1, has_active_rules=True)
        assert sampler._pending_moderate is True

        # Frame 2: MINOR — should NOT set pending_minor while moderate is pending
        detector.detect.return_value = _make_result(ChangeLevel.MINOR, distance=4)
        f2 = _make_frame(seq=2, timestamp=t0 + timedelta(seconds=1.1))
        sampler.should_analyze(f2, has_active_rules=True)
        assert sampler._pending_moderate is True
        assert sampler._pending_minor is False  # Not set because moderate is pending


class TestHeartbeat:
    """Heartbeat periodic analysis tests."""

    def test_heartbeat_fires_at_interval(self):
        """Heartbeat triggers after interval with no changes."""
        heartbeat = 5.0
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.NONE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            debounce_seconds=0.3,
            heartbeat_interval=heartbeat,
        )
        sampler._last_analysis = t0

        # Just before heartbeat — should NOT fire
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=4.9))
        should1, _ = sampler.should_analyze(f1, has_active_rules=True)
        assert should1 is False

        # After heartbeat — should fire
        f2 = _make_frame(seq=2, timestamp=t0 + timedelta(seconds=5.1))
        should2, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should2 is True

    def test_heartbeat_does_not_fire_without_rules(self):
        """Heartbeat should NOT trigger without active rules."""
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.NONE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=0,
            heartbeat_interval=5.0,
        )
        sampler._last_analysis = t0

        frame = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=10))
        should, _ = sampler.should_analyze(frame, has_active_rules=False)
        assert should is False


class TestCooldownInteractions:
    """Cooldown blocks all trigger types including pending debounce."""

    def test_cooldown_blocks_pending_moderate(self):
        """Pending moderate should not fire during cooldown."""
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.MODERATE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=2.0,
            debounce_seconds=0.3,
            heartbeat_interval=9999,
        )
        # Last analysis was very recent
        sampler._last_analysis = t0

        # MODERATE at t0+0.5 — within cooldown
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=0.5))
        should1, _ = sampler.should_analyze(f1, has_active_rules=True)
        assert should1 is False

        # t0+1.0 — debounce elapsed but still within cooldown
        detector.detect.return_value = _make_result(ChangeLevel.NONE)
        f2 = _make_frame(seq=2, timestamp=t0 + timedelta(seconds=1.0))
        should2, _ = sampler.should_analyze(f2, has_active_rules=True)
        assert should2 is False

    def test_cooldown_blocks_heartbeat(self):
        """Heartbeat should not fire during cooldown."""
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        detector = _mock_detector(ChangeLevel.NONE)
        sampler = FrameSampler(
            detector,
            cooldown_seconds=10.0,
            heartbeat_interval=5.0,
        )
        sampler._last_analysis = t0

        # At t0+6 — heartbeat (5s) elapsed but cooldown (10s) hasn't
        f1 = _make_frame(seq=1, timestamp=t0 + timedelta(seconds=6))
        should, _ = sampler.should_analyze(f1, has_active_rules=True)
        assert should is False
