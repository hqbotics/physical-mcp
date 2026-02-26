"""Discord webhook notification delivery.

Sends alerts with camera frame photos to Discord channels via
incoming webhooks.  Supports rich embeds with priority-coded colors.

Setup:
1. In your Discord server → Settings → Integrations → Webhooks → New Webhook
2. Copy the webhook URL (looks like https://discord.com/api/webhooks/{id}/{token})
3. Set DISCORD_WEBHOOK_URL env var (or config.yaml)
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from ..rules.models import AlertEvent

logger = logging.getLogger("physical-mcp")

# Priority → Discord embed sidebar colour (decimal)
_PRIORITY_COLOR = {
    "low": 0x3498DB,  # blue
    "medium": 0xF1C40F,  # yellow
    "high": 0xE67E22,  # orange
    "critical": 0xE74C3C,  # red
}


class DiscordWebhookNotifier:
    """Push alerts with photos to Discord via incoming webhooks."""

    def __init__(self, default_webhook_url: str = ""):
        self._default_url = default_webhook_url
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _build_embed(self, alert: AlertEvent, has_image: bool) -> dict:
        """Build a Discord embed object."""
        priority = alert.rule.priority.value
        color = _PRIORITY_COLOR.get(priority, 0xF1C40F)

        description = alert.rule.custom_message or (
            f"{alert.evaluation.reasoning}\n\n"
            f"**Condition:** {alert.rule.condition}\n"
            f"**Confidence:** {alert.evaluation.confidence:.0%}"
        )

        embed: dict = {
            "title": alert.rule.name,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {
                "text": f"physical-mcp | {priority}",
            },
        }

        if has_image:
            embed["image"] = {"url": "attachment://camera.jpg"}

        return embed

    async def notify(self, alert: AlertEvent, webhook_url: str = "") -> bool:
        """Send alert to Discord.  Returns True on success."""
        url = webhook_url or self._default_url
        if not url:
            return False

        session = self._get_session()
        embed = self._build_embed(alert, has_image=bool(alert.frame_base64))

        try:
            if alert.frame_base64:
                # Multipart: payload_json + file attachment
                image_bytes = base64.b64decode(alert.frame_base64)
                form = aiohttp.FormData()
                form.add_field(
                    "payload_json",
                    json.dumps({"embeds": [embed]}),
                    content_type="application/json",
                )
                form.add_field(
                    "files[0]",
                    image_bytes,
                    filename="camera.jpg",
                    content_type="image/jpeg",
                )
                async with session.post(url, data=form) as resp:
                    ok = resp.status < 400
            else:
                # Simple JSON POST with embed
                payload = {"embeds": [embed]}
                async with session.post(url, json=payload) as resp:
                    ok = resp.status < 400

            if ok:
                logger.info(f"Discord alert sent: {alert.rule.name}")
            else:
                logger.warning(f"Discord webhook failed: HTTP {resp.status}")
            return ok

        except Exception as e:
            logger.warning(f"Discord error: {e}")
            return False

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
