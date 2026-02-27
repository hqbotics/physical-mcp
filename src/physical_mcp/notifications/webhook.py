"""Generic webhook notification delivery.

POSTs a structured JSON payload to any URL when an alert fires.
Use this as an escape hatch for integrations that don't have a
dedicated notifier (e.g. Home Assistant, IFTTT, custom servers).

Setup:
1. Set WEBHOOK_URL env var (or per-rule notification.url)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from ..rules.models import AlertEvent

logger = logging.getLogger("physical-mcp")


class WebhookNotifier:
    """POST structured JSON to any URL on alert."""

    def __init__(self, default_url: str = ""):
        self._default_url = default_url
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _build_payload(self, alert: AlertEvent) -> dict:
        """Build a structured JSON payload."""
        payload: dict = {
            "event": "watch_rule_triggered",
            "rule_name": alert.rule.name,
            "rule_id": alert.rule.id,
            "condition": alert.rule.condition,
            "reasoning": alert.evaluation.reasoning,
            "confidence": alert.evaluation.confidence,
            "priority": alert.rule.priority.value,
            "scene_summary": alert.scene_summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if alert.rule.custom_message:
            payload["custom_message"] = alert.rule.custom_message

        if alert.frame_base64:
            payload["image_base64"] = alert.frame_base64

        return payload

    async def notify(self, alert: AlertEvent, url: str = "") -> bool:
        """POST alert JSON to webhook URL.  Returns True on success."""
        target_url = url or self._default_url
        if not target_url:
            return False

        session = self._get_session()
        payload = self._build_payload(alert)

        try:
            async with session.post(target_url, json=payload) as resp:
                ok = resp.status < 400

            if ok:
                logger.info(f"Webhook alert sent: {alert.rule.name} → {target_url}")
            else:
                logger.warning(f"Webhook failed: HTTP {resp.status} → {target_url}")
            return ok

        except Exception as e:
            logger.warning(f"Webhook error: {e}")
            return False

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
