"""HTTP POST webhook notification delivery."""

from __future__ import annotations

import logging
from typing import Optional

import aiohttp

from ..rules.models import AlertEvent

logger = logging.getLogger("physical-mcp")


class WebhookNotifier:
    """Fire-and-forget HTTP POST to a webhook URL.

    Uses aiohttp with a 5-second timeout. No retries — if the webhook
    is down, the alert is logged and dropped. Keep it simple for v1.
    """

    def __init__(self, default_url: str = ""):
        self._default_url = default_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def notify(self, alert: AlertEvent, url: str | None = None) -> bool:
        """POST alert data as JSON. Returns True on success."""
        target_url = url or self._default_url
        if not target_url:
            return False

        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=5)
            self._session = aiohttp.ClientSession(timeout=timeout)

        payload = {
            "event": "rule_triggered",
            "rule_id": alert.rule.id,
            "rule_name": alert.rule.name,
            "condition": alert.rule.condition,
            "priority": alert.rule.priority.value,
            "reasoning": alert.evaluation.reasoning,
            "confidence": alert.evaluation.confidence,
            "timestamp": alert.evaluation.timestamp.isoformat(),
            "scene_summary": alert.scene_summary,
            "custom_message": alert.rule.custom_message,
        }

        try:
            async with self._session.post(target_url, json=payload) as resp:
                if resp.status < 400:
                    logger.info(f"Webhook sent to {target_url}: {resp.status}")
                    return True
                else:
                    logger.warning(
                        f"Webhook failed: {target_url} returned {resp.status}"
                    )
                    return False
        except Exception as e:
            logger.warning(f"Webhook error: {target_url}: {e}")
            return False

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
