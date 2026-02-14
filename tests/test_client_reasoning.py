"""Tests for client-side reasoning — process_client_evaluations."""

from datetime import datetime

import pytest

from physical_mcp.perception.scene_state import SceneState
from physical_mcp.rules.engine import RulesEngine
from physical_mcp.rules.models import WatchRule, RulePriority, NotificationTarget


def _make_rule(
    rule_id: str = "r_test1",
    condition: str = "someone enters the room",
    cooldown: int = 60,
) -> WatchRule:
    return WatchRule(
        id=rule_id,
        name=f"Rule {rule_id}",
        condition=condition,
        priority=RulePriority.MEDIUM,
        notification=NotificationTarget(),
        cooldown_seconds=cooldown,
    )


class TestClientEvaluations:
    def test_valid_triggered_evaluation(self):
        """Client reports a triggered rule — should generate alert."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1"))
        scene = SceneState()
        scene.update("Test scene", ["chair"], 1, "change")

        evaluations = [
            {
                "rule_id": "r_1",
                "triggered": True,
                "confidence": 0.9,
                "reasoning": "I see someone entering the room",
            }
        ]

        alerts = engine.process_client_evaluations(evaluations, scene)
        assert len(alerts) == 1
        assert alerts[0].rule.id == "r_1"
        assert alerts[0].evaluation.confidence == 0.9
        assert alerts[0].evaluation.reasoning == "I see someone entering the room"

    def test_not_triggered_evaluation(self):
        """Client reports rule NOT triggered — no alert."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1"))
        scene = SceneState()

        evaluations = [
            {
                "rule_id": "r_1",
                "triggered": False,
                "confidence": 0.1,
                "reasoning": "Room is empty",
            }
        ]

        alerts = engine.process_client_evaluations(evaluations, scene)
        assert len(alerts) == 0

    def test_low_confidence_does_not_trigger(self):
        """Triggered but low confidence (< 0.7) — no alert."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1"))
        scene = SceneState()

        evaluations = [
            {
                "rule_id": "r_1",
                "triggered": True,
                "confidence": 0.5,
                "reasoning": "Maybe someone, not sure",
            }
        ]

        alerts = engine.process_client_evaluations(evaluations, scene)
        assert len(alerts) == 0

    def test_unknown_rule_id_ignored(self):
        """Evaluation for a rule that doesn't exist — silently ignored."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1"))
        scene = SceneState()

        evaluations = [
            {
                "rule_id": "r_nonexistent",
                "triggered": True,
                "confidence": 0.95,
                "reasoning": "Something triggered",
            }
        ]

        alerts = engine.process_client_evaluations(evaluations, scene)
        assert len(alerts) == 0

    def test_malformed_evaluation_skipped(self):
        """Missing required fields — skipped, no crash."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1"))
        scene = SceneState()

        evaluations = [
            {"triggered": True},  # Missing rule_id
            {"rule_id": "r_1"},   # Missing triggered (defaults False)
            "not a dict",         # Completely wrong type
        ]

        # Should not crash — malformed entries are skipped
        alerts = engine.process_client_evaluations(evaluations, scene)
        assert len(alerts) == 0

    def test_cooldown_respected(self):
        """After triggering, same rule should be in cooldown."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1", cooldown=300))
        scene = SceneState()

        eval1 = [
            {
                "rule_id": "r_1",
                "triggered": True,
                "confidence": 0.9,
                "reasoning": "First trigger",
            }
        ]

        # First trigger should work
        alerts1 = engine.process_client_evaluations(eval1, scene)
        assert len(alerts1) == 1

        # Second trigger immediately — should be in cooldown
        eval2 = [
            {
                "rule_id": "r_1",
                "triggered": True,
                "confidence": 0.95,
                "reasoning": "Second trigger",
            }
        ]
        alerts2 = engine.process_client_evaluations(eval2, scene)
        assert len(alerts2) == 0

    def test_multiple_rules_evaluated(self):
        """Multiple rules in one batch — each evaluated independently."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1", condition="person enters"))
        engine.add_rule(_make_rule("r_2", condition="door opens"))
        scene = SceneState()

        evaluations = [
            {
                "rule_id": "r_1",
                "triggered": True,
                "confidence": 0.85,
                "reasoning": "Person visible",
            },
            {
                "rule_id": "r_2",
                "triggered": False,
                "confidence": 0.1,
                "reasoning": "Door is closed",
            },
        ]

        alerts = engine.process_client_evaluations(evaluations, scene)
        assert len(alerts) == 1
        assert alerts[0].rule.id == "r_1"

    def test_empty_evaluations(self):
        """Empty list — no alerts, no crash."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1"))
        scene = SceneState()

        alerts = engine.process_client_evaluations([], scene)
        assert len(alerts) == 0
