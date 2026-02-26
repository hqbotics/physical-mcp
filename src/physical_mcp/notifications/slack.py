"""Slack incoming webhook notification delivery.

Sends alerts to Slack channels via incoming webhook URLs.
Uses Block Kit for rich formatting.

Note: Slack incoming webhooks do NOT support file uploads — only
text and blocks.  To send images, a full Slack Bot Token with
files:write scope would be needed (future enhancement).

Setup:
1. In your Slack workspace → Apps → Incoming Webhooks → Add to Slack
2. Choose a channel, copy the webhook URL
3. Set SLACK_WEBHOOK_URL env var (or config.yaml)
"""

from __future__ import annotations

import logging
from typing import Optional

import aiohttp

from ..rules.models import AlertEvent

logger = logging.getLogger("physical-mcp")

# Priority → Slack emoji
_PRIORITY_EMOJI = {
    "low": ":information_source:",
    "medium": ":warning:",
    "high": ":rotating_light:",
    "critical": ":red_circle:",
}


class SlackWebhookNotifier:
    """Push alerts to Slack via incoming webhooks (text only)."""

    def __init__(self, default_webhook_url: str = ""):
        self._default_url = default_webhook_url
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _build_blocks(self, alert: AlertEvent) -> list[dict]:
        """Build Slack Block Kit blocks."""
        priority = alert.rule.priority.value
        emoji = _PRIORITY_EMOJI.get(priority, ":warning:")

        if alert.rule.custom_message:
            body = alert.rule.custom_message
        else:
            body = (
                f"{alert.evaluation.reasoning}\n\n"
                f"*Condition:* {alert.rule.condition}\n"
                f"*Confidence:* {alert.evaluation.confidence:.0%}"
            )

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{alert.rule.name}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} {body}",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"physical-mcp | {priority} priority",
                    }
                ],
            },
        ]

    async def notify(self, alert: AlertEvent, webhook_url: str = "") -> bool:
        """Send alert to Slack.  Returns True on success."""
        url = webhook_url or self._default_url
        if not url:
            return False

        session = self._get_session()
        blocks = self._build_blocks(alert)

        # Plain text fallback for clients that don't render blocks
        fallback = (
            alert.rule.custom_message
            or f"[{alert.rule.priority.value.upper()}] {alert.rule.name}: {alert.evaluation.reasoning}"
        )

        payload = {"blocks": blocks, "text": fallback}

        try:
            async with session.post(url, json=payload) as resp:
                ok = resp.status < 400

            if ok:
                logger.info(f"Slack alert sent: {alert.rule.name}")
            else:
                logger.warning(f"Slack webhook failed: HTTP {resp.status}")
            return ok

        except Exception as e:
            logger.warning(f"Slack error: {e}")
            return False

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
