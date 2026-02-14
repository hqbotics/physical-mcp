"""ntfy.sh push notification delivery.

ntfy is a free, zero-signup push notification service.  Users install
the ntfy app on their phone, subscribe to a topic, and receive alerts
as push notifications — with camera frame images attached.

Works on: Android, iOS, web browser, desktop.
Docs: https://docs.ntfy.sh/
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import aiohttp

from ..rules.models import AlertEvent

logger = logging.getLogger("physical-mcp")

# physical-mcp priority → ntfy numeric priority
_NTFY_PRIORITY = {
    "low": "2",
    "medium": "3",
    "high": "4",
    "critical": "5",
}

# priority → ntfy emoji tags
_NTFY_TAGS = {
    "low": "camera",
    "medium": "camera,eyes",
    "high": "camera,warning",
    "critical": "camera,rotating_light",
}


class NtfyNotifier:
    """Push notifications via ntfy.sh (or self-hosted ntfy).

    Supports image attachments — when a camera frame is available,
    it's sent as a JPEG attachment so the user can SEE what triggered
    the alert on their phone.
    """

    def __init__(
        self,
        default_topic: str = "",
        server_url: str = "https://ntfy.sh",
    ):
        self._default_topic = default_topic
        self._server_url = server_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _send(
        self,
        url: str,
        message: str,
        headers: dict,
        frame_base64: str | None = None,
    ) -> bool:
        """Send notification — with image attachment if frame available."""
        session = self._get_session()
        try:
            if frame_base64:
                # PUT binary image body, text goes in X-Message header
                image_bytes = base64.b64decode(frame_base64)
                headers["Filename"] = "camera.jpg"
                headers["X-Message"] = message
                async with session.put(url, data=image_bytes, headers=headers) as resp:
                    ok = resp.status < 400
            else:
                # POST text body (no image)
                async with session.post(url, data=message.encode(), headers=headers) as resp:
                    ok = resp.status < 400

            if ok:
                logger.info(f"ntfy sent: {headers.get('Title', '?')}")
            else:
                logger.warning(f"ntfy failed: HTTP {resp.status}")
            return ok
        except Exception as e:
            logger.warning(f"ntfy error: {e}")
            return False

    async def notify(self, alert: AlertEvent, topic: str | None = None) -> bool:
        """Send a triggered-rule alert with optional camera frame."""
        target_topic = topic or self._default_topic
        if not target_topic:
            return False

        url = f"{self._server_url}/{target_topic}"
        priority = _NTFY_PRIORITY.get(alert.rule.priority.value, "3")

        headers = {
            "Title": alert.rule.name,
            "Priority": priority,
            "Tags": _NTFY_TAGS.get(alert.rule.priority.value, "camera"),
        }

        message = (
            f"{alert.evaluation.reasoning}\n\n"
            f"Condition: {alert.rule.condition}\n"
            f"Confidence: {alert.evaluation.confidence:.0%}"
        )

        return await self._send(
            url, message, headers, frame_base64=alert.frame_base64
        )

    async def notify_scene_change(
        self,
        topic: str,
        change_level: str,
        rule_names: list[str],
        frame_base64: str | None = None,
    ) -> bool:
        """Lightweight pre-evaluation notification: something changed."""
        if not topic:
            return False

        url = f"{self._server_url}/{topic}"
        headers = {
            "Title": f"Scene Change: {change_level.title()}",
            "Priority": "2",
            "Tags": "camera,mag",
        }
        message = (
            f"Monitoring: {', '.join(rule_names)}\n"
            f"Evaluating camera now..."
        )

        return await self._send(url, message, headers, frame_base64=frame_base64)

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
