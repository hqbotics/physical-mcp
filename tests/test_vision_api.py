"""Tests for the HTTP Vision API."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from physical_mcp.perception.scene_state import SceneState
from physical_mcp.vision_api import create_vision_routes


def _make_state(with_frame: bool = True, with_scene: bool = True) -> dict:
    """Create a mock state dict matching the server's shared state."""
    state: dict = {
        "scene_states": {},
        "frame_buffers": {},
        "camera_configs": {},
    }

    if with_scene:
        scene = SceneState()
        scene.update(
            summary="Two people at a desk with laptops",
            objects=["laptop", "coffee cup", "monitor"],
            people_count=2,
            change_desc="Person sat down",
        )
        state["scene_states"]["usb:0"] = scene

    if with_frame:
        mock_frame = MagicMock()
        mock_frame.to_jpeg_bytes.return_value = b"\xff\xd8\xff\xe0fakejpeg"

        mock_buffer = AsyncMock()
        mock_buffer.latest.return_value = mock_frame
        state["frame_buffers"]["usb:0"] = mock_buffer

    if with_scene or with_frame:
        mock_cfg = MagicMock()
        mock_cfg.name = "Office"
        state["camera_configs"]["usb:0"] = mock_cfg

    return state


@pytest.fixture
def state_with_data():
    return _make_state(with_frame=True, with_scene=True)


@pytest.fixture
def empty_state():
    return _make_state(with_frame=False, with_scene=False)


@pytest_asyncio.fixture
async def client_with_data(state_with_data):
    app = create_vision_routes(state_with_data)
    async with TestClient(TestServer(app)) as client:
        yield client


@pytest_asyncio.fixture
async def client_empty(empty_state):
    app = create_vision_routes(empty_state)
    async with TestClient(TestServer(app)) as client:
        yield client


# ── Index endpoint ────────────────────────────────────────────


class TestIndex:
    @pytest.mark.asyncio
    async def test_returns_api_overview(self, client_with_data):
        resp = await client_with_data.get("/")
        assert resp.status == 200
        data = await resp.json()
        assert data["name"] == "physical-mcp"
        assert "cameras" in data
        assert "usb:0" in data["cameras"]
        assert "endpoints" in data

    @pytest.mark.asyncio
    async def test_empty_cameras(self, client_empty):
        resp = await client_empty.get("/")
        assert resp.status == 200
        data = await resp.json()
        assert data["cameras"] == []


# ── Frame endpoint ────────────────────────────────────────────


class TestFrame:
    @pytest.mark.asyncio
    async def test_returns_jpeg(self, client_with_data):
        resp = await client_with_data.get("/frame")
        assert resp.status == 200
        assert resp.content_type == "image/jpeg"
        body = await resp.read()
        assert body.startswith(b"\xff\xd8")

    @pytest.mark.asyncio
    async def test_specific_camera(self, client_with_data):
        resp = await client_with_data.get("/frame/usb:0")
        assert resp.status == 200
        assert resp.content_type == "image/jpeg"

    @pytest.mark.asyncio
    async def test_unknown_camera_404(self, client_with_data):
        resp = await client_with_data.get("/frame/usb:99")
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_no_cameras_503(self, client_empty):
        resp = await client_empty.get("/frame")
        assert resp.status == 503

    @pytest.mark.asyncio
    async def test_no_frame_503(self, state_with_data):
        """Buffer exists but has no frame yet."""
        mock_buffer = AsyncMock()
        mock_buffer.latest.return_value = None
        state_with_data["frame_buffers"]["usb:0"] = mock_buffer

        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/frame")
            assert resp.status == 503


# ── Scene endpoint ────────────────────────────────────────────


class TestScene:
    @pytest.mark.asyncio
    async def test_returns_scene_json(self, client_with_data):
        resp = await client_with_data.get("/scene")
        assert resp.status == 200
        data = await resp.json()
        assert "cameras" in data
        assert "timestamp" in data
        cam = data["cameras"]["usb:0"]
        assert cam["summary"] == "Two people at a desk with laptops"
        assert cam["people_count"] == 2
        assert "laptop" in cam["objects_present"]
        assert cam["name"] == "Office"

    @pytest.mark.asyncio
    async def test_specific_camera(self, client_with_data):
        resp = await client_with_data.get("/scene/usb:0")
        assert resp.status == 200
        data = await resp.json()
        assert data["summary"] == "Two people at a desk with laptops"
        assert data["name"] == "Office"

    @pytest.mark.asyncio
    async def test_unknown_camera_404(self, client_with_data):
        resp = await client_with_data.get("/scene/usb:99")
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_empty_scene(self, client_empty):
        resp = await client_empty.get("/scene")
        assert resp.status == 200
        data = await resp.json()
        assert data["cameras"] == {}


# ── Changes endpoint ──────────────────────────────────────────


class TestChanges:
    @pytest.mark.asyncio
    async def test_returns_changes(self, client_with_data):
        resp = await client_with_data.get("/changes")
        assert resp.status == 200
        data = await resp.json()
        assert "changes" in data
        assert "usb:0" in data["changes"]
        assert data["minutes"] == 5

    @pytest.mark.asyncio
    async def test_custom_minutes(self, client_with_data):
        resp = await client_with_data.get("/changes?minutes=10")
        assert resp.status == 200
        data = await resp.json()
        assert data["minutes"] == 10

    @pytest.mark.asyncio
    async def test_filter_by_camera(self, client_with_data):
        resp = await client_with_data.get("/changes?camera_id=usb:0")
        assert resp.status == 200
        data = await resp.json()
        assert "usb:0" in data["changes"]


# ── CORS ──────────────────────────────────────────────────────


class TestCORS:
    @pytest.mark.asyncio
    async def test_cors_headers(self, client_with_data):
        resp = await client_with_data.get("/scene")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    @pytest.mark.asyncio
    async def test_options_request(self, client_with_data):
        resp = await client_with_data.options("/scene")
        assert resp.status == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
