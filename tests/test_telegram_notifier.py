"""Tests for Telegram Bot API notification delivery."""

import base64
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from physical_mcp.notifications.telegram import TelegramNotifier
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
        notification=NotificationTarget(type="telegram", target="12345"),
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


class TestTelegramNotifier:
    @pytest.mark.asyncio
    async def test_no_token_returns_false(self):
        notifier = TelegramNotifier()
        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_no_chat_id_returns_false(self):
        notifier = TelegramNotifier(bot_token="fake-token")
        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_text_message_without_frame(self):
        """No frame → sendMessage JSON."""
        notifier = TelegramNotifier("fake-token", "12345")
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
        assert "sendMessage" in captured["url"]
        assert captured["json"]["chat_id"] == "12345"
        assert "I saw something happen" in captured["json"]["text"]
        await notifier.close()

    @pytest.mark.asyncio
    async def test_photo_with_frame(self):
        """Frame present → sendPhoto with multipart form."""
        notifier = TelegramNotifier("fake-token", "12345")
        alert = _make_alert(frame=_FAKE_FRAME)

        captured = {"url": None, "has_data": False}

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            captured["url"] = url
            captured["has_data"] = data is not None
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(alert)

        assert result is True
        assert "sendPhoto" in captured["url"]
        assert captured["has_data"] is True
        await notifier.close()

    @pytest.mark.asyncio
    async def test_custom_message(self):
        """custom_message replaces default format."""
        notifier = TelegramNotifier("fake-token", "12345")
        rule = WatchRule(
            id="r_custom",
            name="Door Watch",
            condition="person at door",
            priority=RulePriority.HIGH,
            notification=NotificationTarget(type="telegram", target="12345"),
            custom_message="Hello visitor!",
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

        assert captured["json"]["text"] == "Hello visitor!"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_chat_id_override(self):
        """Explicit chat_id overrides default."""
        notifier = TelegramNotifier("fake-token", "default-id")
        alert = _make_alert(frame=None)

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

        await notifier.notify(alert, chat_id="override-id")

        assert captured["json"]["chat_id"] == "override-id"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self):
        """Network error returns False, no exception."""
        notifier = TelegramNotifier("fake-token", "12345")

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            raise Exception("Connection refused")
            yield  # pragma: no cover

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_http_error_returns_false(self):
        """HTTP 403 returns False."""
        notifier = TelegramNotifier("bad-token", "12345")

        @asynccontextmanager
        async def mock_post(url, json=None, data=None):
            resp = AsyncMock()
            resp.status = 403
            resp.text = AsyncMock(return_value="Forbidden")
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(_make_alert(frame=None))
        assert result is False
        await notifier.close()
