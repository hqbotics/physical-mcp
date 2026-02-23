"""Tests for the watch rules engine."""

from datetime import datetime, timedelta


from physical_mcp.perception.scene_state import SceneState
from physical_mcp.rules.engine import RulesEngine
from physical_mcp.rules.models import (
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)


def _make_rule(id: str = "r1", cooldown: int = 60) -> WatchRule:
    return WatchRule(
        id=id,
        name=f"Rule {id}",
        condition="test condition",
        priority=RulePriority.MEDIUM,
        notification=NotificationTarget(type="local"),
        cooldown_seconds=cooldown,
    )


def _make_eval(
    rule_id: str = "r1", triggered: bool = True, confidence: float = 0.9
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        triggered=triggered,
        confidence=confidence,
        reasoning="test",
    )


class TestRulesEngine:
    def test_add_and_list_rules(self):
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        engine.add_rule(_make_rule("r2"))
        assert len(engine.list_rules()) == 2

    def test_remove_rule(self):
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        assert engine.remove_rule("r1") is True
        assert engine.remove_rule("r1") is False
        assert len(engine.list_rules()) == 0

    def test_triggered_alert(self):
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState(summary="test scene")
        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 1
        assert alerts[0].rule.id == "r1"

    def test_cooldown_blocks_second_alert(self):
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1", cooldown=60))
        scene = SceneState()
        engine.process_evaluations([_make_eval()], scene)
        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 0

    def test_low_confidence_no_alert(self):
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState()
        alerts = engine.process_evaluations([_make_eval(confidence=0.5)], scene)
        assert len(alerts) == 0

    def test_not_triggered_no_alert(self):
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState()
        alerts = engine.process_evaluations([_make_eval(triggered=False)], scene)
        assert len(alerts) == 0

    def test_disabled_rule_not_active(self):
        engine = RulesEngine()
        rule = _make_rule("r1")
        rule.enabled = False
        engine.add_rule(rule)
        assert len(engine.get_active_rules()) == 0

    def test_cooldown_expired_rule_active(self):
        engine = RulesEngine()
        rule = _make_rule("r1", cooldown=60)
        rule.last_triggered = datetime.now() - timedelta(seconds=120)
        engine.add_rule(rule)
        assert len(engine.get_active_rules()) == 1

    def test_custom_message_field(self):
        """WatchRule supports custom_message field."""
        rule = WatchRule(
            id="r_cm",
            name="Custom Rule",
            condition="test",
            priority=RulePriority.MEDIUM,
            notification=NotificationTarget(type="local"),
            custom_message="Hello!",
        )
        assert rule.custom_message == "Hello!"

        # Verify serialization round-trip
        data = rule.model_dump(mode="json")
        assert data["custom_message"] == "Hello!"
        restored = WatchRule(**data)
        assert restored.custom_message == "Hello!"

    def test_custom_message_defaults_to_none(self):
        """WatchRule without custom_message defaults to None."""
        rule = _make_rule("r_default")
        assert rule.custom_message is None
