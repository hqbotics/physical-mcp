"""In-process async event bus for multi-subscriber fanout."""

from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("physical-mcp")

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class EventBus:
    """Topic-based event bus with subscribe/unsubscribe and async publish."""

    def __init__(self) -> None:
        self._subs: dict[str, dict[int, EventHandler]] = {}
        self._id_to_topic: dict[int, str] = {}
        self._id_gen = itertools.count(1)
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: EventHandler) -> int:
        """Subscribe handler to a topic. Returns subscription id."""
        sub_id = next(self._id_gen)
        with self._lock:
            topic_subs = self._subs.setdefault(topic, {})
            topic_subs[sub_id] = handler
            self._id_to_topic[sub_id] = topic
        return sub_id

    def unsubscribe(self, sub_id: int) -> bool:
        """Remove subscription by id. Returns True if removed."""
        with self._lock:
            topic = self._id_to_topic.pop(sub_id, "")
            if not topic:
                return False
            topic_subs = self._subs.get(topic)
            if not topic_subs:
                return False
            removed = topic_subs.pop(sub_id, None) is not None
            if not topic_subs:
                self._subs.pop(topic, None)
            return removed

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        """Publish event to all current subscribers of a topic."""
        with self._lock:
            handlers = list(self._subs.get(topic, {}).values())

        if not handlers:
            return

        async def _run(handler: EventHandler) -> None:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("EventBus handler failed for topic '%s'", topic)

        await asyncio.gather(*(_run(h) for h in handlers), return_exceptions=True)
