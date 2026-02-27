"""Tests for the perception loop — the core camera monitoring pipeline."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from physical_mcp.camera.base import Frame
from physical_mcp.camera.buffer import FrameBuffer
from physical_mcp.perception.change_detector import ChangeDetector
from physical_mcp.perception.frame_sampler import FrameSampler
from physical_mcp.perception.loop import _cam_label, _save_alert_frame, perception_loop
from physical_mcp.perception.scene_state import SceneState
from physical_mcp.reasoning.analyzer import FrameAnalyzer
from physical_mcp.rules.engine import RulesEngine
from physical_mcp.rules.models import (
    NotificationTarget,
    RulePriority,
    WatchRule,
)
from physical_mcp.stats import StatsTracker
from physical_mcp.alert_queue import AlertQueue


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


def _make_rule(
    id: str = "r_test",
    name: str = "Person Detector",
    condition: str = "a person is visible",
) -> WatchRule:
    return WatchRule(
        id=id,
        name=name,
        condition=condition,
        priority=RulePriority.HIGH,
        notification=NotificationTarget(type="local"),
        cooldown_seconds=30,
    )


def _make_config():
    """Create a minimal config mock."""
    config = MagicMock()
    config.perception.capture_fps = 2
    config.perception.buffer_size = 100
    config.perception.change_detection.minor_threshold = 5
    config.perception.change_detection.moderate_threshold = 12
    config.perception.change_detection.major_threshold = 25
    config.perception.sampling.heartbeat_interval = 0
    config.perception.sampling.debounce_seconds = 0.5
    config.perception.sampling.cooldown_seconds = 3.0
    config.reasoning.image_quality = 60
    config.reasoning.max_thumbnail_dim = 480
    config.reasoning.llm_timeout_seconds = 30
    return config


# ── Unit tests for helpers ──────────────────────────────────


class TestCamLabel:
    """Tests for _cam_label helper."""

    def test_with_name_and_id(self):
        assert _cam_label("Kitchen", "usb:0") == "Kitchen (usb:0)"

    def test_with_only_id(self):
        assert _cam_label("", "usb:0") == "usb:0"

    def test_with_neither(self):
        assert _cam_label("", "") == "unknown"

    def test_with_only_name(self):
        assert _cam_label("Front Door", "") == "Front Door ()"


class TestSaveAlertFrame:
    """Tests for _save_alert_frame helper."""

    def test_saves_frame_to_disk(self, tmp_path):
        frame = _make_frame()
        with patch("physical_mcp.perception.loop._FRAME_PATH", tmp_path / "frame.jpg"):
            _save_alert_frame(frame, quality=50)
            assert (tmp_path / "frame.jpg").exists()
            assert (tmp_path / "frame.jpg").stat().st_size > 0

    def test_handles_error_gracefully(self):
        frame = _make_frame()
        # Write to impossible path
        with patch(
            "physical_mcp.perception.loop._FRAME_PATH",
            Path("/nonexistent/dir/frame.jpg"),
        ):
            # Should not raise
            _save_alert_frame(frame, quality=50)


# ── Integration tests for perception_loop ────────────────────


class TestPerceptionLoop:
    """Tests for the main perception_loop function."""

    @pytest.mark.asyncio
    async def test_loop_captures_frames(self):
        """Loop captures frames and pushes to buffer."""
        frame = _make_frame()
        camera = AsyncMock()
        camera.grab_frame = AsyncMock(return_value=frame)

        buf = FrameBuffer(max_frames=10)
        detector = ChangeDetector()
        sampler = FrameSampler(detector, heartbeat_interval=0)
        analyzer = FrameAnalyzer(provider=None)
        scene = SceneState()
        engine = RulesEngine()
        stats = StatsTracker()
        config = _make_config()
        alert_queue = AlertQueue()

        # Run loop for a brief time then cancel
        loop_task = asyncio.create_task(
            perception_loop(
                camera=camera,
                frame_buffer=buf,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene,
                rules_engine=engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                camera_id="usb:0",
                camera_name="Test",
            )
        )
        await asyncio.sleep(0.3)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Verify frames were captured
        assert camera.grab_frame.call_count >= 1
        assert await buf.size() >= 1

    @pytest.mark.asyncio
    async def test_loop_health_tracking(self):
        """Loop updates shared_state health dict."""
        frame = _make_frame()
        camera = AsyncMock()
        camera.grab_frame = AsyncMock(return_value=frame)

        shared_state: dict = {"camera_health": {}}
        buf = FrameBuffer(max_frames=10)
        detector = ChangeDetector()
        sampler = FrameSampler(detector, heartbeat_interval=0)
        analyzer = FrameAnalyzer(provider=None)
        scene = SceneState()
        engine = RulesEngine()
        stats = StatsTracker()
        config = _make_config()
        alert_queue = AlertQueue()

        loop_task = asyncio.create_task(
            perception_loop(
                camera=camera,
                frame_buffer=buf,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene,
                rules_engine=engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                shared_state=shared_state,
                camera_id="usb:0",
                camera_name="Test Cam",
            )
        )
        await asyncio.sleep(0.3)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        health = shared_state["camera_health"]["usb:0"]
        assert health["camera_id"] == "usb:0"
        assert health["camera_name"] == "Test Cam"
        assert health["status"] == "running"
        assert health["last_frame_at"] is not None

    @pytest.mark.asyncio
    async def test_loop_no_rules_no_api_calls(self):
        """With no rules, analyzer is never called."""
        frame = _make_frame()
        camera = AsyncMock()
        camera.grab_frame = AsyncMock(return_value=frame)

        mock_provider = AsyncMock()
        analyzer = FrameAnalyzer(provider=mock_provider)

        buf = FrameBuffer(max_frames=10)
        detector = ChangeDetector()
        sampler = FrameSampler(detector, heartbeat_interval=0)
        scene = SceneState()
        engine = RulesEngine()  # No rules
        stats = StatsTracker()
        config = _make_config()
        alert_queue = AlertQueue()

        loop_task = asyncio.create_task(
            perception_loop(
                camera=camera,
                frame_buffer=buf,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene,
                rules_engine=engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                camera_id="usb:0",
            )
        )
        await asyncio.sleep(0.3)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # No rules → no API calls
        mock_provider.analyze_images_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_handles_camera_error(self):
        """Loop survives camera grab_frame errors."""
        call_count = 0

        async def flaky_grab():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("Camera disconnected")
            return _make_frame(seq=call_count)

        camera = AsyncMock()
        camera.grab_frame = flaky_grab

        buf = FrameBuffer(max_frames=10)
        detector = ChangeDetector()
        sampler = FrameSampler(detector, heartbeat_interval=0)
        analyzer = FrameAnalyzer(provider=None)
        scene = SceneState()
        engine = RulesEngine()
        stats = StatsTracker()
        config = _make_config()
        alert_queue = AlertQueue()

        loop_task = asyncio.create_task(
            perception_loop(
                camera=camera,
                frame_buffer=buf,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene,
                rules_engine=engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                camera_id="usb:0",
            )
        )
        await asyncio.sleep(2.0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Loop survived errors and eventually captured frames
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_loop_server_mode_with_rules(self):
        """With rules + provider, analyzer.analyze_and_evaluate is called."""
        frame = _make_frame()
        camera = AsyncMock()
        camera.grab_frame = AsyncMock(return_value=frame)

        # Mock analyzer that returns scene data + no triggered rules
        analyzer = MagicMock()
        analyzer.has_provider = True
        analyzer.analyze_and_evaluate = AsyncMock(
            return_value={
                "scene": {
                    "summary": "A desk with a laptop",
                    "objects": ["desk", "laptop"],
                    "people_count": 0,
                },
                "evaluations": [],
            }
        )

        buf = FrameBuffer(max_frames=100)
        detector = ChangeDetector()
        # Low cooldown + debounce for fast testing
        sampler = FrameSampler(
            detector, heartbeat_interval=0, debounce_seconds=0.0, cooldown_seconds=0.0
        )
        scene = SceneState()
        engine = RulesEngine()
        engine.add_rule(_make_rule())
        stats = StatsTracker()
        config = _make_config()
        alert_queue = AlertQueue()
        shared_state: dict = {}

        loop_task = asyncio.create_task(
            perception_loop(
                camera=camera,
                frame_buffer=buf,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene,
                rules_engine=engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                shared_state=shared_state,
                camera_id="usb:0",
                camera_name="Test",
            )
        )
        await asyncio.sleep(0.8)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Analyzer should have been called at least once (first frame always triggers)
        assert analyzer.analyze_and_evaluate.call_count >= 1

    @pytest.mark.asyncio
    async def test_loop_error_backoff(self):
        """Analyzer errors trigger exponential backoff in health dict."""
        frame = _make_frame()
        camera = AsyncMock()
        camera.grab_frame = AsyncMock(return_value=frame)

        analyzer = MagicMock()
        analyzer.has_provider = True
        analyzer.analyze_and_evaluate = AsyncMock(
            side_effect=RuntimeError("API rate limit")
        )

        buf = FrameBuffer(max_frames=100)
        detector = ChangeDetector()
        sampler = FrameSampler(
            detector, heartbeat_interval=0, debounce_seconds=0.0, cooldown_seconds=0.0
        )
        scene = SceneState()
        engine = RulesEngine()
        engine.add_rule(_make_rule())
        stats = StatsTracker()
        config = _make_config()
        alert_queue = AlertQueue()
        shared_state: dict = {"camera_health": {}}

        loop_task = asyncio.create_task(
            perception_loop(
                camera=camera,
                frame_buffer=buf,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene,
                rules_engine=engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                shared_state=shared_state,
                camera_id="usb:0",
                camera_name="Test",
            )
        )
        await asyncio.sleep(1.0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        health = shared_state["camera_health"]["usb:0"]
        assert health["consecutive_errors"] >= 1
        assert health["status"] in ("degraded", "backoff")
        assert "API rate limit" in health["last_error"]

    @pytest.mark.asyncio
    async def test_loop_updates_scene_on_analysis(self):
        """Successful analysis updates the scene state."""
        # Use frames with different content to trigger change detection
        frame1 = _make_frame(seq=0)
        frame2 = Frame(
            image=np.full((100, 100, 3), 128, dtype=np.uint8),
            timestamp=datetime.now(),
            source_id="test",
            sequence_number=1,
            resolution=(100, 100),
        )
        frames = [frame1, frame2]
        call_idx = 0

        async def grab():
            nonlocal call_idx
            f = frames[min(call_idx, len(frames) - 1)]
            call_idx += 1
            return f

        camera = AsyncMock()
        camera.grab_frame = grab

        analyzer = MagicMock()
        analyzer.has_provider = True
        analyzer.analyze_and_evaluate = AsyncMock(
            return_value={
                "scene": {
                    "summary": "Person at desk working",
                    "objects": ["person", "desk"],
                    "people_count": 1,
                },
                "evaluations": [],
            }
        )

        buf = FrameBuffer(max_frames=100)
        detector = ChangeDetector()
        sampler = FrameSampler(
            detector, heartbeat_interval=0, debounce_seconds=0.0, cooldown_seconds=0.0
        )
        scene = SceneState()
        engine = RulesEngine()
        engine.add_rule(_make_rule())
        stats = StatsTracker()
        config = _make_config()
        alert_queue = AlertQueue()

        loop_task = asyncio.create_task(
            perception_loop(
                camera=camera,
                frame_buffer=buf,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene,
                rules_engine=engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                camera_id="usb:0",
            )
        )
        await asyncio.sleep(0.8)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        if analyzer.analyze_and_evaluate.call_count > 0:
            assert scene.summary == "Person at desk working"
            assert scene.people_count == 1
