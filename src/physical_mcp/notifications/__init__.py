"""Notification dispatch for triggered watch rules.

Routes alerts to the appropriate channel:
- "local": no-op (the MCP tool response IS the notification)
- "desktop": OS-native desktop notification (macOS / Linux / Windows)
- "ntfy": push notification via ntfy.sh (free, zero-signup)
- "telegram": direct Telegram Bot API (sendPhoto with camera frame)
- "discord": Discord incoming webhook (embed with image)
- "slack": Slack incoming webhook (Block Kit, text only)
- "webhook": generic HTTP POST (JSON payload)
- "openclaw": multi-channel delivery via OpenClaw CLI (Telegram, WhatsApp, etc.)
"""

from __future__ import annotations

__all__ = ["NotificationDispatcher"]

import logging

from ..config import NotificationsConfig
from ..rules.models import AlertEvent
from .desktop import DesktopNotifier
from .discord import DiscordWebhookNotifier
from .ntfy import NtfyNotifier
from .openclaw import OpenClawNotifier
from .slack import SlackWebhookNotifier
from .telegram import TelegramNotifier
from .webhook import WebhookNotifier

logger = logging.getLogger("physical-mcp")


class NotificationDispatcher:
    """Routes alerts to the appropriate notification channel."""

    def __init__(self, config: NotificationsConfig):
        self._config = config
        self._desktop = (
            DesktopNotifier(min_interval=10.0) if config.desktop_enabled else None
        )
        self._ntfy = NtfyNotifier(
            default_topic=config.ntfy_topic,
            server_url=config.ntfy_server_url,
        )
        self._openclaw = OpenClawNotifier(
            default_channel=config.openclaw_channel,
            default_target=config.openclaw_target,
        )
        self._telegram = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            default_chat_id=config.telegram_chat_id,
        )
        self._discord = DiscordWebhookNotifier(
            default_webhook_url=config.discord_webhook_url,
        )
        self._slack = SlackWebhookNotifier(
            default_webhook_url=config.slack_webhook_url,
        )
        self._webhook = WebhookNotifier(
            default_url=config.webhook_url,
        )

    async def dispatch(self, alert: AlertEvent) -> None:
        """Send notification based on rule's notification target."""
        target = alert.rule.notification
        logger.info(
            f"Dispatching notification: type={target.type}, "
            f"rule={alert.rule.name}, desktop_enabled={self._desktop is not None}"
        )
        if target.type == "desktop":
            if self._desktop:
                title = f"[{alert.rule.priority.value.upper()}] {alert.rule.name}"
                body = alert.rule.custom_message or alert.evaluation.reasoning
                self._desktop.notify(title, body)
            else:
                logger.warning(
                    "Desktop notification requested but desktop_enabled=False"
                )
        elif target.type == "ntfy":
            topic = target.channel or self._config.ntfy_topic
            await self._ntfy.notify(alert, topic)
            # Desktop bonus alongside ntfy (local machine gets popup too)
            if self._desktop:
                body = alert.rule.custom_message or alert.evaluation.reasoning
                self._desktop.notify(alert.rule.name, body)
        elif target.type == "telegram":
            chat_id = target.target or self._config.telegram_chat_id
            await self._telegram.notify(alert, chat_id=chat_id)
            if self._desktop:
                body = alert.rule.custom_message or alert.evaluation.reasoning
                self._desktop.notify(alert.rule.name, body)
        elif target.type == "discord":
            url = target.url or self._config.discord_webhook_url
            await self._discord.notify(alert, webhook_url=url)
            if self._desktop:
                body = alert.rule.custom_message or alert.evaluation.reasoning
                self._desktop.notify(alert.rule.name, body)
        elif target.type == "slack":
            url = target.url or self._config.slack_webhook_url
            await self._slack.notify(alert, webhook_url=url)
            if self._desktop:
                body = alert.rule.custom_message or alert.evaluation.reasoning
                self._desktop.notify(alert.rule.name, body)
        elif target.type == "webhook":
            url = target.url or self._config.webhook_url
            await self._webhook.notify(alert, url=url)
        elif target.type == "openclaw":
            # Fan out to multiple channels (comma-separated)
            channels = (target.channel or self._config.openclaw_channel).split(",")
            targets = (target.target or self._config.openclaw_target).split(",")
            for ch, dest in zip(channels, targets):
                await self._openclaw.notify(
                    alert, channel=ch.strip(), target=dest.strip()
                )
            # Desktop bonus alongside openclaw (local machine gets popup too)
            if self._desktop:
                body = alert.rule.custom_message or alert.evaluation.reasoning
                self._desktop.notify(alert.rule.name, body)
        # "local" type = no-op (the MCP tool response IS the notification)

    async def notify_scene_change(
        self,
        change_level: str,
        rule_names: list[str],
        frame_base64: str | None = None,
    ) -> bool:
        """Send scene-change ntfy notification (used by perception loop)."""
        topic = self._config.ntfy_topic
        if not topic:
            return False
        return await self._ntfy.notify_scene_change(
            topic,
            change_level,
            rule_names,
            frame_base64=frame_base64,
        )

    def notify_desktop(self, title: str, body: str) -> bool:
        """Direct desktop notification (used by perception loop)."""
        if self._desktop:
            return self._desktop.notify(title, body)
        return False

    async def close(self) -> None:
        """Clean up resources."""
        await self._ntfy.close()
        await self._openclaw.close()
        await self._telegram.close()
        await self._discord.close()
        await self._slack.close()
        await self._webhook.close()
