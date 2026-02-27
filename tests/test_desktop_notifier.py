"""Tests for cross-platform desktop notifications."""

from __future__ import annotations

import time
from unittest.mock import patch


from physical_mcp.notifications.desktop import DesktopNotifier, _escape


class TestDesktopNotifier:
    """DesktopNotifier rate limiting and platform dispatch."""

    def test_first_notification_sends(self):
        """First call always dispatches."""
        notifier = DesktopNotifier(min_interval=10.0)
        # Mock the platform to avoid actual subprocess calls
        notifier._platform = "darwin"
        with patch.object(notifier, "_notify_macos") as mock:
            result = notifier.notify("Test", "Hello")
            assert result is True
            mock.assert_called_once_with("Test", "Hello")

    def test_rate_limiting(self):
        """Second call within min_interval is rate-limited."""
        notifier = DesktopNotifier(min_interval=60.0)
        notifier._platform = "darwin"
        with patch.object(notifier, "_notify_macos"):
            notifier.notify("First", "msg")
            result = notifier.notify("Second", "msg")
            assert result is False

    def test_rate_limit_expires(self):
        """Notification sends again after min_interval."""
        notifier = DesktopNotifier(min_interval=0.05)
        notifier._platform = "darwin"
        with patch.object(notifier, "_notify_macos") as mock:
            notifier.notify("First", "msg")
            time.sleep(0.06)
            result = notifier.notify("Second", "msg")
            assert result is True
            assert mock.call_count == 2

    def test_linux_dispatch(self):
        """Linux uses notify-send."""
        notifier = DesktopNotifier(min_interval=0)
        notifier._platform = "linux"
        with patch.object(notifier, "_notify_linux") as mock:
            result = notifier.notify("Alert", "Person detected")
            assert result is True
            mock.assert_called_once_with("Alert", "Person detected")

    def test_windows_dispatch(self):
        """Windows uses PowerShell toast."""
        notifier = DesktopNotifier(min_interval=0)
        notifier._platform = "win32"
        with patch.object(notifier, "_notify_windows") as mock:
            result = notifier.notify("Alert", "Motion")
            assert result is True
            mock.assert_called_once()

    def test_unsupported_platform(self):
        """Unsupported platform returns False."""
        notifier = DesktopNotifier(min_interval=0)
        notifier._platform = "freebsd"
        result = notifier.notify("Test", "Hello")
        assert result is False

    def test_exception_returns_false(self):
        """Subprocess errors are caught, returns False."""
        notifier = DesktopNotifier(min_interval=0)
        notifier._platform = "darwin"
        with patch.object(
            notifier, "_notify_macos", side_effect=OSError("no terminal-notifier")
        ):
            result = notifier.notify("Test", "Hello")
            assert result is False

    def test_macos_terminal_notifier(self):
        """macOS with terminal-notifier calls subprocess."""
        notifier = DesktopNotifier(min_interval=0)
        notifier._platform = "darwin"
        notifier._has_terminal_notifier = True
        with patch("physical_mcp.notifications.desktop.subprocess.Popen") as mock_popen:
            notifier._notify_macos("Alert", "Person seen")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "terminal-notifier"
            assert "-title" in args
            assert "Alert" in args

    def test_macos_osascript_fallback(self):
        """macOS without terminal-notifier falls back to osascript."""
        notifier = DesktopNotifier(min_interval=0)
        notifier._platform = "darwin"
        notifier._has_terminal_notifier = False
        with patch("physical_mcp.notifications.desktop.subprocess.Popen") as mock_popen:
            notifier._notify_macos("Alert", "Person seen")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "osascript"

    def test_linux_notify_send(self):
        """Linux calls notify-send with correct args."""
        notifier = DesktopNotifier(min_interval=0)
        notifier._platform = "linux"
        with patch("physical_mcp.notifications.desktop.subprocess.Popen") as mock_popen:
            notifier._notify_linux("Motion", "Camera 1")
            args = mock_popen.call_args[0][0]
            assert args[0] == "notify-send"
            assert "Motion" in args
            assert "Camera 1" in args


class TestEscapeFunction:
    """Tests for shell string escaping."""

    def test_escape_quotes(self):
        assert _escape('say "hello"') == 'say \\"hello\\"'

    def test_escape_single_quotes(self):
        assert _escape("it's") == "it\\'s"

    def test_escape_backslash(self):
        assert _escape("path\\to") == "path\\\\to"

    def test_escape_clean_string(self):
        assert _escape("normal text") == "normal text"

    def test_escape_combined(self):
        result = _escape("""He said "it's fine" \\ end""")
        assert '\\"' in result
        assert "\\'" in result
        assert "\\\\" in result
