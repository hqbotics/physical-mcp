"""Frame sampling strategy — decides WHEN to send frames for LLM analysis.

This is the primary cost-control mechanism.

Design philosophy (how ChatGPT/Doubao do it):
- Local change detection runs on EVERY frame (free, <5ms)
- LLM is called ONLY when there's a significant reason to
- Background auto-analysis is OFF by default
- LLM calls happen when:
  1. User explicitly calls analyze_now (on-demand)
  2. Watch rules exist AND a MAJOR scene change is detected (event-driven)
  3. Heartbeat interval (default 5 min, only if watch rules exist)
- Without watch rules: the system just captures + detects changes locally. Zero API cost.
"""

from __future__ import annotations

from datetime import datetime

from ..camera.base import Frame
from .change_detector import ChangeDetector, ChangeLevel, ChangeResult


class FrameSampler:
    """Smart event-driven sampling — minimizes LLM calls.

    NO watch rules (default):
      - Never auto-triggers LLM. Zero API cost.
      - User can still call analyze_now manually.
      - Change detection runs locally for the change log.

    WITH watch rules:
      - MAJOR change -> immediate LLM analysis + rule evaluation
      - MODERATE change -> debounce, then analyze if scene stabilizes
      - MINOR/NONE -> no LLM call (not worth the cost)
      - Heartbeat -> analyze every heartbeat_interval (default 5 min)

    Cost estimates:
      Static room, no rules = 0 API calls/hour
      Static room, with rules = ~12 calls/hour (heartbeat only)
      Active room, with rules = ~20-40 calls/hour
    """

    def __init__(
        self,
        change_detector: ChangeDetector,
        heartbeat_interval: float = 300.0,  # 5 minutes default
        debounce_seconds: float = 3.0,
        cooldown_seconds: float = 10.0,  # Min 10s between LLM calls
    ):
        self._detector = change_detector
        self._heartbeat = heartbeat_interval
        self._debounce = debounce_seconds
        self._cooldown = cooldown_seconds
        self._last_analysis: datetime = datetime.min
        self._pending_moderate: bool = False
        self._moderate_timestamp: datetime = datetime.min

    def should_analyze(
        self, frame: Frame, has_active_rules: bool = False
    ) -> tuple[bool, ChangeResult]:
        """Returns (should_send_to_llm, change_result).

        Args:
            frame: The current camera frame.
            has_active_rules: Whether any watch rules are active.
                If False, never auto-triggers LLM (zero cost mode).
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

        # MAJOR change: analyze immediately
        if result.level == ChangeLevel.MAJOR:
            self._last_analysis = now
            self._pending_moderate = False
            return True, result

        # MODERATE change: debounce (wait for scene to stabilize)
        if result.level == ChangeLevel.MODERATE:
            if not self._pending_moderate:
                self._pending_moderate = True
                self._moderate_timestamp = now
                return False, result
            elif (now - self._moderate_timestamp).total_seconds() >= self._debounce:
                self._last_analysis = now
                self._pending_moderate = False
                return True, result
            return False, result

        # MINOR/NONE: don't call LLM (not worth the cost)
        # Someone shifts in chair, lighting flickers — skip it

        # Heartbeat: periodic check (only with active rules)
        if since_last >= self._heartbeat:
            self._last_analysis = now
            return True, result

        return False, result
