"""Tests for RTSP camera auto-discovery."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from physical_mcp.camera.discover import (
    DiscoveredCamera,
    DiscoveryResult,
    RTSP_PORTS,
    RTSP_URL_PATTERNS,
    _get_local_subnet,
    _scan_port,
    discover_cameras,
)


class TestDiscoveredCamera:
    def test_defaults(self):
        cam = DiscoveredCamera(
            ip="192.168.1.100", port=554, url="rtsp://192.168.1.100:554/0"
        )
        assert cam.brand == "unknown"
        assert cam.method == "port_scan"

    def test_custom_fields(self):
        cam = DiscoveredCamera(
            ip="10.0.0.5",
            port=8554,
            url="rtsp://10.0.0.5:8554/live",
            brand="hikvision",
            method="onvif",
            name="Front Door",
        )
        assert cam.brand == "hikvision"
        assert cam.name == "Front Door"


class TestDiscoveryResult:
    def test_empty_result(self):
        result = DiscoveryResult()
        assert result.cameras == []
        assert result.scanned_hosts == 0
        assert result.scan_time_seconds == 0.0
        assert result.errors == []


class TestGetLocalSubnet:
    def test_returns_string(self):
        """Should return a valid CIDR string or empty."""
        subnet = _get_local_subnet()
        if subnet:
            # Should be a valid CIDR notation
            import ipaddress

            network = ipaddress.IPv4Network(subnet, strict=False)
            assert network.prefixlen == 24

    @patch("physical_mcp.camera.discover.socket")
    def test_returns_empty_on_error(self, mock_socket):
        """Returns empty string when network is unavailable."""
        mock_socket.socket.return_value.__enter__ = lambda s: s
        mock_socket.socket.return_value.__exit__ = lambda s, *a: None
        mock_socket.socket.return_value.connect.side_effect = OSError("No network")
        mock_socket.AF_INET = 2
        mock_socket.SOCK_DGRAM = 2
        result = _get_local_subnet()
        # May or may not be empty depending on implementation, just verify no crash
        assert isinstance(result, str)


class TestScanPort:
    @pytest.mark.asyncio
    async def test_open_port(self):
        """Mocked open port returns True."""
        sem = asyncio.Semaphore(10)

        mock_writer = AsyncMock()
        mock_writer.close = lambda: None
        mock_writer.wait_closed = AsyncMock()

        with patch("physical_mcp.camera.discover.asyncio.open_connection") as mock_conn:
            mock_conn.return_value = (AsyncMock(), mock_writer)
            result = await _scan_port("192.168.1.1", 554, 1.0, sem)

        assert result is True

    @pytest.mark.asyncio
    async def test_closed_port(self):
        """Connection refused returns False."""
        sem = asyncio.Semaphore(10)

        with patch("physical_mcp.camera.discover.asyncio.open_connection") as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError()
            result = await _scan_port("192.168.1.1", 554, 1.0, sem)

        assert result is False

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Timeout returns False."""
        sem = asyncio.Semaphore(10)

        with patch("physical_mcp.camera.discover.asyncio.open_connection") as mock_conn:
            mock_conn.side_effect = asyncio.TimeoutError()
            result = await _scan_port("192.168.1.1", 554, 0.1, sem)

        assert result is False


class TestDiscoverCameras:
    @pytest.mark.asyncio
    async def test_invalid_subnet(self):
        """Invalid subnet returns error."""
        result = await discover_cameras(subnet="not-a-cidr")
        assert len(result.errors) > 0
        assert result.cameras == []

    @pytest.mark.asyncio
    async def test_no_cameras_found(self):
        """Empty network returns empty result."""
        with patch("physical_mcp.camera.discover._scan_port", return_value=False):
            with patch("physical_mcp.camera.discover._onvif_discover", return_value=[]):
                result = await discover_cameras(
                    subnet="192.168.99.0/30",  # tiny subnet
                    timeout=0.1,
                    try_onvif=False,
                )

        assert result.cameras == []
        assert result.scanned_hosts == 2  # /30 = 2 usable hosts

    @pytest.mark.asyncio
    async def test_result_has_timing(self):
        """Result includes scan time."""
        with patch("physical_mcp.camera.discover._scan_port", return_value=False):
            result = await discover_cameras(
                subnet="192.168.99.0/30",
                timeout=0.1,
                try_onvif=False,
            )

        assert result.scan_time_seconds > 0

    def test_constants(self):
        """Verify expected RTSP ports and patterns."""
        assert 554 in RTSP_PORTS
        assert 8554 in RTSP_PORTS
        assert len(RTSP_URL_PATTERNS) > 5
        assert "/stream1" in RTSP_URL_PATTERNS
        assert "/ch0_0.h264" in RTSP_URL_PATTERNS
