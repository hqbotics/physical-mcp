"""Watch rules engine — evaluation, cooldown management, alert generation."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING

from ..perception.scene_state import SceneState
from .models import AlertEvent, RuleEvaluation, WatchRule

if TYPE_CHECKING:
    from ..eval_log import EvalLog

logger = logging.getLogger("physical-mcp")


class RulesEngine:
    """Evaluates watch rules against LLM analysis results."""

    def __init__(self, eval_log: EvalLog | None = None) -> None:
        self._rules: dict[str, WatchRule] = {}
        self._eval_log = eval_log

    def add_rule(self, rule: WatchRule) -> None:
        self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def load_rules(self, rules: list[WatchRule]) -> None:
        self._rules = {r.id: r for r in rules}

    def get_active_rules(self) -> list[WatchRule]:
        """Get all enabled rules (cooldown is enforced at alert dispatch, not here).

        Previously this filtered out cooled-down rules, which prevented the LLM
        from even seeing them.  Now we always send enabled rules to the LLM and
        only gate on cooldown when deciding whether to actually fire an alert.
        """
        return [r for r in self._rules.values() if r.enabled]

    def process_evaluations(
        self,
        evaluations: list[RuleEvaluation],
        scene_state: SceneState,
        frame_base64: str | None = None,
        camera_id: str = "",
        frame_thumbnail_bytes: bytes | None = None,
    ) -> list[AlertEvent]:
        """Process LLM evaluations and generate alerts for triggered rules.

        Args:
            frame_thumbnail_bytes: Optional small JPEG of the current frame
                for storage in the eval log.  When a user later provides
                feedback, this thumbnail is copied into the few-shot
                ``example_frames`` table for visual learning.

        Returns list of AlertEvent objects for triggered rules.
        """
        now = datetime.now()
        alerts = []
        self._last_eval_ids: dict[str, int] = {}

        global_threshold = float(os.environ.get("RULE_CONFIDENCE_THRESHOLD", "0.3"))

        for ev in evaluations:
            rule = self._rules.get(ev.rule_id)
            rule_name = rule.name if rule else "unknown"
            rule_condition = rule.condition if rule else ""

            # --- Log to EvalLog (every eval, triggered or not) ---
            # Store frame thumbnail only for triggered evaluations
            # (to keep storage manageable)
            _thumb = frame_thumbnail_bytes if ev.triggered else None
            eval_id = 0
            if self._eval_log:
                try:
                    eval_id = self._eval_log.log_evaluation(
                        rule_id=ev.rule_id,
                        rule_name=rule_name,
                        condition=rule_condition,
                        camera_id=camera_id,
                        triggered=ev.triggered,
                        confidence=ev.confidence,
                        reasoning=ev.reasoning,
                        scene_summary=scene_state.summary,
                        frame_thumbnail=_thumb,
                    )
                    self._last_eval_ids[ev.rule_id] = eval_id
                except Exception as e:
                    logger.warning(f"EvalLog write failed: {e}")

            logger.info(
                f"\U0001f4ca EVAL: {rule_name} \u2014 triggered={ev.triggered}, "
                f"confidence={ev.confidence:.2f}, reason={ev.reasoning[:100]}"
            )

            # --- Per-rule threshold (from self-tuning) or global ---
            _threshold = global_threshold
            if self._eval_log:
                try:
                    stats = self._eval_log.get_rule_stats(ev.rule_id)
                    if stats and stats.get("confidence_threshold"):
                        _threshold = stats["confidence_threshold"]
                except Exception:
                    pass

            if not ev.triggered or ev.confidence < _threshold:
                if ev.triggered and ev.confidence < _threshold:
                    logger.info(
                        f"  \u2192 DROPPED (confidence {ev.confidence:.2f} < {_threshold} threshold)"
                    )
                continue
            if rule is None or not rule.enabled:
                continue
            # Cooldown gate: only suppress alert dispatch, not LLM evaluation
            if rule.last_triggered:
                elapsed = (now - rule.last_triggered).total_seconds()
                if elapsed < rule.cooldown_seconds:
                    logger.info(
                        f"  \u2192 COOLDOWN: {rule.name} triggered but in cooldown "
                        f"({elapsed:.0f}s / {rule.cooldown_seconds}s)"
                    )
                    continue
            rule.last_triggered = now
            alerts.append(
                AlertEvent(
                    rule=rule,
                    evaluation=ev,
                    scene_summary=scene_state.summary,
                    frame_base64=frame_base64,
                    eval_id=eval_id,
                )
            )
        return alerts

    def get_last_eval_ids(self) -> dict[str, int]:
        """Return eval_log IDs from the most recent process_evaluations call."""
        return getattr(self, "_last_eval_ids", {})

    def process_client_evaluations(
        self,
        evaluations: list[dict],
        scene_state: SceneState,
        frame_base64: str | None = None,
    ) -> list[AlertEvent]:
        """Process rule evaluations submitted by the MCP client.

        Similar to process_evaluations() but accepts dict input from the
        report_rule_evaluation tool (client-side reasoning mode).

        Args:
            evaluations: List of dicts with keys:
                rule_id, triggered, confidence, reasoning
            scene_state: Current scene state for context

        Returns:
            List of triggered AlertEvent objects
        """
        parsed = []
        for ev_dict in evaluations:
            try:
                parsed.append(
                    RuleEvaluation(
                        rule_id=ev_dict["rule_id"],
                        triggered=bool(ev_dict.get("triggered", False)),
                        confidence=float(ev_dict.get("confidence", 0.0)),
                        reasoning=str(ev_dict.get("reasoning", "")),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return self.process_evaluations(parsed, scene_state, frame_base64=frame_base64)

    def list_rules(self) -> list[WatchRule]:
        return list(self._rules.values())
