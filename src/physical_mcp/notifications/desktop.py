"""Cross-platform desktop notifications via OS-native commands.

- macOS: terminal-notifier (brew install terminal-notifier), osascript fallback
- Linux: notify-send (libnotify)
- Windows: PowerShell toast (best-effort)

No pip dependencies required.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time

logger = logging.getLogger("physical-mcp")


class DesktopNotifier:
    """Fire-and-forget desktop notifications with rate limiting.

    At most one notification per ``min_interval`` seconds to prevent
    spam from rapid scene changes.
    """

    def __init__(self, min_interval: float = 10.0):
        self._min_interval = min_interval
        self._last_sent: float = 0.0
        self._platform = sys.platform
        # On macOS, prefer terminal-notifier (reliable banners) over osascript
        self._has_terminal_notifier = (
            self._platform == "darwin"
            and shutil.which("terminal-notifier") is not None
        )

    def _should_send(self) -> bool:
        now = time.monotonic()
        if now - self._last_sent < self._min_interval:
            return False
        self._last_sent = now
        return True

    def notify(self, title: str, body: str) -> bool:
        """Send a desktop notification.  Non-blocking, fire-and-forget.

        Returns True if dispatched, False if rate-limited or unsupported.
        """
        if not self._should_send():
            logger.debug("Desktop notification rate-limited, skipping")
            return False

        try:
            logger.info(f"Desktop notification: {title}")
            if self._platform == "darwin":
                self._notify_macos(title, body)
            elif self._platform == "linux":
                self._notify_linux(title, body)
            elif self._platform == "win32":
                self._notify_windows(title, body)
            else:
                logger.debug(
                    f"Desktop notifications unsupported on {self._platform}"
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"Desktop notification error: {e}")
            return False

    # ── Platform backends ──────────────────────────────────────

    def _notify_macos(self, title: str, body: str) -> None:
        if self._has_terminal_notifier:
            subprocess.Popen(
                [
                    "terminal-notifier",
                    "-title", title,
                    "-message", body,
                    "-sound", "default",
                    "-group", "physical-mcp",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # Fallback to osascript (may not show banner on all systems)
            script = (
                f'display notification "{_escape(body)}" '
                f'with title "{_escape(title)}"'
            )
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _notify_linux(self, title: str, body: str) -> None:
        subprocess.Popen(
            ["notify-send", "--app-name=Physical MCP", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _notify_windows(self, title: str, body: str) -> None:
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime] "
            "| Out-Null; "
            "$xml = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$texts = $xml.GetElementsByTagName('text'); "
            f"$texts[0].AppendChild($xml.CreateTextNode('{_escape(title)}'))"
            " | Out-Null; "
            f"$texts[1].AppendChild($xml.CreateTextNode('{_escape(body)}'))"
            " | Out-Null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('Physical MCP').Show($toast)"
        )
        subprocess.Popen(
            ["powershell", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _escape(text: str) -> str:
    """Escape quotes and backslashes for shell embedding."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("'", "\\'")
    )
