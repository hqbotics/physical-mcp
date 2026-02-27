"""Tests for FrameBuffer async ring buffer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import numpy as np
import pytest

from physical_mcp.camera.base import Frame
from physical_mcp.camera.buffer import FrameBuffer


def _make_frame(seq: int = 0, ts: datetime | None = None) -> Frame:
    """Create a minimal test frame."""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    return Frame(
        image=image,
        timestamp=ts or datetime.now(),
        source_id="test",
        sequence_number=seq,
        resolution=(100, 100),
    )


class TestFrameBuffer:
    """FrameBuffer push/pop/query tests."""

    @pytest.mark.asyncio
    async def test_push_and_latest(self):
        """Push a frame, get it back via latest()."""
        buf = FrameBuffer(max_frames=10)
        frame = _make_frame(seq=1)
        await buf.push(frame)
        latest = await buf.latest()
        assert latest is not None
        assert latest.sequence_number == 1

    @pytest.mark.asyncio
    async def test_empty_buffer_latest(self):
        """latest() on empty buffer returns None."""
        buf = FrameBuffer(max_frames=10)
        assert await buf.latest() is None

    @pytest.mark.asyncio
    async def test_ring_buffer_maxlen(self):
        """Old frames are discarded when buffer is full."""
        buf = FrameBuffer(max_frames=3)
        for i in range(5):
            await buf.push(_make_frame(seq=i))
        assert await buf.size() == 3
        latest = await buf.latest()
        assert latest.sequence_number == 4  # Most recent

    @pytest.mark.asyncio
    async def test_get_frames_since(self):
        """get_frames_since filters by timestamp."""
        buf = FrameBuffer(max_frames=100)
        now = datetime.now()
        old = _make_frame(seq=0, ts=now - timedelta(seconds=10))
        recent1 = _make_frame(seq=1, ts=now - timedelta(seconds=2))
        recent2 = _make_frame(seq=2, ts=now)
        await buf.push(old)
        await buf.push(recent1)
        await buf.push(recent2)

        since = now - timedelta(seconds=5)
        frames = await buf.get_frames_since(since)
        assert len(frames) == 2
        assert frames[0].sequence_number == 1
        assert frames[1].sequence_number == 2

    @pytest.mark.asyncio
    async def test_get_frames_since_empty(self):
        """get_frames_since on empty buffer returns empty list."""
        buf = FrameBuffer(max_frames=10)
        frames = await buf.get_frames_since(datetime.now())
        assert frames == []

    @pytest.mark.asyncio
    async def test_get_sampled_fewer_than_count(self):
        """get_sampled returns all frames when buffer has fewer than count."""
        buf = FrameBuffer(max_frames=100)
        for i in range(3):
            await buf.push(_make_frame(seq=i))
        sampled = await buf.get_sampled(10)
        assert len(sampled) == 3

    @pytest.mark.asyncio
    async def test_get_sampled_even_spacing(self):
        """get_sampled returns evenly-spaced frames."""
        buf = FrameBuffer(max_frames=100)
        for i in range(10):
            await buf.push(_make_frame(seq=i))
        sampled = await buf.get_sampled(3)
        assert len(sampled) == 3
        # Should pick frames from beginning, middle, end-ish
        seqs = [f.sequence_number for f in sampled]
        assert seqs[0] < seqs[1] < seqs[2]

    @pytest.mark.asyncio
    async def test_size(self):
        """size() returns correct count."""
        buf = FrameBuffer(max_frames=100)
        assert await buf.size() == 0
        await buf.push(_make_frame(seq=0))
        await buf.push(_make_frame(seq=1))
        assert await buf.size() == 2

    @pytest.mark.asyncio
    async def test_clear(self):
        """clear() empties the buffer."""
        buf = FrameBuffer(max_frames=100)
        await buf.push(_make_frame(seq=0))
        await buf.push(_make_frame(seq=1))
        await buf.clear()
        assert await buf.size() == 0
        assert await buf.latest() is None

    @pytest.mark.asyncio
    async def test_wait_for_frame_timeout(self):
        """wait_for_frame returns latest after timeout when no new frame."""
        buf = FrameBuffer(max_frames=10)
        await buf.push(_make_frame(seq=42))
        # Short timeout — no new frame will arrive
        result = await buf.wait_for_frame(timeout=0.1)
        assert result is not None
        assert result.sequence_number == 42

    @pytest.mark.asyncio
    async def test_wait_for_frame_empty_timeout(self):
        """wait_for_frame on empty buffer returns None after timeout."""
        buf = FrameBuffer(max_frames=10)
        result = await buf.wait_for_frame(timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_push(self):
        """Multiple concurrent pushes don't corrupt the buffer."""
        buf = FrameBuffer(max_frames=100)

        async def push_batch(start: int, count: int):
            for i in range(start, start + count):
                await buf.push(_make_frame(seq=i))

        await asyncio.gather(
            push_batch(0, 20),
            push_batch(100, 20),
            push_batch(200, 20),
        )
        assert await buf.size() == 60
