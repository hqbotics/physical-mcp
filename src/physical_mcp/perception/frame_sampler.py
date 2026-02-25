"""Frame sampling strategy — decides WHEN to send frames for LLM analysis.

This is the primary cost-control mechanism.

Design philosophy:
- Local change detection runs on EVERY frame (free, <5ms)
- LLM is called when there's a meaningful reason to:
  1. User explicitly calls analyze_now (on-demand)
  2. Watch rules exist AND scene change detected (event-driven)
  3. Heartbeat interval (safety net, only if watch rules exist)
- Without watch rules: just captures + detects changes locally. Zero API cost.
"""

from __future__ import annotations

from datetime import datetime

from ..camera.base import Frame
from .change_detector import ChangeDetector, ChangeLevel, ChangeResult


# Longer debounce for subtle changes to avoid noise
_MINOR_DEBOUNCE_MULTIPLIER = 1.5


class FrameSampler:
    """Event-driven sampling — catches brief actions while controlling cost.

    NO watch rules (default):
      - Never auto-triggers LLM. Zero API cost.
      - User can still call analyze_now manually.

    WITH watch rules:
      - MAJOR change -> immediate LLM analysis
      - MODERATE change -> debounce, then analyze (catches quick sips)
      - MINOR change -> longer debounce, then analyze (catches subtle gestures)
      - NONE -> heartbeat only
      - Heartbeat -> periodic check every heartbeat_interval
    """

    def __init__(
        self,
        change_detector: ChangeDetector,
        heartbeat_interval: float = 300.0,
        debounce_seconds: float = 3.0,
        cooldown_seconds: float = 10.0,
    ):
        self._detector = change_detector
        self._heartbeat = heartbeat_interval
        self._debounce = debounce_seconds
        self._cooldown = cooldown_seconds
        self._last_analysis: datetime = datetime.min
        # Pending change flags — fire even if scene calms down
        self._pending_moderate: bool = False
        self._moderate_timestamp: datetime = datetime.min
        self._pending_minor: bool = False
        self._minor_timestamp: datetime = datetime.min

    def should_analyze(
        self, frame: Frame, has_active_rules: bool = False
    ) -> tuple[bool, ChangeResult]:
        """Returns (should_send_to_llm, change_result).

        Key fix: pending debounce fires even when current frame is calm.
        This catches brief actions (quick sip = MODERATE spike → NONE next frame).
        """
        result = self._detector.detect(frame.image)
        now = frame.timestamp
        since_last = (now - self._last_analysis).total_seconds()

        # No active rules = never auto-trigger LLM
        if not has_active_rules:
            return False, result

        # Cooldown: never analyze faster than cooldown_seconds
        if since_last < self._cooldown:
            return False, result

        # ── Pending debounce checks (fire even if current frame is calm) ──
        # This is critical for brief actions: a sip creates a MODERATE spike
        # for 1-2 frames, then drops to NONE. Without this, the debounce
        # check inside the MODERATE block never fires on the NONE frame.
        if self._pending_moderate:
            elapsed = (now - self._moderate_timestamp).total_seconds()
            if elapsed >= self._debounce:
                self._last_analysis = now
                self._pending_moderate = False
                self._pending_minor = False
                return True, result

        if self._pending_minor:
            minor_debounce = self._debounce * _MINOR_DEBOUNCE_MULTIPLIER
            elapsed = (now - self._minor_timestamp).total_seconds()
            if elapsed >= minor_debounce:
                self._last_analysis = now
                self._pending_minor = False
                return True, result

        # ── Level-specific triggers ──

        # MAJOR change: analyze immediately
        if result.level == ChangeLevel.MAJOR:
            self._last_analysis = now
            self._pending_moderate = False
            self._pending_minor = False
            return True, result

        # MODERATE change: start debounce (or upgrade existing minor)
        if result.level == ChangeLevel.MODERATE:
            if not self._pending_moderate:
                self._pending_moderate = True
                self._moderate_timestamp = now
                self._pending_minor = False  # Moderate supersedes minor
            return False, result

        # MINOR change: start longer debounce
        if result.level == ChangeLevel.MINOR:
            if not self._pending_minor and not self._pending_moderate:
                self._pending_minor = True
                self._minor_timestamp = now
            return False, result

        # NONE: no change detected — only heartbeat can trigger
        # Heartbeat: periodic check (only with active rules)
        if since_last >= self._heartbeat:
            self._last_analysis = now
            return True, result

        return False, result
