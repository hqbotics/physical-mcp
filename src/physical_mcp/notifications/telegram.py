"""Telegram Bot API notification delivery.

Sends alerts with camera frame photos directly to Telegram chats
via the Bot API.  Zero dependencies beyond aiohttp (already required).

Setup:
1. Message @BotFather on Telegram → /newbot → copy the token
2. Send any message to your bot, then visit:
   https://api.telegram.org/bot<TOKEN>/getUpdates
   to find your chat_id
3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars (or config.yaml)
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import aiohttp

from ..rules.models import AlertEvent

logger = logging.getLogger("physical-mcp")


class TelegramNotifier:
    """Push alerts with photos to Telegram via Bot API."""

    def __init__(
        self,
        bot_token: str = "",
        default_chat_id: str = "",
    ):
        self._bot_token = bot_token
        self._default_chat_id = default_chat_id
        self._api_base = "https://api.telegram.org"
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _format_message(self, alert: AlertEvent) -> str:
        """Format alert into Telegram Markdown message."""
        if alert.rule.custom_message:
            return alert.rule.custom_message

        priority_emoji = {
            "low": "\u2139\ufe0f",
            "medium": "\u26a0\ufe0f",
            "high": "\ud83d\udea8",
            "critical": "\ud83d\udd34",
        }
        emoji = priority_emoji.get(alert.rule.priority.value, "\u26a0\ufe0f")

        return (
            f"{emoji} *{alert.rule.name}*\n\n"
            f"{alert.evaluation.reasoning}\n\n"
            f"_Condition:_ {alert.rule.condition}\n"
            f"_Confidence:_ {alert.evaluation.confidence:.0%}"
        )

    async def notify(self, alert: AlertEvent, chat_id: str = "") -> bool:
        """Send alert to Telegram.  Returns True on success."""
        target_chat = chat_id or self._default_chat_id
        if not self._bot_token or not target_chat:
            return False

        message = self._format_message(alert)
        session = self._get_session()

        try:
            if alert.frame_base64:
                # sendPhoto with multipart form — image + caption
                url = f"{self._api_base}/bot{self._bot_token}/sendPhoto"
                image_bytes = base64.b64decode(alert.frame_base64)
                form = aiohttp.FormData()
                form.add_field("chat_id", target_chat)
                form.add_field("caption", message)
                form.add_field("parse_mode", "Markdown")
                form.add_field(
                    "photo",
                    image_bytes,
                    filename="camera.jpg",
                    content_type="image/jpeg",
                )
                async with session.post(url, data=form) as resp:
                    ok = resp.status < 400
                    if not ok:
                        body = await resp.text()
                        logger.warning(
                            f"Telegram sendPhoto failed: HTTP {resp.status} — {body}"
                        )
            else:
                # sendMessage — text only
                url = f"{self._api_base}/bot{self._bot_token}/sendMessage"
                payload = {
                    "chat_id": target_chat,
                    "text": message,
                    "parse_mode": "Markdown",
                }
                async with session.post(url, json=payload) as resp:
                    ok = resp.status < 400
                    if not ok:
                        body = await resp.text()
                        logger.warning(
                            f"Telegram sendMessage failed: HTTP {resp.status} — {body}"
                        )

            if ok:
                logger.info(f"Telegram alert sent: {alert.rule.name}")
            return ok

        except Exception as e:
            logger.warning(f"Telegram error: {e}")
            return False

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
