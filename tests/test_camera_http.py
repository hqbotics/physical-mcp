"""Tests for HTTP MJPEG camera backend."""

import pytest

from physical_mcp.camera.factory import create_camera
from physical_mcp.camera.http_mjpeg import HTTPCamera, _id_from_url
from physical_mcp.config import CameraConfig


class TestHTTPCamera:
    def test_requires_url(self):
        with pytest.raises(ValueError, match="HTTP camera URL is required"):
            HTTPCamera(url="")

    def test_source_id_from_url(self):
        cam = HTTPCamera(url="http://192.168.1.50:81/stream")
        assert cam.source_id == "http:192.168.1.50"

    def test_source_id_custom(self):
        cam = HTTPCamera(url="http://192.168.1.50/stream", camera_id="3d-printer")
        assert cam.source_id == "3d-printer"

    def test_is_open_before_open(self):
        cam = HTTPCamera(url="http://192.168.1.50/stream")
        assert cam.is_open() is False


class TestFactoryHTTP:
    def test_create_http_camera(self):
        config = CameraConfig(
            id="esp32-cam", type="http", url="http://192.168.1.50:81/stream"
        )
        camera = create_camera(config)
        assert isinstance(camera, HTTPCamera)
        assert camera.source_id == "esp32-cam"

    def test_http_requires_url(self):
        config = CameraConfig(type="http")
        with pytest.raises(ValueError, match="HTTP camera requires"):
            create_camera(config)

    def test_error_lists_all_types(self):
        config = CameraConfig(type="gopro")
        with pytest.raises(ValueError, match="usb, rtsp, http"):
            create_camera(config)


class TestIdFromUrl:
    def test_with_port(self):
        assert _id_from_url("http://192.168.1.50:81/stream") == "http:192.168.1.50"

    def test_without_port(self):
        assert _id_from_url("http://octopi.local/webcam") == "http:octopi.local"

    def test_with_credentials(self):
        assert (
            _id_from_url("http://admin:pass@192.168.1.50/video") == "http:192.168.1.50"
        )
