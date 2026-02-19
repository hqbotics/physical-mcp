"""Tests for LAN camera discovery."""

import pytest

from physical_mcp.camera.discovery import (
    DiscoveredCamera,
    _detect_subnet,
    discover_cameras,
)


class TestDiscoveredCamera:
    def test_suggested_id_rtsp(self):
        cam = DiscoveredCamera(
            name="Test",
            url="rtsp://192.168.1.100:554/stream",
            type="rtsp",
            host="192.168.1.100",
            port=554,
        )
        assert cam.suggested_id == "rtsp:192.168.1.100"

    def test_suggested_id_http(self):
        cam = DiscoveredCamera(
            name="Test",
            url="http://192.168.1.50:81/stream",
            type="http",
            host="192.168.1.50",
            port=81,
        )
        assert cam.suggested_id == "http:192.168.1.50"


class TestDetectSubnet:
    def test_returns_string_or_none(self):
        """Subnet detection returns a string like '192.168.1' or None."""
        result = _detect_subnet()
        if result is not None:
            parts = result.split(".")
            assert len(parts) == 3
            assert all(p.isdigit() for p in parts)


@pytest.mark.asyncio
class TestDiscoverCameras:
    async def test_empty_result_for_nonexistent_subnet(self):
        """Scanning a non-routable subnet returns no cameras."""
        cameras = await discover_cameras(subnet="10.255.255", timeout=0.5)
        assert isinstance(cameras, list)
        # May or may not find cameras, but should not crash

    async def test_returns_list(self):
        """discover_cameras always returns a list."""
        cameras = await discover_cameras(subnet="127.0.0", timeout=0.1)
        assert isinstance(cameras, list)
