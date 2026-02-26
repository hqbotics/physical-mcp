"""Bounded alert queue for client-side reasoning mode.

When no server-side vision provider is configured, the perception loop
queues PendingAlert objects here. The check_camera_alerts() MCP tool
drains the queue, returning frames as ImageContent for the MCP client
(Claude Desktop, ChatGPT, etc.) to visually analyze.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime

from .rules.models import PendingAlert


class AlertQueue:
    """Thread-safe bounded queue for pending client-side alerts.

    Features:
    - Bounded size (prevents memory bloat if client doesn't poll)
    - TTL-based expiration (old alerts auto-prune)
    - Drain semantics (pop_all clears queue, preventing duplicate processing)
    """

    def __init__(self, max_size: int = 50, ttl_seconds: int = 300):
        self._queue: deque[PendingAlert] = deque(maxlen=max_size)
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def push(self, alert: PendingAlert) -> None:
        """Add a pending alert to the queue."""
        async with self._lock:
            self._prune_expired()
            self._queue.append(alert)

    async def pop_all(self) -> list[PendingAlert]:
        """Drain and return all pending alerts. Called by check_camera_alerts."""
        async with self._lock:
            self._prune_expired()
            alerts = list(self._queue)
            self._queue.clear()
            return alerts

    async def has_pending(self) -> bool:
        """Check if any alerts are pending without consuming them."""
        async with self._lock:
            self._prune_expired()
            return len(self._queue) > 0

    async def size(self) -> int:
        """Current number of pending alerts."""
        async with self._lock:
            self._prune_expired()
            return len(self._queue)

    async def flush_rule(self, rule_id: str) -> int:
        """Remove pending alerts that reference a specific rule."""
        async with self._lock:
            before = len(self._queue)
            self._queue = deque(
                (
                    a
                    for a in self._queue
                    if not any(r.get("id") == rule_id for r in a.active_rules)
                ),
                maxlen=self._queue.maxlen,
            )
            return before - len(self._queue)

    def _prune_expired(self) -> None:
        """Remove alerts that have exceeded their TTL."""
        now = datetime.now()
        while self._queue and self._queue[0].expires_at < now:
            self._queue.popleft()
