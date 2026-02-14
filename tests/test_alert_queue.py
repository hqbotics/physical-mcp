"""Tests for the AlertQueue — bounded async queue for client-side reasoning."""

import asyncio
from datetime import datetime, timedelta

import pytest

from physical_mcp.alert_queue import AlertQueue
from physical_mcp.rules.models import PendingAlert


def _make_alert(
    alert_id: str = "pa_test1",
    change_level: str = "major",
    ttl_seconds: int = 300,
) -> PendingAlert:
    return PendingAlert(
        id=alert_id,
        timestamp=datetime.now(),
        change_level=change_level,
        change_description=f"Test change ({change_level})",
        frame_base64="dGVzdF9mcmFtZV9kYXRh",  # base64 of "test_frame_data"
        scene_context="A test scene",
        active_rules=[
            {"id": "r_test1", "name": "Test rule", "condition": "something happens", "priority": "medium"}
        ],
        expires_at=datetime.now() + timedelta(seconds=ttl_seconds),
    )


class TestAlertQueue:
    @pytest.mark.asyncio
    async def test_push_and_pop_all(self):
        """Basic push and drain."""
        q = AlertQueue(max_size=10)
        alert1 = _make_alert("pa_1")
        alert2 = _make_alert("pa_2")

        await q.push(alert1)
        await q.push(alert2)

        assert await q.size() == 2
        assert await q.has_pending() is True

        alerts = await q.pop_all()
        assert len(alerts) == 2
        assert alerts[0].id == "pa_1"
        assert alerts[1].id == "pa_2"

        # Queue is drained
        assert await q.size() == 0
        assert await q.has_pending() is False

    @pytest.mark.asyncio
    async def test_pop_all_returns_empty_when_no_alerts(self):
        q = AlertQueue()
        alerts = await q.pop_all()
        assert alerts == []
        assert await q.has_pending() is False

    @pytest.mark.asyncio
    async def test_bounded_size(self):
        """Queue should not exceed max_size."""
        q = AlertQueue(max_size=3)

        for i in range(5):
            await q.push(_make_alert(f"pa_{i}"))

        # Only last 3 should remain (deque maxlen)
        assert await q.size() == 3
        alerts = await q.pop_all()
        assert [a.id for a in alerts] == ["pa_2", "pa_3", "pa_4"]

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """Expired alerts should be pruned automatically."""
        q = AlertQueue(max_size=10, ttl_seconds=300)

        # Add an already-expired alert
        expired = PendingAlert(
            id="pa_expired",
            timestamp=datetime.now() - timedelta(seconds=600),
            change_level="major",
            change_description="Old change",
            frame_base64="b2xk",
            scene_context="Old scene",
            active_rules=[],
            expires_at=datetime.now() - timedelta(seconds=1),  # Already expired
        )
        # Push directly to the deque to bypass any push-time pruning
        q._queue.append(expired)

        # Add a fresh alert
        fresh = _make_alert("pa_fresh")
        await q.push(fresh)

        # Only the fresh one should survive pruning
        assert await q.size() == 1
        alerts = await q.pop_all()
        assert alerts[0].id == "pa_fresh"

    @pytest.mark.asyncio
    async def test_has_pending_without_consuming(self):
        """has_pending should not drain the queue."""
        q = AlertQueue()
        await q.push(_make_alert("pa_1"))

        assert await q.has_pending() is True
        assert await q.has_pending() is True  # Still there
        assert await q.size() == 1  # Still there

    @pytest.mark.asyncio
    async def test_pop_all_clears_queue(self):
        """pop_all should drain — subsequent pop_all returns empty."""
        q = AlertQueue()
        await q.push(_make_alert("pa_1"))
        await q.push(_make_alert("pa_2"))

        first = await q.pop_all()
        assert len(first) == 2

        second = await q.pop_all()
        assert len(second) == 0
