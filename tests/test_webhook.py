"""Tests for webhook notification delivery."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from physical_mcp.notifications.webhook import WebhookNotifier
from physical_mcp.rules.models import (
    AlertEvent,
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)


def _make_alert() -> AlertEvent:
    rule = WatchRule(
        id="r_test",
        name="Test Rule",
        condition="something happens",
        priority=RulePriority.HIGH,
        notification=NotificationTarget(type="webhook", url="http://example.com/hook"),
    )
    evaluation = RuleEvaluation(
        rule_id="r_test",
        triggered=True,
        confidence=0.9,
        reasoning="I saw something happen",
    )
    return AlertEvent(rule=rule, evaluation=evaluation, scene_summary="Test scene")


class TestWebhookNotifier:
    @pytest.mark.asyncio
    async def test_no_url_returns_false(self):
        """No URL configured returns False."""
        notifier = WebhookNotifier()
        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_notify_builds_correct_payload(self):
        """Verify payload structure."""
        from contextlib import asynccontextmanager

        notifier = WebhookNotifier("http://example.com/hook")
        alert = _make_alert()

        captured_payload = {}

        @asynccontextmanager
        async def mock_post(url, json=None):
            captured_payload.update(json or {})
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post

        notifier._session = mock_session
        result = await notifier.notify(alert)

        assert result is True
        assert captured_payload["rule_id"] == "r_test"
        assert captured_payload["event"] == "rule_triggered"
        assert captured_payload["confidence"] == 0.9

        await notifier.close()

    @pytest.mark.asyncio
    async def test_notify_error_does_not_crash(self):
        """Network error returns False, no exception."""
        notifier = WebhookNotifier("http://localhost:1/nonexistent")

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(side_effect=Exception("Connection refused"))
        notifier._session = mock_session

        result = await notifier.notify(_make_alert())
        assert result is False

        await notifier.close()
