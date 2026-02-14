"""Tests for ntfy.sh notification delivery."""

import base64
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from physical_mcp.notifications.ntfy import NtfyNotifier
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
        notification=NotificationTarget(type="ntfy", channel="test-topic"),
    )
    evaluation = RuleEvaluation(
        rule_id="r_test",
        triggered=True,
        confidence=0.9,
        reasoning="I saw something happen",
    )
    return AlertEvent(
        rule=rule, evaluation=evaluation, scene_summary="Test scene",
        frame_base64=frame,
    )


# Fake JPEG bytes for image tests
_FAKE_FRAME = base64.b64encode(b"\xff\xd8\xff\xe0fake-jpeg-data").decode()


class TestNtfyNotifier:
    @pytest.mark.asyncio
    async def test_no_topic_returns_false(self):
        """No topic configured returns False."""
        notifier = NtfyNotifier()
        result = await notifier.notify(_make_alert())
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_text_post_without_frame(self):
        """No frame → POST text body, no Filename header."""
        notifier = NtfyNotifier("test-topic")
        alert = _make_alert(priority="high", frame=None)

        captured = {"method": None, "headers": {}, "data": None}

        @asynccontextmanager
        async def mock_post(url, data=None, headers=None):
            captured["method"] = "POST"
            captured["headers"] = headers or {}
            captured["data"] = data
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify(alert)

        assert result is True
        assert captured["method"] == "POST"
        assert "Filename" not in captured["headers"]
        assert "X-Message" not in captured["headers"]
        # Title is just the rule name (no [HIGH] prefix)
        assert captured["headers"]["Title"] == "Test Rule"

        await notifier.close()

    @pytest.mark.asyncio
    async def test_image_put_with_frame(self):
        """Frame present → PUT binary JPEG, text in X-Message header."""
        notifier = NtfyNotifier("test-topic")
        alert = _make_alert(priority="high", frame=_FAKE_FRAME)

        captured = {"method": None, "headers": {}, "data": None}

        @asynccontextmanager
        async def mock_put(url, data=None, headers=None):
            captured["method"] = "PUT"
            captured["headers"] = headers or {}
            captured["data"] = data
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.put = mock_put
        notifier._session = mock_session

        result = await notifier.notify(alert)

        assert result is True
        assert captured["method"] == "PUT"
        assert captured["headers"]["Filename"] == "camera.jpg"
        assert "I saw something happen" in captured["headers"]["X-Message"]
        # Data should be raw bytes, not base64
        assert isinstance(captured["data"], bytes)
        assert captured["data"] == base64.b64decode(_FAKE_FRAME)

        await notifier.close()

    @pytest.mark.asyncio
    async def test_title_is_rule_name(self):
        """Title should be just the rule name, no priority prefix."""
        notifier = NtfyNotifier("test-topic")
        alert = _make_alert(priority="critical")

        captured_headers = {}

        @asynccontextmanager
        async def mock_post(url, data=None, headers=None):
            captured_headers.update(headers or {})
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        await notifier.notify(alert)

        assert captured_headers["Title"] == "Test Rule"
        assert "[CRITICAL]" not in captured_headers["Title"]
        assert captured_headers["Priority"] == "5"  # critical → 5

        await notifier.close()

    @pytest.mark.asyncio
    async def test_notify_body_contains_reasoning(self):
        """Verify body includes reasoning and condition."""
        notifier = NtfyNotifier("test-topic")
        alert = _make_alert()

        captured_body = b""

        @asynccontextmanager
        async def mock_post(url, data=None, headers=None):
            nonlocal captured_body
            captured_body = data
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        await notifier.notify(alert)

        body_text = captured_body.decode()
        assert "I saw something happen" in body_text
        assert "something happens" in body_text
        assert "90%" in body_text

        await notifier.close()

    @pytest.mark.asyncio
    async def test_priority_mapping(self):
        """Test all priority levels map correctly."""
        from physical_mcp.notifications.ntfy import _NTFY_PRIORITY

        assert _NTFY_PRIORITY["low"] == "2"
        assert _NTFY_PRIORITY["medium"] == "3"
        assert _NTFY_PRIORITY["high"] == "4"
        assert _NTFY_PRIORITY["critical"] == "5"

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self):
        """Network error returns False, no exception."""
        notifier = NtfyNotifier("test-topic")

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(side_effect=Exception("Connection refused"))
        notifier._session = mock_session

        result = await notifier.notify(_make_alert())
        assert result is False

        await notifier.close()

    @pytest.mark.asyncio
    async def test_scene_change_no_topic_returns_false(self):
        """Scene change with empty topic returns False."""
        notifier = NtfyNotifier()
        result = await notifier.notify_scene_change("", "major", ["Rule 1"])
        assert result is False
        await notifier.close()

    @pytest.mark.asyncio
    async def test_scene_change_with_frame(self):
        """Scene change sends PUT with image when frame provided."""
        notifier = NtfyNotifier("test-topic")

        captured = {"method": None, "headers": {}}

        @asynccontextmanager
        async def mock_put(url, data=None, headers=None):
            captured["method"] = "PUT"
            captured["headers"] = headers or {}
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.put = mock_put
        notifier._session = mock_session

        result = await notifier.notify_scene_change(
            "test-topic", "major", ["Front door"], frame_base64=_FAKE_FRAME,
        )

        assert result is True
        assert captured["method"] == "PUT"
        assert captured["headers"]["Filename"] == "camera.jpg"

        await notifier.close()

    @pytest.mark.asyncio
    async def test_scene_change_without_frame(self):
        """Scene change sends POST text when no frame."""
        notifier = NtfyNotifier("test-topic")

        captured = {"method": None}

        @asynccontextmanager
        async def mock_post(url, data=None, headers=None):
            captured["method"] = "POST"
            resp = AsyncMock()
            resp.status = 200
            yield resp

        mock_session = AsyncMock()
        mock_session.post = mock_post
        notifier._session = mock_session

        result = await notifier.notify_scene_change(
            "test-topic", "minor", ["Baby monitor"],
        )

        assert result is True
        assert captured["method"] == "POST"

        await notifier.close()
