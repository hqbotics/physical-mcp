"""Tests for OpenClaw channel notification delivery."""

from unittest.mock import AsyncMock, patch
import asyncio

import pytest

from physical_mcp.notifications.openclaw import OpenClawNotifier
from physical_mcp.rules.models import (
    AlertEvent,
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)


def _make_alert(frame_base64: str | None = None) -> AlertEvent:
    rule = WatchRule(
        id="r_test",
        name="Stand-up detector",
        condition="no person visible at desk",
        priority=RulePriority.HIGH,
        notification=NotificationTarget(
            type="openclaw", channel="telegram", target="123456"
        ),
    )
    evaluation = RuleEvaluation(
        rule_id="r_test",
        triggered=True,
        confidence=0.92,
        reasoning="The desk is empty, the person has left",
    )
    return AlertEvent(
        rule=rule,
        evaluation=evaluation,
        scene_summary="Empty desk with monitor and chair",
        frame_base64=frame_base64,
    )


class TestOpenClawNotifier:
    @pytest.mark.asyncio
    async def test_notify_sends_correct_cli_args(self):
        """Subprocess called with openclaw message send --channel --target -m."""
        notifier = OpenClawNotifier(
            default_channel="telegram",
            default_target="123456",
            openclaw_bin="/usr/bin/openclaw",
        )
        alert = _make_alert()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch("os.path.exists", return_value=False),
        ):
            result = await notifier.notify(alert)

        assert result is True
        # Check the call args
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "/usr/bin/openclaw"
        assert call_args[1] == "message"
        assert call_args[2] == "send"
        assert "--channel" in call_args
        idx = call_args.index("--channel")
        assert call_args[idx + 1] == "telegram"
        assert "--target" in call_args
        idx = call_args.index("--target")
        assert call_args[idx + 1] == "123456"
        assert "-m" in call_args

    @pytest.mark.asyncio
    async def test_message_format(self):
        """Body includes rule name, reasoning, and confidence."""
        notifier = OpenClawNotifier(
            default_channel="slack",
            default_target="C123",
        )
        alert = _make_alert()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch("os.path.exists", return_value=False),
        ):
            await notifier.notify(alert)

        call_args = mock_exec.call_args[0]
        msg_idx = call_args.index("-m")
        message = call_args[msg_idx + 1]
        assert "Stand-up detector" in message
        assert "desk is empty" in message
        assert "92%" in message

    @pytest.mark.asyncio
    async def test_media_attachment_when_frame_exists(self):
        """--media flag passed when frame file exists on disk."""
        notifier = OpenClawNotifier(
            default_channel="telegram",
            default_target="123",
        )
        alert = _make_alert()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch.object(
                notifier, "_prepare_media", return_value="/mock/camera-alert.jpg"
            ),
        ):
            await notifier.notify(alert)

        # First call should include --media with the prepared path
        call_args = mock_exec.call_args_list[0][0]
        assert "--media" in call_args
        assert "/mock/camera-alert.jpg" in call_args

    @pytest.mark.asyncio
    async def test_no_media_when_frame_missing(self):
        """--media NOT passed when frame file does not exist."""
        notifier = OpenClawNotifier(
            default_channel="telegram",
            default_target="123",
        )
        alert = _make_alert()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch.object(notifier, "_prepare_media", return_value=None),
        ):
            await notifier.notify(alert)

        call_args = mock_exec.call_args[0]
        assert "--media" not in call_args

    @pytest.mark.asyncio
    async def test_missing_channel_returns_false(self):
        """No channel configured returns False, no crash."""
        notifier = OpenClawNotifier(default_channel="", default_target="123")
        result = await notifier.notify(_make_alert())
        assert result is False

    @pytest.mark.asyncio
    async def test_missing_target_returns_false(self):
        """No target configured returns False, no crash."""
        notifier = OpenClawNotifier(default_channel="telegram", default_target="")
        result = await notifier.notify(_make_alert())
        assert result is False

    @pytest.mark.asyncio
    async def test_cli_not_found_returns_false(self):
        """FileNotFoundError from subprocess handled gracefully."""
        notifier = OpenClawNotifier(
            default_channel="telegram",
            default_target="123",
            openclaw_bin="/nonexistent/openclaw",
        )

        with (
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("No such file"),
            ),
            patch("os.path.exists", return_value=False),
        ):
            result = await notifier.notify(_make_alert())

        assert result is False

    @pytest.mark.asyncio
    async def test_cli_timeout_returns_false(self):
        """15s timeout returns False, no hang."""
        notifier = OpenClawNotifier(
            default_channel="telegram",
            default_target="123",
        )

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("os.path.exists", return_value=False),
        ):
            result = await notifier.notify(_make_alert())

        assert result is False

    @pytest.mark.asyncio
    async def test_cli_nonzero_exit_returns_false(self):
        """Non-zero exit code returns False."""
        notifier = OpenClawNotifier(
            default_channel="telegram",
            default_target="123",
        )

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: auth failed"))
        mock_proc.returncode = 1

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("os.path.exists", return_value=False),
        ):
            result = await notifier.notify(_make_alert())

        assert result is False

    @pytest.mark.asyncio
    async def test_custom_message_used_when_set(self):
        """custom_message replaces default format entirely."""
        notifier = OpenClawNotifier(
            default_channel="slack",
            default_target="C123",
        )
        rule = WatchRule(
            id="r_custom",
            name="X-shape detector",
            condition="person forming X shape",
            priority=RulePriority.HIGH,
            notification=NotificationTarget(
                type="openclaw", channel="slack", target="C123"
            ),
            custom_message="NO WAY YOU DID IT!",
        )
        evaluation = RuleEvaluation(
            rule_id="r_custom",
            triggered=True,
            confidence=0.92,
            reasoning="The person is forming an X shape with their arms",
        )
        alert = AlertEvent(
            rule=rule,
            evaluation=evaluation,
            scene_summary="Person at desk",
        )

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch.object(notifier, "_prepare_media", return_value=None),
        ):
            await notifier.notify(alert)

        call_args = mock_exec.call_args[0]
        msg_idx = call_args.index("-m")
        message = call_args[msg_idx + 1]
        assert message == "NO WAY YOU DID IT!"
        assert "X-shape detector" not in message
        assert "92%" not in message

    def test_format_message_falls_back_without_custom(self):
        """Without custom_message, default format is used."""
        alert = _make_alert()
        msg = OpenClawNotifier._format_message(alert)
        assert "Stand-up detector" in msg
        assert "92%" in msg

    @pytest.mark.asyncio
    async def test_per_rule_channel_override(self):
        """Per-rule channel/target overrides default config."""
        notifier = OpenClawNotifier(
            default_channel="slack",
            default_target="C999",
        )
        alert = _make_alert()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch("os.path.exists", return_value=False),
        ):
            # Override with whatsapp
            await notifier.notify(alert, channel="whatsapp", target="+1234567890")

        call_args = mock_exec.call_args[0]
        idx = call_args.index("--channel")
        assert call_args[idx + 1] == "whatsapp"
        idx = call_args.index("--target")
        assert call_args[idx + 1] == "+1234567890"
