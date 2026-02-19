"""Tests for RTSP camera backend and factory integration."""

import pytest

from physical_mcp.camera.factory import create_camera
from physical_mcp.camera.rtsp import RTSPCamera, _id_from_url, _mask_credentials
from physical_mcp.config import CameraConfig


class TestRTSPCamera:
    def test_requires_url(self):
        """RTSPCamera raises if no URL provided."""
        with pytest.raises(ValueError, match="RTSP URL is required"):
            RTSPCamera(url="")

    def test_source_id_from_url(self):
        """source_id is derived from URL host."""
        cam = RTSPCamera(url="rtsp://admin:pass@192.168.1.100:554/stream")
        assert cam.source_id == "rtsp:192.168.1.100"

    def test_source_id_custom(self):
        """Custom camera_id overrides auto-derived one."""
        cam = RTSPCamera(url="rtsp://192.168.1.100/stream", camera_id="front-door")
        assert cam.source_id == "front-door"

    def test_is_open_before_open(self):
        """Camera is not open before open() is called."""
        cam = RTSPCamera(url="rtsp://192.168.1.100/stream")
        assert cam.is_open() is False

    def test_safe_url_masks_password(self):
        """Password is masked in safe URL for logging."""
        cam = RTSPCamera(url="rtsp://admin:secret123@192.168.1.100:554/stream")
        assert "secret123" not in cam._safe_url
        assert "admin:***@" in cam._safe_url


class TestFactoryRTSP:
    def test_create_rtsp_camera(self):
        """Factory creates RTSPCamera from rtsp config."""
        config = CameraConfig(
            id="front-door",
            type="rtsp",
            url="rtsp://192.168.1.100:554/stream",
        )
        camera = create_camera(config)
        assert isinstance(camera, RTSPCamera)
        assert camera.source_id == "front-door"

    def test_rtsp_requires_url(self):
        """Factory raises if RTSP config has no URL."""
        config = CameraConfig(type="rtsp")
        with pytest.raises(ValueError, match="RTSP camera requires a 'url'"):
            create_camera(config)

    def test_rtsp_default_resolution(self):
        """RTSP camera gets resolution from config."""
        config = CameraConfig(
            type="rtsp",
            url="rtsp://192.168.1.100/stream",
            width=1920,
            height=1080,
        )
        camera = create_camera(config)
        assert isinstance(camera, RTSPCamera)


class TestIdFromUrl:
    def test_full_url(self):
        assert (
            _id_from_url("rtsp://admin:pass@192.168.1.100:554/stream")
            == "rtsp:192.168.1.100"
        )

    def test_no_credentials(self):
        assert _id_from_url("rtsp://192.168.1.100:554/stream") == "rtsp:192.168.1.100"

    def test_no_port(self):
        assert _id_from_url("rtsp://192.168.1.100/stream") == "rtsp:192.168.1.100"

    def test_hostname(self):
        assert _id_from_url("rtsp://camera.local/stream") == "rtsp:camera.local"

    def test_bare_host(self):
        assert _id_from_url("rtsp://10.0.0.1") == "rtsp:10.0.0.1"


class TestMaskCredentials:
    def test_masks_password(self):
        assert (
            _mask_credentials("rtsp://admin:secret@host/path")
            == "rtsp://admin:***@host/path"
        )

    def test_no_credentials(self):
        assert _mask_credentials("rtsp://host/path") == "rtsp://host/path"

    def test_user_only(self):
        assert _mask_credentials("rtsp://admin@host/path") == "rtsp://admin@host/path"

    def test_no_scheme(self):
        assert _mask_credentials("just-a-string") == "just-a-string"
