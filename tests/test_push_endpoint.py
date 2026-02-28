"""Tests for the push/frame and push/register API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from physical_mcp.camera.buffer import FrameBuffer
from physical_mcp.camera.cloud import CloudCamera
from physical_mcp.perception.scene_state import SceneState
from physical_mcp.vision_api import create_vision_routes


def _make_jpeg(width: int = 320, height: int = 240, quality: int = 60) -> bytes:
    """Create a valid JPEG image as bytes."""
    img = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()


def _make_cloud_state(
    camera_id: str = "cloud:test",
    auth_token: str = "test-token",
    with_pending_claim: bool = False,
) -> dict:
    """Create a mock state dict with a cloud camera."""
    cloud_cam = CloudCamera(camera_id=camera_id, auth_token=auth_token)
    cloud_cam._opened = True  # Skip async open

    frame_buffer = FrameBuffer(max_frames=10)

    state: dict = {
        "cameras": {camera_id: cloud_cam},
        "camera_configs": {
            camera_id: MagicMock(name="Test Cloud Camera"),
        },
        "frame_buffers": {camera_id: frame_buffer},
        "scene_states": {camera_id: SceneState()},
        "camera_health": {
            camera_id: {
                "camera_id": camera_id,
                "camera_name": "Test Cloud Camera",
                "consecutive_errors": 0,
                "backoff_until": None,
                "last_success_at": None,
                "last_error": "",
                "last_frame_at": None,
                "status": "waiting_for_frames",
            }
        },
        "config": MagicMock(
            vision_api=MagicMock(auth_token="", port=8090),
            perception=MagicMock(buffer_size=300),
        ),
        "_pending_claims": {},
        "_completed_claims": {},
    }

    if with_pending_claim:
        state["_pending_claims"]["AB3K7X"] = {
            "camera_id": "cloud:new-cam",
            "camera_name": "New Camera",
            "chat_id": "123456",
        }

    return state


@pytest_asyncio.fixture
async def client_cloud():
    state = _make_cloud_state()
    app = create_vision_routes(state)
    async with TestClient(TestServer(app)) as client:
        yield client


@pytest_asyncio.fixture
async def client_with_claim():
    state = _make_cloud_state(with_pending_claim=True)
    app = create_vision_routes(state)
    async with TestClient(TestServer(app)) as client:
        yield client, state


# ── Push Frame endpoint ────────────────────────────────


class TestPushFrame:
    @pytest.mark.asyncio
    async def test_push_valid_frame(self, client_cloud):
        """POST /push/frame/{camera_id} accepts JPEG and returns success."""
        jpeg = _make_jpeg()
        resp = await client_cloud.post(
            "/push/frame/cloud:test",
            data=jpeg,
            headers={
                "X-Camera-Token": "test-token",
                "Content-Type": "image/jpeg",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["camera_id"] == "cloud:test"
        assert data["sequence"] == 1
        assert data["resolution"] == [320, 240]

    @pytest.mark.asyncio
    async def test_push_increments_sequence(self, client_cloud):
        """Pushing multiple frames increments sequence number."""
        for i in range(3):
            resp = await client_cloud.post(
                "/push/frame/cloud:test",
                data=_make_jpeg(),
                headers={"X-Camera-Token": "test-token"},
            )
            data = await resp.json()
            assert data["sequence"] == i + 1

    @pytest.mark.asyncio
    async def test_push_unknown_camera_404(self, client_cloud):
        """POST to unknown camera returns 404."""
        resp = await client_cloud.post(
            "/push/frame/cloud:nonexistent",
            data=_make_jpeg(),
            headers={"X-Camera-Token": "test-token"},
        )
        assert resp.status == 404
        data = await resp.json()
        assert data["code"] == "camera_not_found"

    @pytest.mark.asyncio
    async def test_push_wrong_token_403(self, client_cloud):
        """Push with wrong token returns 403."""
        resp = await client_cloud.post(
            "/push/frame/cloud:test",
            data=_make_jpeg(),
            headers={"X-Camera-Token": "wrong-token"},
        )
        assert resp.status == 403
        data = await resp.json()
        assert data["code"] == "forbidden"

    @pytest.mark.asyncio
    async def test_push_empty_body_400(self, client_cloud):
        """Push with empty body returns 400."""
        resp = await client_cloud.post(
            "/push/frame/cloud:test",
            data=b"",
            headers={"X-Camera-Token": "test-token"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["code"] == "empty_body"

    @pytest.mark.asyncio
    async def test_push_invalid_jpeg_400(self, client_cloud):
        """Push with invalid image data returns 400."""
        resp = await client_cloud.post(
            "/push/frame/cloud:test",
            data=b"not-a-jpeg",
            headers={"X-Camera-Token": "test-token"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["code"] == "invalid_frame"

    @pytest.mark.asyncio
    async def test_push_updates_health(self, client_cloud):
        """Push frame updates camera health status."""
        resp = await client_cloud.post(
            "/push/frame/cloud:test",
            data=_make_jpeg(),
            headers={"X-Camera-Token": "test-token"},
        )
        assert resp.status == 200
        # Verify via health endpoint
        health_resp = await client_cloud.get("/health/cloud:test")
        assert health_resp.status == 200
        health_data = await health_resp.json()
        assert health_data["health"]["status"] == "running"

    @pytest.mark.asyncio
    async def test_push_to_non_cloud_camera_400(self):
        """Push to a USB camera returns 400."""
        # Create state with a USB camera mock
        mock_cam = MagicMock()
        mock_cam.__class__.__name__ = "USBCamera"
        state = {
            "cameras": {"usb:0": mock_cam},
            "frame_buffers": {},
            "scene_states": {},
            "camera_configs": {},
            "camera_health": {},
            "config": MagicMock(vision_api=MagicMock(auth_token="")),
        }
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/push/frame/usb:0",
                data=_make_jpeg(),
                headers={"X-Camera-Token": "tok"},
            )
            assert resp.status == 400
            data = await resp.json()
            assert data["code"] == "not_cloud_camera"


# ── Push Register endpoint ──────────────────────────────


class TestPushRegister:
    @pytest.mark.asyncio
    async def test_register_with_valid_claim(self, client_with_claim):
        """POST /push/register with valid claim code creates camera."""
        client, state = client_with_claim
        resp = await client.post(
            "/push/register",
            json={"claim_code": "AB3K7X"},
        )
        assert resp.status == 201
        data = await resp.json()
        assert "camera_id" in data
        assert "camera_token" in data
        assert "push_url" in data
        assert data["camera_id"] == "cloud:new-cam"
        assert data["push_url"].startswith("/push/frame/")

        # Claim code should be consumed
        assert "AB3K7X" not in state["_pending_claims"]
        # Camera should be registered
        assert data["camera_id"] in state["cameras"]

    @pytest.mark.asyncio
    async def test_register_invalid_claim_404(self, client_with_claim):
        """Invalid claim code returns 404."""
        client, _ = client_with_claim
        resp = await client.post(
            "/push/register",
            json={"claim_code": "WRONG1"},
        )
        assert resp.status == 404
        data = await resp.json()
        assert data["code"] == "invalid_code"

    @pytest.mark.asyncio
    async def test_register_missing_code_400(self, client_with_claim):
        """Missing claim_code returns 400."""
        client, _ = client_with_claim
        resp = await client.post(
            "/push/register",
            json={},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["code"] == "missing_code"

    @pytest.mark.asyncio
    async def test_register_case_insensitive(self, client_with_claim):
        """Claim codes are case-insensitive (normalized to uppercase)."""
        client, _ = client_with_claim
        resp = await client.post(
            "/push/register",
            json={"claim_code": "ab3k7x"},
        )
        assert resp.status == 201

    @pytest.mark.asyncio
    async def test_register_invalid_json_400(self, client_with_claim):
        """Non-JSON body returns 400."""
        client, _ = client_with_claim
        resp = await client.post(
            "/push/register",
            data=b"not json",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status == 400


# ── Cloud camera via POST /cameras ───────────────────────


class TestAddCloudCamera:
    @pytest.mark.asyncio
    async def test_add_cloud_camera_via_api(self):
        """POST /cameras with type=cloud creates a cloud camera."""
        state = {
            "cameras": {},
            "camera_configs": {},
            "frame_buffers": {},
            "scene_states": {},
            "camera_health": {},
            "config": MagicMock(
                vision_api=MagicMock(auth_token=""),
                perception=MagicMock(buffer_size=300),
            ),
        }
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/cameras",
                json={
                    "type": "cloud",
                    "id": "cloud:kitchen",
                    "name": "Kitchen Camera",
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["id"] == "cloud:kitchen"
            assert data["type"] == "cloud"
            assert "cloud:kitchen" in state["cameras"]
            assert isinstance(state["cameras"]["cloud:kitchen"], CloudCamera)
