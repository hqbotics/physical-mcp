"""Tests for the event-driven alert pipeline end-to-end.

Validates the full flow: perception loop -> rule evaluation -> notification dispatch,
ensuring exactly-once delivery semantics and correct budget/rate limiting.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from physical_mcp.notifications import NotificationDispatcher
from physical_mcp.config import NotificationsConfig
from physical_mcp.perception.scene_state import SceneState
from physical_mcp.rules.engine import RulesEngine
from physical_mcp.rules.models import (
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)
from physical_mcp.stats import StatsTracker


def _make_rule(
    id: str = "r1",
    cooldown: int = 60,
    notif_type: str = "openclaw",
    enabled: bool = True,
) -> WatchRule:
    return WatchRule(
        id=id,
        name=f"Rule {id}",
        condition="no person visible at desk",
        priority=RulePriority.HIGH,
        notification=NotificationTarget(
            type=notif_type, channel="telegram", target="123"
        ),
        cooldown_seconds=cooldown,
        enabled=enabled,
    )


def _make_eval(
    rule_id: str = "r1",
    triggered: bool = True,
    confidence: float = 0.9,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        triggered=triggered,
        confidence=confidence,
        reasoning="Desk is empty, person has left",
    )


class TestAlertPipeline:
    """Full pipeline from evaluation to notification dispatch."""

    @pytest.mark.asyncio
    async def test_perception_to_openclaw_delivery(self):
        """Full flow: evaluate -> process -> dispatch openclaw."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState(summary="Empty desk")

        # Process evaluation
        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 1

        # Dispatch
        config = NotificationsConfig(
            openclaw_channel="telegram",
            openclaw_target="123456",
            desktop_enabled=False,
        )
        dispatcher = NotificationDispatcher(config)

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch("os.path.exists", return_value=False),
        ):
            await dispatcher.dispatch(alerts[0])

        # Verify openclaw was called
        assert mock_exec.called
        call_args = mock_exec.call_args[0]
        assert "message" in call_args
        assert "send" in call_args

        await dispatcher.close()

    def test_no_alert_when_not_triggered(self):
        """triggered=False -> no alert dispatched."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState()

        evals = [_make_eval(triggered=False)]
        alerts = engine.process_evaluations(evals, scene)
        assert len(alerts) == 0

    def test_dispatch_called_once_per_alert(self):
        """Single trigger -> exactly one alert object."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState()

        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 1

        # Process same evaluation again -> blocked by cooldown
        alerts2 = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts2) == 0

    def test_disabled_rule_not_evaluated(self):
        """Disabled rule skipped in evaluation -- no alert."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1", enabled=False))
        scene = SceneState()

        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 0


class TestBudgetAndRateLimiting:
    """Budget and rate limiting prevent runaway costs."""

    def test_budget_exceeded_blocks_analysis(self):
        """When daily budget is exceeded, budget_exceeded() returns True."""
        stats = StatsTracker(daily_budget=0.01, max_per_hour=120)

        # Simulate 5 analyses at $0.003 each = $0.015 > $0.01 budget
        for _ in range(5):
            stats.record_analysis()

        assert stats.budget_exceeded() is True

    def test_hourly_rate_limit(self):
        """When hourly limit is reached, budget_exceeded() returns True."""
        stats = StatsTracker(daily_budget=0.0, max_per_hour=5)

        for _ in range(5):
            stats.record_analysis()

        assert stats.budget_exceeded() is True

    def test_stale_hourly_entries_pruned(self):
        """Old hourly entries are cleaned up so limit eventually resets."""
        from datetime import timedelta

        stats = StatsTracker(daily_budget=0.0, max_per_hour=3)

        # Add 3 analyses
        for _ in range(3):
            stats.record_analysis()

        assert stats.budget_exceeded() is True

        # Manually age the entries to >1 hour ago
        stats._hour_analyses = [
            datetime.now() - timedelta(hours=2) for _ in stats._hour_analyses
        ]

        # Now budget_exceeded should prune stale entries and return False
        assert stats.budget_exceeded() is False


class TestAlertEventStructure:
    """Alert events have correct structure for consumers."""

    def test_alert_event_has_scene_summary(self):
        """AlertEvent includes scene context for rich notifications."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState(summary="Empty room with desk")

        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 1
        assert alerts[0].scene_summary == "Empty room with desk"

    def test_alert_event_has_rule_details(self):
        """AlertEvent includes rule name and condition for context."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState()

        alerts = engine.process_evaluations([_make_eval()], scene)
        assert alerts[0].rule.name == "Rule r1"
        assert alerts[0].rule.condition == "no person visible at desk"
        assert alerts[0].evaluation.confidence == 0.9
