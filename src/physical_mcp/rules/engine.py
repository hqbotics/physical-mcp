"""Watch rules engine — evaluation, cooldown management, alert generation."""

from __future__ import annotations

import logging
from datetime import datetime

from ..perception.scene_state import SceneState
from .models import AlertEvent, RuleEvaluation, WatchRule

logger = logging.getLogger("physical-mcp")


class RulesEngine:
    """Evaluates watch rules against LLM analysis results."""

    def __init__(self) -> None:
        self._rules: dict[str, WatchRule] = {}

    def add_rule(self, rule: WatchRule) -> None:
        self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def load_rules(self, rules: list[WatchRule]) -> None:
        self._rules = {r.id: r for r in rules}

    def get_active_rules(self) -> list[WatchRule]:
        """Get rules that are enabled and not in cooldown."""
        now = datetime.now()
        active = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if rule.last_triggered:
                elapsed = (now - rule.last_triggered).total_seconds()
                if elapsed < rule.cooldown_seconds:
                    continue
            active.append(rule)
        return active

    def process_evaluations(
        self,
        evaluations: list[RuleEvaluation],
        scene_state: SceneState,
        frame_base64: str | None = None,
    ) -> list[AlertEvent]:
        """Process LLM evaluations and generate alerts for triggered rules."""
        now = datetime.now()
        alerts = []
        for ev in evaluations:
            # Log ALL evaluations for debugging
            rule = self._rules.get(ev.rule_id)
            rule_name = rule.name if rule else "unknown"
            logger.info(
                f"📊 EVAL: {rule_name} — triggered={ev.triggered}, "
                f"confidence={ev.confidence:.2f}, reason={ev.reasoning[:100]}"
            )
            if not ev.triggered or ev.confidence < 0.75:
                continue
            rule = self._rules.get(ev.rule_id)
            if rule is None or not rule.enabled:
                continue
            # Double-check cooldown
            if rule.last_triggered:
                elapsed = (now - rule.last_triggered).total_seconds()
                if elapsed < rule.cooldown_seconds:
                    continue
            rule.last_triggered = now
            alerts.append(
                AlertEvent(
                    rule=rule,
                    evaluation=ev,
                    scene_summary=scene_state.summary,
                    frame_base64=frame_base64,
                )
            )
        return alerts

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
