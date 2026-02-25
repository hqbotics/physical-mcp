"""Tests for CloudCamera — push-based camera backend.

CloudCamera receives JPEG frames via HTTP POST /ingest/{camera_id}
instead of pulling from hardware. This is the core of the cloud-hosted
architecture for consumer wireless cameras.
"""

import cv2
import numpy as np
import pytest

from physical_mcp.camera.cloud import CloudCamera, CloudCameraError
from physical_mcp.camera.factory import create_camera
from physical_mcp.config import CameraConfig


def _make_jpeg(width: int = 100, height: int = 80) -> bytes:
    """Create a valid JPEG from a random image."""
    image = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", image)
    return buf.tobytes()


class TestCloudCameraBasics:
    """Core CloudCamera functionality."""

    @pytest.mark.asyncio
    async def test_open_close(self):
        """CloudCamera opens and closes without hardware."""
        cam = CloudCamera(camera_id="test:1", name="Test Cam")
        assert not cam.is_open()
        await cam.open()
        assert cam.is_open()
        assert cam.source_id == "test:1"
        await cam.close()
        assert not cam.is_open()

    @pytest.mark.asyncio
    async def test_receive_and_grab_frame(self):
        """Push a JPEG → grab_frame returns it."""
        cam = CloudCamera(camera_id="test:1")
        await cam.open()

        jpeg = _make_jpeg(320, 240)
        frame = await cam.receive_frame(jpeg)

        assert frame is not None
        assert frame.source_id == "test:1"
        assert frame.resolution == (320, 240)
        assert frame.sequence_number == 1
        assert frame.image.shape == (240, 320, 3)

        # grab_frame should return the same frame
        grabbed = await cam.grab_frame()
        assert grabbed.sequence_number == 1

        await cam.close()

    @pytest.mark.asyncio
    async def test_multiple_frames_sequence(self):
        """Multiple pushed frames increment sequence number."""
        cam = CloudCamera(camera_id="test:1")
        await cam.open()

        for i in range(5):
            await cam.receive_frame(_make_jpeg())

        # grab_frame returns frames in FIFO order — first pushed = first grabbed
        frame1 = await cam.grab_frame()
        assert frame1.sequence_number == 1

        frame2 = await cam.grab_frame()
        assert frame2.sequence_number == 2

        frame5 = await cam.grab_frame()
        assert frame5.sequence_number == 3

        await cam.close()

    @pytest.mark.asyncio
    async def test_invalid_jpeg_raises(self):
        """Invalid JPEG data raises ValueError."""
        cam = CloudCamera(camera_id="test:1")
        await cam.open()

        with pytest.raises(ValueError, match="Invalid JPEG"):
            await cam.receive_frame(b"not a jpeg")

        await cam.close()

    @pytest.mark.asyncio
    async def test_empty_data_raises(self):
        """Empty bytes raises ValueError."""
        cam = CloudCamera(camera_id="test:1")
        await cam.open()

        with pytest.raises(ValueError, match="Invalid JPEG"):
            await cam.receive_frame(b"")

        await cam.close()


class TestCloudCameraTimeout:
    """Timeout and stale frame behavior."""

    @pytest.mark.asyncio
    async def test_grab_frame_timeout_returns_last(self):
        """On timeout, grab_frame returns the last received frame."""
        cam = CloudCamera(camera_id="test:1", grab_timeout=0.1)
        await cam.open()

        # Push one frame first
        await cam.receive_frame(_make_jpeg())
        first = await cam.grab_frame()
        assert first.sequence_number == 1

        # Now queue is empty — grab should timeout and return last frame
        stale = await cam.grab_frame()
        assert stale.sequence_number == 1  # Same frame returned

        await cam.close()

    @pytest.mark.asyncio
    async def test_grab_frame_no_frames_raises(self):
        """If no frame has ever been received, timeout raises."""
        cam = CloudCamera(camera_id="test:1", grab_timeout=0.1)
        await cam.open()

        with pytest.raises(CloudCameraError, match="No frames received"):
            await cam.grab_frame()

        await cam.close()


class TestCloudCameraQueue:
    """Queue overflow behavior."""

    @pytest.mark.asyncio
    async def test_queue_overflow_drops_oldest(self):
        """When queue is full, oldest frame is dropped."""
        cam = CloudCamera(camera_id="test:1", queue_size=3)
        await cam.open()

        # Push 5 frames into queue of size 3
        for i in range(5):
            await cam.receive_frame(_make_jpeg())

        # Queue should have frames 3, 4, 5 (dropped 1, 2)
        frame = await cam.grab_frame()
        assert frame.sequence_number >= 3

        await cam.close()


class TestCloudCameraAuth:
    """Per-camera token validation."""

    def test_validate_token_with_match(self):
        """Correct token validates."""
        cam = CloudCamera(camera_id="test:1", auth_token="secret123")
        assert cam.validate_token("secret123") is True

    def test_validate_token_with_mismatch(self):
        """Wrong token fails."""
        cam = CloudCamera(camera_id="test:1", auth_token="secret123")
        assert cam.validate_token("wrong") is False

    def test_validate_token_no_token_configured(self):
        """No auth_token configured → accept any token."""
        cam = CloudCamera(camera_id="test:1", auth_token="")
        assert cam.validate_token("anything") is True
        assert cam.validate_token("") is True

    def test_validate_token_empty_token_with_auth(self):
        """Empty token when auth is configured → reject."""
        cam = CloudCamera(camera_id="test:1", auth_token="secret123")
        assert cam.validate_token("") is False


class TestCloudCameraFactory:
    """Factory creates CloudCamera from config."""

    def test_factory_creates_cloud_camera(self):
        """create_camera with type='cloud' returns CloudCamera."""
        config = CameraConfig(
            id="cloud:front-door",
            name="Front Door",
            type="cloud",
            auth_token="sk_test123",
        )
        camera = create_camera(config)
        assert isinstance(camera, CloudCamera)
        assert camera.source_id == "cloud:front-door"
        assert camera.validate_token("sk_test123") is True

    def test_factory_cloud_no_url_needed(self):
        """Cloud cameras don't need a URL (unlike HTTP/RTSP)."""
        config = CameraConfig(
            id="cloud:kitchen",
            type="cloud",
        )
        # Should not raise
        camera = create_camera(config)
        assert isinstance(camera, CloudCamera)

    def test_config_auth_token_default_empty(self):
        """CameraConfig.auth_token defaults to empty string."""
        config = CameraConfig()
        assert config.auth_token == ""

    def test_config_cloud_camera_roundtrip(self):
        """Cloud camera config survives save/load."""
        import tempfile
        from physical_mcp.config import PhysicalMCPConfig, save_config, load_config

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name

        config = PhysicalMCPConfig(
            cameras=[
                CameraConfig(
                    id="cloud:front",
                    name="Front Door Cam",
                    type="cloud",
                    auth_token="sk_abc123",
                ),
            ]
        )
        save_config(config, path)
        loaded = load_config(path)

        assert len(loaded.cameras) == 1
        assert loaded.cameras[0].type == "cloud"
        assert loaded.cameras[0].auth_token == "sk_abc123"
        assert loaded.cameras[0].id == "cloud:front"
