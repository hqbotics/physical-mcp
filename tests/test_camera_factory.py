"""Tests for the camera factory."""

import pytest

from physical_mcp.camera.factory import create_camera
from physical_mcp.camera.usb import USBCamera
from physical_mcp.config import CameraConfig


class TestCameraFactory:
    def test_create_usb_camera(self):
        """USB type creates USBCamera instance."""
        config = CameraConfig(type="usb", device_index=0, width=640, height=480)
        camera = create_camera(config)
        assert isinstance(camera, USBCamera)

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
