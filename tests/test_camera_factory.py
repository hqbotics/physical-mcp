"""Tests for the camera factory."""

import pytest

from physical_mcp.camera.factory import create_camera
from physical_mcp.camera.rtsp import RTSPCamera
from physical_mcp.camera.usb import USBCamera
from physical_mcp.config import CameraConfig
from physical_mcp.exceptions import CameraConnectionError


class TestCameraFactory:
    def test_create_usb_camera(self):
        """USB type creates USBCamera instance."""
        config = CameraConfig(type="usb", device_index=0, width=640, height=480)
        camera = create_camera(config)
        assert isinstance(camera, USBCamera)

    def test_create_rtsp_camera(self):
        """RTSP type creates RTSPCamera instance."""
        config = CameraConfig(
            id="front-door",
            type="rtsp",
            url="rtsp://admin:pass@192.168.1.100:554/stream",
        )
        camera = create_camera(config)
        assert isinstance(camera, RTSPCamera)
        assert camera.source_id == "front-door"

    def test_create_http_camera(self):
        """HTTP type also creates RTSPCamera (OpenCV handles both)."""
        config = CameraConfig(
            id="garage",
            type="http",
            url="http://192.168.1.101:8080/video",
        )
        camera = create_camera(config)
        assert isinstance(camera, RTSPCamera)

    def test_rtsp_no_url_raises(self):
        """RTSP camera without URL raises CameraConnectionError."""
        config = CameraConfig(type="rtsp")
        with pytest.raises(CameraConnectionError, match="URL is required"):
            create_camera(config)

    def test_unknown_type_raises(self):
        """Unknown camera type raises ValueError."""
        config = CameraConfig(type="gopro", device_index=0)
        with pytest.raises(ValueError, match="Unknown camera type"):
            create_camera(config)

    def test_default_config_creates_usb(self):
        """Default CameraConfig creates USB camera."""
        config = CameraConfig()
        camera = create_camera(config)
        assert isinstance(camera, USBCamera)

    def test_error_message_lists_supported_types(self):
        """Error message includes supported types."""
        config = CameraConfig(type="gopro")
        with pytest.raises(ValueError, match="usb"):
            create_camera(config)


class TestRTSPCamera:
    def test_password_masking(self):
        """Safe URL masks password in logs."""
        cam = RTSPCamera(
            url="rtsp://admin:secretpass@192.168.1.100:554/stream",
            camera_id="test",
        )
        assert "secretpass" not in cam._safe_url
        assert "admin:***@" in cam._safe_url

    def test_url_without_auth_unchanged(self):
        """URL without credentials is returned as-is."""
        cam = RTSPCamera(
            url="rtsp://192.168.1.100:554/stream",
            camera_id="test",
        )
        assert cam._safe_url == "rtsp://192.168.1.100:554/stream"

    def test_source_id(self):
        """source_id matches the configured camera_id."""
        cam = RTSPCamera(url="rtsp://host/stream", camera_id="kitchen")
        assert cam.source_id == "kitchen"
