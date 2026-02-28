"""Tests for the CloudCamera (pushed-frame camera for cloud relay)."""

from __future__ import annotations


import cv2
import numpy as np
import pytest

from physical_mcp.camera.cloud import CloudCamera
from physical_mcp.camera.factory import create_camera
from physical_mcp.config import CameraConfig
from physical_mcp.exceptions import CameraTimeoutError


def _make_jpeg(width: int = 640, height: int = 480, quality: int = 60) -> bytes:
    """Create a valid JPEG image as bytes."""
    img = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()


class TestCloudCameraInit:
    def test_default_construction(self):
        """CloudCamera can be created with defaults."""
        cam = CloudCamera()
        assert cam.source_id == "cloud:0"
        assert not cam.is_open()

    def test_custom_id(self):
        """CloudCamera uses the provided camera_id."""
        cam = CloudCamera(camera_id="cloud:living-room")
        assert cam.source_id == "cloud:living-room"

    def test_auth_token(self):
        """CloudCamera stores auth token for relay verification."""
        cam = CloudCamera(camera_id="cloud:0", auth_token="secret123")
        assert cam.verify_token("secret123")
        assert not cam.verify_token("wrong")

    def test_no_auth_token_allows_any(self):
        """Without auth token, any token is accepted."""
        cam = CloudCamera(camera_id="cloud:0")
        assert cam.verify_token("")
        assert cam.verify_token("anything")


class TestCloudCameraLifecycle:
    @pytest.mark.asyncio
    async def test_open_and_close(self):
        """Can open and close a cloud camera."""
        cam = CloudCamera(camera_id="cloud:0")
        assert not cam.is_open()
        await cam.open()
        assert cam.is_open()
        await cam.close()
        assert not cam.is_open()

    @pytest.mark.asyncio
    async def test_grab_before_push_raises(self):
        """grab_frame raises CameraTimeoutError when no frame pushed."""
        cam = CloudCamera(camera_id="cloud:0")
        await cam.open()
        with pytest.raises(CameraTimeoutError, match="No frame available"):
            await cam.grab_frame()
        await cam.close()


class TestCloudCameraPush:
    @pytest.mark.asyncio
    async def test_push_valid_jpeg(self):
        """push_frame accepts valid JPEG and returns a Frame."""
        cam = CloudCamera(camera_id="cloud:test")
        await cam.open()

        jpeg = _make_jpeg(320, 240)
        frame = cam.push_frame(jpeg)

        assert frame is not None
        assert frame.source_id == "cloud:test"
        assert frame.sequence_number == 1
        assert frame.resolution == (320, 240)
        assert frame.image.shape == (240, 320, 3)
        await cam.close()

    @pytest.mark.asyncio
    async def test_push_then_grab(self):
        """grab_frame returns the most recently pushed frame."""
        cam = CloudCamera(camera_id="cloud:test")
        await cam.open()

        jpeg = _make_jpeg(640, 480)
        cam.push_frame(jpeg)

        frame = await cam.grab_frame()
        assert frame is not None
        assert frame.resolution == (640, 480)
        await cam.close()

    @pytest.mark.asyncio
    async def test_push_multiple_keeps_latest(self):
        """Multiple pushes — grab_frame returns the latest."""
        cam = CloudCamera(camera_id="cloud:test")
        await cam.open()

        cam.push_frame(_make_jpeg(320, 240))
        cam.push_frame(_make_jpeg(640, 480))
        cam.push_frame(_make_jpeg(1280, 720))

        frame = await cam.grab_frame()
        assert frame.resolution == (1280, 720)
        assert frame.sequence_number == 3
        await cam.close()

    def test_push_invalid_jpeg_raises(self):
        """push_frame raises ValueError for non-JPEG data."""
        cam = CloudCamera(camera_id="cloud:test")
        cam._opened = True  # Skip open for unit test

        with pytest.raises(ValueError, match="Invalid JPEG"):
            cam.push_frame(b"not a jpeg image at all")

    def test_push_when_closed_raises(self):
        """push_frame raises ValueError when camera is not open."""
        cam = CloudCamera(camera_id="cloud:test")

        with pytest.raises(ValueError, match="not open"):
            cam.push_frame(_make_jpeg())

    @pytest.mark.asyncio
    async def test_push_frame_async(self):
        """push_frame_async works from async context."""
        cam = CloudCamera(camera_id="cloud:test")
        await cam.open()

        jpeg = _make_jpeg(320, 240)
        frame = await cam.push_frame_async(jpeg)

        assert frame.resolution == (320, 240)
        await cam.close()


class TestCloudCameraStats:
    @pytest.mark.asyncio
    async def test_stats_before_push(self):
        """Stats show zero state before any frames pushed."""
        cam = CloudCamera(camera_id="cloud:test")
        await cam.open()

        stats = cam.stats
        assert stats["total_pushed"] == 0
        assert stats["has_frame"] is False
        assert stats["last_push_age_seconds"] is None
        await cam.close()

    @pytest.mark.asyncio
    async def test_stats_after_push(self):
        """Stats update after pushing frames."""
        cam = CloudCamera(camera_id="cloud:test")
        await cam.open()

        cam.push_frame(_make_jpeg())
        cam.push_frame(_make_jpeg())

        stats = cam.stats
        assert stats["total_pushed"] == 2
        assert stats["has_frame"] is True
        assert stats["sequence"] == 2
        assert stats["last_push_age_seconds"] is not None
        assert stats["last_push_age_seconds"] < 5.0  # Just pushed
        await cam.close()


class TestCloudCameraFactory:
    def test_factory_creates_cloud_camera(self):
        """create_camera with type='cloud' returns CloudCamera."""
        config = CameraConfig(
            id="cloud:living-room",
            type="cloud",
            auth_token="tok123",
        )
        camera = create_camera(config)
        assert isinstance(camera, CloudCamera)
        assert camera.source_id == "cloud:living-room"
        assert camera.verify_token("tok123")

    def test_factory_error_includes_cloud(self):
        """Error message for unknown types mentions 'cloud'."""
        config = CameraConfig(type="gopro")
        with pytest.raises(ValueError, match="cloud"):
            create_camera(config)
