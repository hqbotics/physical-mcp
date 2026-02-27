"""OpenClaw channel delivery -- Telegram, WhatsApp, Discord, Slack, Signal.

Bridges physical-mcp's event-driven alerts into OpenClaw's multi-channel
delivery system via the `openclaw message send` CLI subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from ..rules.models import AlertEvent

logger = logging.getLogger("physical-mcp")

# OpenClaw restricts media paths to its workspace directory.
_OPENCLAW_MEDIA_DIR = Path.home() / ".openclaw" / "workspace"
_FRAME_SRC = Path("/tmp/physical-mcp-frame.jpg")


class OpenClawNotifier:
    """Deliver alerts to any OpenClaw channel via CLI subprocess.

    Routes triggered watch-rule alerts to Telegram, WhatsApp, Discord,
    Slack, Signal, etc. using the ``openclaw message send`` command.

    Two-stage delivery: tries with camera image first, falls back to
    text-only if media upload fails (e.g. missing Slack ``files:write``
    scope).

    Args:
        default_channel: Default OpenClaw channel (e.g. "telegram", "slack").
        default_target: Default destination (chat_id, phone, channel_id).
        openclaw_bin: Path to the ``openclaw`` binary (auto-detected if empty).
    """

    def __init__(
        self,
        default_channel: str = "",
        default_target: str = "",
        openclaw_bin: str = "",
    ):
        self._default_channel = default_channel
        self._default_target = default_target
        self._bin = openclaw_bin or shutil.which("openclaw") or "openclaw"

    # ── Public API ──────────────────────────────────────────────────────

    async def notify(
        self,
        alert: AlertEvent,
        channel: str = "",
        target: str = "",
    ) -> bool:
        """Deliver alert message to an OpenClaw channel.

        Tries to attach the latest camera frame. If media upload fails
        (e.g. missing Slack scope), retries as text-only so the alert
        still gets delivered.

        Args:
            alert: The triggered alert event.
            channel: Override channel (falls back to default).
            target: Override target (falls back to default).

        Returns:
            True if the message was sent successfully.
        """
        ch = channel or self._default_channel
        dest = target or self._default_target

        if not ch:
            logger.warning("OpenClaw notifier: no channel configured")
            return False
        if not dest:
            logger.warning("OpenClaw notifier: no target configured")
            return False

        message = self._format_message(alert)
        base_cmd = [
            self._bin,
            "message",
            "send",
            "--channel",
            ch,
            "--target",
            dest,
            "-m",
            message,
        ]

        # Stage 1: try with camera frame image
        media_path = self._prepare_media()
        if media_path:
            ok = await self._run_cmd(
                base_cmd + ["--media", str(media_path)],
                label=f"{ch}/{dest}",
                rule_name=alert.rule.name,
            )
            if ok:
                return True
            logger.info("Media attach failed, retrying text-only")

        # Stage 2: text-only fallback (guaranteed to work)
        return await self._run_cmd(
            base_cmd,
            label=f"{ch}/{dest}",
            rule_name=alert.rule.name,
        )

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _prepare_media() -> Path | None:
        """Copy camera frame into OpenClaw's allowed media directory.

        Returns the path inside the workspace, or None if no frame exists.
        """
        if not _FRAME_SRC.exists():
            return None
        try:
            _OPENCLAW_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            dest = _OPENCLAW_MEDIA_DIR / "camera-alert.jpg"
            shutil.copy2(_FRAME_SRC, dest)
            return dest
        except Exception as e:
            logger.debug(f"Media copy failed: {e}")
            return None

    async def _run_cmd(
        self,
        cmd: list[str],
        label: str = "",
        rule_name: str = "",
    ) -> bool:
        """Execute an openclaw CLI command and return success."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode == 0:
                logger.info(f"OpenClaw alert sent to {label}: {rule_name}")
                return True
            else:
                logger.warning(
                    f"OpenClaw send failed (rc={proc.returncode}): "
                    f"{stderr.decode()[:200]}"
                )
                return False
        except asyncio.TimeoutError:
            logger.warning("OpenClaw send timed out (15s)")
            return False
        except FileNotFoundError:
            logger.warning(
                f"openclaw CLI not found at '{self._bin}'. "
                "Install OpenClaw or set openclaw_bin in config."
            )
            return False
        except Exception as e:
            logger.warning(f"OpenClaw send error: {e}")
            return False

    @staticmethod
    def _format_message(alert: AlertEvent) -> str:
        """Format an alert into a human-friendly chat message.

        Uses the rule's ``custom_message`` when set (user said
        "say X when Y happens"), otherwise falls back to a
        developer-friendly format with rule name, reasoning and
        confidence.
        """
        if alert.rule.custom_message:
            return alert.rule.custom_message
        parts = [
            f"[{alert.rule.name}] {alert.evaluation.reasoning}",
            f"Confidence: {alert.evaluation.confidence:.0%}",
        ]
        if alert.scene_summary:
            parts.append(f"Scene: {alert.scene_summary[:200]}")
        return "\n".join(parts)

    async def close(self) -> None:
        """No persistent resources to clean up."""
        pass
