"""Tests for Discord webhook notification delivery."""

import base64
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from physical_mcp.notifications.discord import DiscordWebhookNotifier, _PRIORITY_COLOR
from physical_mcp.rules.models import (
    AlertEvent,
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)


def _make_alert(priority: str = "high", frame: str | None = None) -> AlertEvent:
    rule = WatchRule(
        id="r_test",
        name="Test Rule",
        condition="something happens",
        priority=RulePriority(priority),
        notification=NotificationTarget(type="discord"),
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
        frame_base64=frame,
    )


_FAKE_FRAME = base64.b64encode(b"\xff\xd8\xff\xe0fake-jpeg-data").decode()


class TestDiscordWebhookNotifier:
    @pytest.mark.asyncio
    async def test_no_url_returns_false(self):
        notifier = DiscordWebhookNotifier()
        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_embed_without_frame(self):
        """No frame → JSON POST with embed."""
        notifier = DiscordWebhookNotifier("https://discord.com/api/webhooks/fake")
        alert = _make_alert(frame=None)

        captured = {"url": None, "json": None}

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            captured["url"] = url
            captured["json"] = json
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(alert)

        assert result is True
        assert captured["json"] is not None
        embed = captured["json"]["embeds"][0]
        assert embed["title"] == "Test Rule"
        assert "I saw something happen" in embed["description"]
        assert embed["color"] == _PRIORITY_COLOR["high"]
        await notifier.close()

    @pytest.mark.asyncio
    async def test_image_with_frame(self):
        """Frame present → multipart POST with attachment."""
        notifier = DiscordWebhookNotifier("https://discord.com/api/webhooks/fake")
        alert = _make_alert(frame=_FAKE_FRAME)

        captured = {"url": None, "has_data": False, "json": None}

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            captured["url"] = url
            captured["has_data"] = data is not None
            captured["json"] = json
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(alert)

        assert result is True
        assert captured["has_data"] is True  # multipart form
        assert captured["json"] is None  # not json when multipart
        await notifier.close()

    @pytest.mark.asyncio
    async def test_priority_colors(self):
        """Each priority maps to a distinct colour."""
        assert _PRIORITY_COLOR["low"] == 0x3498DB
        assert _PRIORITY_COLOR["medium"] == 0xF1C40F
        assert _PRIORITY_COLOR["high"] == 0xE67E22
        assert _PRIORITY_COLOR["critical"] == 0xE74C3C

    @pytest.mark.asyncio
    async def test_custom_message(self):
        """custom_message replaces embed description."""
        notifier = DiscordWebhookNotifier("https://discord.com/api/webhooks/fake")
        rule = WatchRule(
            id="r_custom",
            name="Door Watch",
            condition="person at door",
            priority=RulePriority.HIGH,
            notification=NotificationTarget(type="discord"),
            custom_message="Someone is here!",
        )
        evaluation = RuleEvaluation(
            rule_id="r_custom", triggered=True, confidence=0.9, reasoning="Person seen"
        )
        alert = AlertEvent(rule=rule, evaluation=evaluation, scene_summary="Test")

        captured = {"json": None}

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            captured["json"] = json
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        await notifier.notify(alert)

        embed = captured["json"]["embeds"][0]
        assert embed["description"] == "Someone is here!"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_url_override(self):
        """Explicit webhook_url overrides default."""
        notifier = DiscordWebhookNotifier("https://default.url/hook")

        captured = {"url": None}

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            captured["url"] = url
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        await notifier.notify(
            _make_alert(frame=None), webhook_url="https://override.url/hook"
        )
        assert captured["url"] == "https://override.url/hook"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self):
        notifier = DiscordWebhookNotifier("https://discord.com/api/webhooks/fake")

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            raise Exception("Network error")
            yield  # pragma: no cover

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()
