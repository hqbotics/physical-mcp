"""Tests for generic webhook notification delivery."""

import base64
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from physical_mcp.notifications.webhook import WebhookNotifier
from physical_mcp.rules.models import (
    AlertEvent,
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)


def _make_alert(
    priority: str = "high", frame: str | None = None, custom_msg: str | None = None
) -> AlertEvent:
    rule = WatchRule(
        id="r_test",
        name="Test Rule",
        condition="something happens",
        priority=RulePriority(priority),
        notification=NotificationTarget(type="webhook", url="https://example.com/hook"),
        custom_message=custom_msg,
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


class TestWebhookNotifier:
    @pytest.mark.asyncio
    async def test_no_url_returns_false(self):
        notifier = WebhookNotifier()
        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_json_payload_structure(self):
        """Verify JSON payload contains all expected fields."""
        notifier = WebhookNotifier("https://example.com/hook")
        alert = _make_alert(frame=None)

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
        assert payload["event"] == "watch_rule_triggered"
        assert payload["rule_name"] == "Test Rule"
        assert payload["rule_id"] == "r_test"
        assert payload["condition"] == "something happens"
        assert payload["reasoning"] == "I saw something happen"
        assert payload["confidence"] == 0.9
        assert payload["priority"] == "high"
        assert payload["scene_summary"] == "Test scene"
        assert "timestamp" in payload
        assert "image_base64" not in payload  # no frame
        await notifier.close()

    @pytest.mark.asyncio
    async def test_includes_frame_when_present(self):
        """Frame base64 included in payload."""
        notifier = WebhookNotifier("https://example.com/hook")
        alert = _make_alert(frame=_FAKE_FRAME)

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

        assert captured["json"]["image_base64"] == _FAKE_FRAME
        await notifier.close()

    @pytest.mark.asyncio
    async def test_custom_message_in_payload(self):
        """custom_message included in payload."""
        notifier = WebhookNotifier("https://example.com/hook")
        alert = _make_alert(custom_msg="Hello!")

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

        assert captured["json"]["custom_message"] == "Hello!"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_url_override(self):
        """Explicit url overrides default."""
        notifier = WebhookNotifier("https://default.url")

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

        await notifier.notify(_make_alert(), url="https://override.url")
        assert captured["url"] == "https://override.url"
        await notifier.close()

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self):
        notifier = WebhookNotifier("https://example.com/hook")

        @asynccontextmanager
        async def mock_post(url, json=None):
            raise Exception("Connection refused")
            yield  # pragma: no cover

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()
