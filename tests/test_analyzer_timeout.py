"""Tests for FrameAnalyzer timeout behavior."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

import numpy as np
import pytest

from physical_mcp.camera.base import Frame
from physical_mcp.config import PhysicalMCPConfig
from physical_mcp.perception.scene_state import SceneState
from physical_mcp.reasoning.analyzer import FrameAnalyzer, LLM_CALL_TIMEOUT
from physical_mcp.reasoning.providers.base import VisionProvider


class SlowProvider(VisionProvider):
    """A provider that takes longer than the timeout."""

    async def analyze_image(self, image_b64: str, prompt: str) -> str:
        await asyncio.sleep(LLM_CALL_TIMEOUT + 5)
        return '{"summary": "should never get here"}'

    async def analyze_image_json(self, image_b64: str, prompt: str) -> dict:
        await asyncio.sleep(LLM_CALL_TIMEOUT + 5)
        return {"summary": "should never get here"}

    @property
    def provider_name(self) -> str:
        return "slow-test"

    @property
    def model_name(self) -> str:
        return "slow-v1"


class FastProvider(VisionProvider):
    """A provider that responds quickly."""

    async def analyze_image(self, image_b64: str, prompt: str) -> str:
        return '{"summary": "fast response", "objects": [], "people_count": 0}'

    async def analyze_image_json(self, image_b64: str, prompt: str) -> dict:
        return {"summary": "fast response", "objects": [], "people_count": 0}

    @property
    def provider_name(self) -> str:
        return "fast-test"

    @property
    def model_name(self) -> str:
        return "fast-v1"


def _make_frame() -> Frame:
    """Create a minimal test frame."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    return Frame(
        image=img,
        timestamp=datetime.now(),
        source_id="test",
        sequence_number=1,
        resolution=(100, 100),
    )


def _make_config() -> PhysicalMCPConfig:
    return PhysicalMCPConfig()


@pytest.mark.asyncio
class TestAnalyzerTimeout:
    async def test_timeout_returns_empty_summary(self):
        """Slow provider should be timed out, returning empty result."""
        analyzer = FrameAnalyzer(SlowProvider())
        frame = _make_frame()
        scene = SceneState()
        config = _make_config()

        # Use a very short timeout for the test
        with patch("physical_mcp.reasoning.analyzer.LLM_CALL_TIMEOUT", 0.1):
            result = await analyzer.analyze_scene(frame, scene, config)

        assert result["summary"] == ""
        assert result["objects"] == []

    async def test_fast_provider_works_normally(self):
        """Fast provider should return results normally."""
        analyzer = FrameAnalyzer(FastProvider())
        frame = _make_frame()
        scene = SceneState()
        config = _make_config()

        result = await analyzer.analyze_scene(frame, scene, config)
        assert result["summary"] == "fast response"

    async def test_timeout_constant_is_15_seconds(self):
        """Verify the default timeout is 15 seconds."""
        assert LLM_CALL_TIMEOUT == 15.0
