"""Tests for desktop notification delivery."""

import time
from unittest.mock import patch, MagicMock

from physical_mcp.notifications.desktop import DesktopNotifier, _escape


class TestDesktopNotifier:
    def test_rate_limiting_blocks_rapid_calls(self):
        """Second call within min_interval is skipped."""
        notifier = DesktopNotifier(min_interval=60.0)
        with patch.object(notifier, "_notify_macos"):
            notifier._platform = "darwin"
            assert notifier.notify("Title", "Body") is True
            assert notifier.notify("Title2", "Body2") is False  # rate-limited

    def test_rate_limiting_allows_after_interval(self):
        """Call after min_interval passes should succeed."""
        notifier = DesktopNotifier(min_interval=0.0)  # no delay
        with patch.object(notifier, "_notify_macos"):
            notifier._platform = "darwin"
            assert notifier.notify("A", "B") is True
            assert notifier.notify("C", "D") is True

    def test_macos_with_terminal_notifier(self):
        """macOS uses terminal-notifier when available."""
        notifier = DesktopNotifier()
        notifier._platform = "darwin"
        notifier._has_terminal_notifier = True
        with patch("physical_mcp.notifications.desktop.subprocess.Popen") as mock_popen:
            notifier.notify("Test Title", "Test Body")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "terminal-notifier"
            assert "-title" in args
            assert "Test Title" in args

    def test_macos_falls_back_to_osascript(self):
        """macOS falls back to osascript when terminal-notifier not installed."""
        notifier = DesktopNotifier()
        notifier._platform = "darwin"
        notifier._has_terminal_notifier = False
        with patch("physical_mcp.notifications.desktop.subprocess.Popen") as mock_popen:
            notifier.notify("Test Title", "Test Body")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "osascript"
            assert "Test Title" in args[2]

    def test_linux_calls_notify_send(self):
        """Linux backend calls notify-send."""
        notifier = DesktopNotifier()
        notifier._platform = "linux"
        with patch("physical_mcp.notifications.desktop.subprocess.Popen") as mock_popen:
            notifier.notify("Test Title", "Test Body")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "notify-send"

    def test_unsupported_platform_returns_false(self):
        """Unknown platform returns False."""
        notifier = DesktopNotifier()
        notifier._platform = "freebsd"
        assert notifier.notify("Title", "Body") is False

    def test_exception_does_not_crash(self):
        """Errors are caught, returns False."""
        notifier = DesktopNotifier()
        notifier._platform = "darwin"
        notifier._has_terminal_notifier = False
        with patch(
            "physical_mcp.notifications.desktop.subprocess.Popen",
            side_effect=FileNotFoundError("osascript not found"),
        ):
            assert notifier.notify("Title", "Body") is False


class TestEscape:
    def test_escapes_double_quotes(self):
        assert _escape('say "hello"') == 'say \\"hello\\"'

    def test_escapes_single_quotes(self):
        assert _escape("it's") == "it\\'s"

    def test_escapes_backslashes(self):
        assert _escape("path\\to") == "path\\\\to"
