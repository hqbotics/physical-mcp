"""Tests for Slack incoming webhook notification delivery."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from physical_mcp.notifications.slack import SlackWebhookNotifier
from physical_mcp.rules.models import (
    AlertEvent,
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)


def _make_alert(priority: str = "high") -> AlertEvent:
    rule = WatchRule(
        id="r_test",
        name="Test Rule",
        condition="something happens",
        priority=RulePriority(priority),
        notification=NotificationTarget(type="slack"),
    )
    evaluation = RuleEvaluation(
        rule_id="r_test",
        triggered=True,
        confidence=0.9,
        reasoning="I saw something happen",
    )
    return AlertEvent(
        rule=rule,
        evaluation=evaluation,
        scene_summary="Test scene",
    )


class TestSlackWebhookNotifier:
    @pytest.mark.asyncio
    async def test_no_url_returns_false(self):
        notifier = SlackWebhookNotifier()
        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_block_kit_payload(self):
        """Verify Block Kit structure."""
        notifier = SlackWebhookNotifier("https://hooks.slack.com/services/fake")
        alert = _make_alert()

        captured = {"json": None}

        @asynccontextmanager
        async def mock_post(url, json=None):
            captured["json"] = json
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(alert)

        assert result is True
        payload = captured["json"]
        assert "blocks" in payload
        assert "text" in payload  # fallback text
        # Header block
        assert payload["blocks"][0]["type"] == "header"
        assert payload["blocks"][0]["text"]["text"] == "Test Rule"
        # Section block with reasoning
        assert payload["blocks"][1]["type"] == "section"
        assert "I saw something happen" in payload["blocks"][1]["text"]["text"]
        # Context block with priority
        assert payload["blocks"][2]["type"] == "context"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_custom_message(self):
        """custom_message replaces block text."""
        notifier = SlackWebhookNotifier("https://hooks.slack.com/services/fake")
        rule = WatchRule(
            id="r_custom",
            name="Door Watch",
            condition="person at door",
            priority=RulePriority.HIGH,
            notification=NotificationTarget(type="slack"),
            custom_message="Someone at the door!",
        )
        evaluation = RuleEvaluation(
            rule_id="r_custom", triggered=True, confidence=0.9, reasoning="Person seen"
        )
        alert = AlertEvent(rule=rule, evaluation=evaluation, scene_summary="Test")

        captured = {"json": None}

        @asynccontextmanager
        async def mock_post(url, json=None):
            captured["json"] = json
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        await notifier.notify(alert)

        section = captured["json"]["blocks"][1]
        assert "Someone at the door!" in section["text"]["text"]
        await notifier.close()

    @pytest.mark.asyncio
    async def test_url_override(self):
        """Explicit webhook_url overrides default."""
        notifier = SlackWebhookNotifier("https://default.url")

        captured = {"url": None}

        @asynccontextmanager
        async def mock_post(url, json=None):
            captured["url"] = url
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        await notifier.notify(_make_alert(), webhook_url="https://override.url")
        assert captured["url"] == "https://override.url"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self):
        notifier = SlackWebhookNotifier("https://hooks.slack.com/services/fake")

        @asynccontextmanager
        async def mock_post(url, json=None):
            raise Exception("Network error")
            yield  # pragma: no cover

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()
