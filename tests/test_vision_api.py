"""Tests for the HTTP Vision API."""

from __future__ import annotations

import asyncio
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
        "pending_cameras": {},  # Prevent loading stale data from disk
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
        mock_buffer.wait_for_frame.return_value = mock_frame
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

    @pytest.mark.asyncio
    async def test_invalid_quality_does_not_crash(self, client_with_data):
        resp = await client_with_data.get("/frame?quality=not-a-number")
        assert resp.status == 200
        assert resp.content_type == "image/jpeg"


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
    async def test_invalid_minutes_uses_default(self, client_with_data):
        resp = await client_with_data.get("/changes?minutes=abc")
        assert resp.status == 200
        data = await resp.json()
        assert data["minutes"] == 5

    @pytest.mark.asyncio
    async def test_filter_by_camera(self, client_with_data):
        resp = await client_with_data.get("/changes?camera_id=usb:0")
        assert resp.status == 200
        data = await resp.json()
        assert "usb:0" in data["changes"]

    @pytest.mark.asyncio
    async def test_filter_by_camera_trims_spaces(self, client_with_data):
        resp = await client_with_data.get("/changes?camera_id=%20usb:0%20")
        assert resp.status == 200
        data = await resp.json()
        assert "usb:0" in data["changes"]
        assert len(data["changes"]) == 1


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


# ── MJPEG stream endpoint ────────────────────────────────────


class TestMJPEGStream:
    @pytest.mark.asyncio
    async def test_stream_returns_multipart(self, state_with_data):
        """Stream endpoint returns multipart content with JPEG frames."""
        # Set wait_for_frame to return frame then raise to stop loop
        mock_frame = MagicMock()
        mock_frame.to_jpeg_bytes.return_value = b"\xff\xd8\xff\xe0fakejpeg"

        call_count = 0

        async def _wait_for_frame(timeout=5.0):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                raise asyncio.CancelledError()
            return mock_frame

        state_with_data["frame_buffers"]["usb:0"].wait_for_frame = _wait_for_frame

        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/stream")
            assert resp.status == 200
            assert "multipart/x-mixed-replace" in resp.content_type
            body = await resp.read()
            assert b"--frame" in body
            assert b"\xff\xd8" in body

    @pytest.mark.asyncio
    async def test_stream_no_cameras_503(self, client_empty):
        resp = await client_empty.get("/stream")
        assert resp.status == 503

    @pytest.mark.asyncio
    async def test_stream_unknown_camera_404(self, state_with_data):
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/stream/usb:99")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_stream_specific_camera(self, state_with_data):
        """Stream from a specific camera ID."""
        call_count = 0
        mock_frame = MagicMock()
        mock_frame.to_jpeg_bytes.return_value = b"\xff\xd8\xff\xe0jpeg"

        async def _wait(timeout=5.0):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError()
            return mock_frame

        state_with_data["frame_buffers"]["usb:0"].wait_for_frame = _wait

        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/stream/usb:0")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_stream_sets_low_latency_headers(self, state_with_data):
        """Stream response carries anti-buffering headers for proxy/LAN clients."""

        call_count = 0
        mock_frame = MagicMock()
        mock_frame.to_jpeg_bytes.return_value = b"\xff\xd8\xff\xe0jpeg"

        async def _wait(timeout=5.0):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError()
            return mock_frame

        state_with_data["frame_buffers"]["usb:0"].wait_for_frame = _wait

        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/stream")
            assert resp.status == 200
            assert resp.headers.get("Pragma") == "no-cache"
            assert resp.headers.get("X-Accel-Buffering") == "no"

    @pytest.mark.asyncio
    async def test_stream_supports_three_concurrent_clients(self, state_with_data):
        """At least 3 simultaneous clients can receive MJPEG chunks."""

        mock_frame = MagicMock()
        mock_frame.to_jpeg_bytes.return_value = b"\xff\xd8\xff\xe0multi"

        async def _wait(timeout=5.0):
            await asyncio.sleep(0)
            return mock_frame

        state_with_data["frame_buffers"]["usb:0"].wait_for_frame = _wait

        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:

            async def _open_and_read() -> tuple[int, bytes]:
                resp = await client.get("/stream/usb:0?fps=5")
                body = await resp.content.read(256)
                await resp.release()
                return resp.status, body

            results = await asyncio.gather(
                _open_and_read(), _open_and_read(), _open_and_read()
            )
            for status, body in results:
                assert status == 200
                assert b"--frame" in body
                assert b"\xff\xd8" in body


# ── SSE events endpoint ──────────────────────────────────────


class TestSSEEvents:
    @pytest.mark.asyncio
    async def test_events_returns_sse(self, state_with_data):
        """Events endpoint returns text/event-stream with scene data."""

        # We need to make the SSE loop terminate after sending initial data
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            # Read with a short timeout — SSE is infinite
            resp = await client.get("/events")
            assert resp.status == 200
            assert resp.content_type == "text/event-stream"

            # Read first chunk (scene event + ping)
            chunk = await resp.content.read(4096)
            text = chunk.decode()
            assert "event: scene" in text
            assert "Two people at a desk with laptops" in text

    @pytest.mark.asyncio
    async def test_events_filter_by_camera(self, state_with_data):
        """Filter SSE events to a specific camera."""
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/events?camera_id=usb:0")
            assert resp.status == 200
            chunk = await resp.content.read(4096)
            text = chunk.decode()
            assert "usb:0" in text


# ── Long-poll changes endpoint ───────────────────────────────


class TestLongPollChanges:
    @pytest.mark.asyncio
    async def test_normal_changes_still_work(self, client_with_data):
        """Non-polling changes endpoint works as before."""
        resp = await client_with_data.get("/changes")
        assert resp.status == 200
        data = await resp.json()
        assert "changes" in data
        assert "timeout" not in data

    @pytest.mark.asyncio
    async def test_long_poll_timeout(self, state_with_data):
        """Long-poll returns timeout flag when no new changes arrive."""
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/changes?wait=true&timeout=1")
            assert resp.status == 200
            data = await resp.json()
            assert data.get("timeout") is True

    @pytest.mark.asyncio
    async def test_long_poll_returns_on_new_change(self, state_with_data):
        """Long-poll returns immediately when a new change is recorded."""
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            # Record a new change after a short delay
            async def add_change():
                await asyncio.sleep(0.3)
                state_with_data["scene_states"]["usb:0"].record_change(
                    "New person entered"
                )

            task = asyncio.create_task(add_change())
            resp = await client.get("/changes?wait=true&timeout=5")
            await task
            assert resp.status == 200
            data = await resp.json()
            # Should NOT have timeout since change arrived
            assert "timeout" not in data
            # Should contain the new change
            all_changes = []
            for cam_changes in data["changes"].values():
                all_changes.extend(cam_changes)
            descs = [c["description"] for c in all_changes]
            assert "New person entered" in descs

    @pytest.mark.asyncio
    async def test_since_filter(self, state_with_data):
        """The 'since' parameter filters changes by timestamp."""
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            # Use a future timestamp — should return no changes
            resp = await client.get("/changes?since=2099-01-01T00:00:00")
            assert resp.status == 200
            data = await resp.json()
            changes = data["changes"].get("usb:0", [])
            assert len(changes) == 0

    @pytest.mark.asyncio
    async def test_invalid_since_is_ignored(self, state_with_data):
        """Invalid since cursor should be ignored (fallback to unfiltered)."""
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp_all = await client.get("/changes")
            assert resp_all.status == 200
            data_all = await resp_all.json()

            resp_bad = await client.get("/changes?since=not-a-time")
            assert resp_bad.status == 200
            data_bad = await resp_bad.json()

            assert data_bad["changes"] == data_all["changes"]

    @pytest.mark.asyncio
    async def test_invalid_since_with_trimmed_camera_filter(self, state_with_data):
        """Invalid since should still apply normalized camera_id filtering."""
        second = SceneState()
        second.update(
            summary="Empty hallway",
            objects=["hallway"],
            people_count=0,
            change_desc="Lights turned off",
        )
        state_with_data["scene_states"]["usb:1"] = second

        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/changes?since=bad-cursor&camera_id=%20usb:0%20")
            assert resp.status == 200
            data = await resp.json()
            assert list(data["changes"].keys()) == ["usb:0"]


# ── Health + alerts replay endpoints ─────────────────────────


class TestHealthAndAlerts:
    @pytest.mark.asyncio
    async def test_health_all(self, state_with_data):
        state_with_data["camera_health"] = {
            "usb:0": {
                "camera_id": "usb:0",
                "camera_name": "Office",
                "consecutive_errors": 0,
                "backoff_until": None,
                "last_success_at": "2026-02-18T02:10:45",
                "last_error": "",
                "last_frame_at": "2026-02-18T02:10:46",
                "status": "running",
            }
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()
            assert "cameras" in data
            assert isinstance(data.get("timestamp"), float)
            assert data["cameras"]["usb:0"]["status"] == "running"
            assert data["cameras"]["usb:0"]["consecutive_errors"] == 0

    @pytest.mark.asyncio
    async def test_health_single_unknown(self, state_with_data):
        state_with_data["camera_health"] = {}
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/usb:9")
            assert resp.status == 200
            data = await resp.json()
            assert data["camera_id"] == "usb:9"
            health = data["health"]
            assert health["status"] == "unknown"
            assert health["camera_id"] == "usb:9"
            assert health["consecutive_errors"] == 0
            assert health["backoff_until"] is None
            assert health["last_success_at"] is None

    @pytest.mark.asyncio
    async def test_health_single_non_dict_row_falls_back_to_defaults(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": ["bad", "row"],
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/usb:0")
            assert resp.status == 200
            data = await resp.json()
            health = data["health"]
            assert health["camera_id"] == "usb:0"
            assert health["camera_name"] == "usb:0"
            assert health["status"] == "unknown"
            assert health["consecutive_errors"] == 0
            assert health["backoff_until"] is None
            assert health["last_success_at"] is None
            assert health["message"] == "No health data yet. Start monitoring first."

    @pytest.mark.asyncio
    async def test_health_single_malformed_row_contains_required_camera_health_keys(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": "malformed",
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/usb:0")
            assert resp.status == 200
            data = await resp.json()
            health = data["health"]
            required = {
                "camera_id",
                "camera_name",
                "consecutive_errors",
                "backoff_until",
                "last_success_at",
                "last_error",
                "last_frame_at",
                "status",
            }
            assert required.issubset(set(health.keys()))

    @pytest.mark.asyncio
    async def test_health_single_malformed_row_nullable_fields_remain_null(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": "malformed",
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/usb:0")
            assert resp.status == 200
            health = (await resp.json())["health"]
            assert health["backoff_until"] is None
            assert health["last_success_at"] is None
            assert health["last_frame_at"] is None
            assert health["last_error"] == ""

    @pytest.mark.asyncio
    async def test_health_single_partial_row_is_normalized(self, state_with_data):
        state_with_data["camera_health"] = {
            "usb:0": {
                "status": "degraded",
                "last_error": "provider timeout",
            }
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/usb:0")
            assert resp.status == 200
            data = await resp.json()
            health = data["health"]
            assert health["camera_id"] == "usb:0"
            assert health["camera_name"] == "usb:0"
            assert health["status"] == "degraded"
            assert health["last_error"] == "provider timeout"
            assert health["consecutive_errors"] == 0
            assert health["backoff_until"] is None
            assert health["last_success_at"] is None
            assert health["last_frame_at"] is None

    @pytest.mark.asyncio
    async def test_health_all_normalizes_empty_camera_name_to_camera_id(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": {
                "camera_id": "usb:0",
                "camera_name": "",
                "status": "running",
            }
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()
            health = data["cameras"]["usb:0"]
            assert health["camera_id"] == "usb:0"
            assert health["camera_name"] == "usb:0"
            assert health["status"] == "running"

    @pytest.mark.asyncio
    async def test_health_all_normalizes_missing_camera_id_to_map_key(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": {
                "camera_id": "",
                "camera_name": "Office",
                "status": "running",
            }
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()
            health = data["cameras"]["usb:0"]
            assert health["camera_id"] == "usb:0"
            assert health["camera_name"] == "Office"
            assert health["status"] == "running"

    @pytest.mark.asyncio
    async def test_health_all_non_dict_row_falls_back_to_defaults(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": "corrupted-row",
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()
            health = data["cameras"]["usb:0"]
            assert health["camera_id"] == "usb:0"
            assert health["camera_name"] == "usb:0"
            assert health["status"] == "unknown"
            assert health["consecutive_errors"] == 0
            assert health["backoff_until"] is None
            assert health["last_success_at"] is None

    @pytest.mark.asyncio
    async def test_health_all_normalization_matrix_unknown_empty_malformed(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": {
                "camera_id": "usb:0",
                "camera_name": "",
                "status": "running",
            },
            "usb:1": "legacy-corrupted-row",
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()

            # empty-name normalization
            h0 = data["cameras"]["usb:0"]
            assert h0["camera_id"] == "usb:0"
            assert h0["camera_name"] == "usb:0"
            assert h0["status"] == "running"

            # malformed-row normalization
            h1 = data["cameras"]["usb:1"]
            assert h1["camera_id"] == "usb:1"
            assert h1["camera_name"] == "usb:1"
            assert h1["status"] == "unknown"

            # unknown-camera single endpoint normalization
            resp_unknown = await client.get("/health/usb:9")
            assert resp_unknown.status == 200
            unknown = (await resp_unknown.json())["health"]
            assert unknown["camera_id"] == "usb:9"
            assert unknown["camera_name"] == "usb:9"
            assert unknown["status"] == "unknown"
            assert unknown["message"] == "No health data yet. Start monitoring first."

    @pytest.mark.asyncio
    async def test_health_all_rows_always_include_required_camera_health_keys(
        self, state_with_data
    ):
        state_with_data["camera_health"] = {
            "usb:0": {
                "camera_id": "",
                "camera_name": "",
                "status": "running",
            },
            "usb:1": "malformed",
            "usb:2": {
                "camera_id": "usb:2",
                "camera_name": "Lab",
                "consecutive_errors": 2,
                "backoff_until": "2026-02-18T02:35:00",
                "last_success_at": None,
                "last_error": "timeout",
                "last_frame_at": None,
                "status": "degraded",
            },
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()

            required = {
                "camera_id",
                "camera_name",
                "consecutive_errors",
                "backoff_until",
                "last_success_at",
                "last_error",
                "last_frame_at",
                "status",
            }
            for health in data["cameras"].values():
                assert required.issubset(set(health.keys()))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status,errors,backoff,last_error",
        [
            ("degraded", 4, "2026-02-18T02:35:00", "provider timeout"),
            ("running", 0, None, ""),
        ],
    )
    async def test_health_single_payload_matrix(
        self, state_with_data, status, errors, backoff, last_error
    ):
        state_with_data["camera_health"] = {
            "usb:0": {
                "camera_id": "usb:0",
                "camera_name": "Office",
                "consecutive_errors": errors,
                "backoff_until": backoff,
                "last_success_at": "2026-02-18T02:30:00",
                "last_error": last_error,
                "last_frame_at": "2026-02-18T02:34:10",
                "status": status,
            }
        }
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/usb:0")
            assert resp.status == 200
            data = await resp.json()
            health = data["health"]
            assert data["camera_id"] == "usb:0"
            assert health["status"] == status
            assert health["consecutive_errors"] == errors
            assert health["backoff_until"] == backoff
            assert health["last_success_at"]
            assert health["last_error"] == last_error

    @pytest.mark.asyncio
    async def test_alerts_replay_filters(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_aaa",
                "event_type": "watch_rule_triggered",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "r_1",
                "rule_name": "Door watch",
                "message": "Person detected",
                "timestamp": "2026-02-18T02:10:00",
            },
            {
                "event_id": "evt_bbb",
                "event_type": "provider_error",
                "camera_id": "usb:1",
                "camera_name": "Lab",
                "rule_id": "",
                "rule_name": "",
                "message": "Timeout",
                "timestamp": "2026-02-18T02:11:00",
            },
            {
                "event_id": "evt_ccc",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "Running in fallback mode",
                "timestamp": "2026-02-18T02:12:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?camera_id=usb:0&event_type=watch_rule_triggered"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_aaa"

            resp2 = await client.get("/alerts?event_type=startup_warning")
            assert resp2.status == 200
            data2 = await resp2.json()
            assert data2["count"] == 1
            startup_event = data2["events"][0]
            assert startup_event["event_id"] == "evt_ccc"
            assert startup_event["event_type"] == "startup_warning"
            assert "fallback mode" in startup_event["message"].lower()

            # invalid limit should fall back safely
            resp3 = await client.get("/alerts?limit=bad-value")
            assert resp3.status == 200
            data3 = await resp3.json()
            assert data3["count"] == 3

            # provider_error filter returns expected payload shape
            resp4 = await client.get("/alerts?event_type=provider_error")
            assert resp4.status == 200
            data4 = await resp4.json()
            assert data4["count"] == 1
            evt = data4["events"][0]
            assert evt["event_type"] == "provider_error"
            assert evt["camera_id"] == "usb:1"
            assert evt["message"] == "Timeout"


# ── JSON error contract ─────────────────────────────────────


class TestJsonErrorContract:
    @pytest.mark.asyncio
    async def test_frame_unknown_camera_error_shape(self, client_with_data):
        resp = await client_with_data.get("/frame/usb:99")
        assert resp.status == 404
        data = await resp.json()
        assert data["code"] == "camera_not_found"
        assert data["camera_id"] == "usb:99"

    @pytest.mark.asyncio
    async def test_scene_unknown_camera_error_shape(self, client_with_data):
        resp = await client_with_data.get("/scene/usb:99")
        assert resp.status == 404
        data = await resp.json()
        assert data["code"] == "camera_not_found"
        assert data["camera_id"] == "usb:99"


class TestAlertsSinceAndLimit:
    @pytest.mark.asyncio
    async def test_since_then_limit_returns_most_recent_filtered_events(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_001",
                "event_type": "watch_rule_triggered",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "r_1",
                "rule_name": "Door",
                "message": "old",
                "timestamp": "2026-02-18T02:10:00",
            },
            {
                "event_id": "evt_002",
                "event_type": "watch_rule_triggered",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "r_1",
                "rule_name": "Door",
                "message": "mid",
                "timestamp": "2026-02-18T02:11:00",
            },
            {
                "event_id": "evt_003",
                "event_type": "watch_rule_triggered",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "r_1",
                "rule_name": "Door",
                "message": "new",
                "timestamp": "2026-02-18T02:12:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?since=2026-02-18T02:10:30&limit=1")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_003"

    @pytest.mark.asyncio
    async def test_compound_filters_with_limit(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_010",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "timeout A",
                "timestamp": "2026-02-18T02:10:00",
            },
            {
                "event_id": "evt_011",
                "event_type": "provider_error",
                "camera_id": "usb:1",
                "camera_name": "Lab",
                "rule_id": "",
                "rule_name": "",
                "message": "timeout B",
                "timestamp": "2026-02-18T02:11:00",
            },
            {
                "event_id": "evt_012",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "timeout C",
                "timestamp": "2026-02-18T02:12:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_012"

            # case/spacing normalization in query filters
            resp2 = await client.get(
                "/alerts?camera_id=%20usb:0%20&event_type=PROVIDER_ERROR&limit=1"
            )
            assert resp2.status == 200
            data2 = await resp2.json()
            assert data2["count"] == 1
            assert data2["events"][0]["event_id"] == "evt_012"

    @pytest.mark.asyncio
    async def test_since_camera_event_and_limit_combined(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_020",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "old timeout",
                "timestamp": "2026-02-18T02:09:00",
            },
            {
                "event_id": "evt_021",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "mid timeout",
                "timestamp": "2026-02-18T02:11:00",
            },
            {
                "event_id": "evt_022",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "new timeout",
                "timestamp": "2026-02-18T02:12:30",
            },
            {
                "event_id": "evt_023",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "fallback",
                "timestamp": "2026-02-18T02:13:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T02:10:30&camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            evt = data["events"][0]
            assert evt["event_id"] == "evt_022"
            assert evt["event_type"] == "provider_error"
            assert evt["camera_id"] == "usb:0"

    @pytest.mark.asyncio
    async def test_since_in_future_returns_empty(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_100",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "fallback",
                "timestamp": "2026-02-18T02:12:00",
            }
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?since=2099-01-01T00:00:00")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 0
            assert data["events"] == []

    @pytest.mark.asyncio
    async def test_invalid_since_is_ignored(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_100",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "fallback",
                "timestamp": "2026-02-18T02:12:00",
            }
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?since=not-a-time")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_100"

    @pytest.mark.asyncio
    async def test_invalid_since_with_compound_filters_and_limit(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_200",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "old timeout",
                "timestamp": "2026-02-18T02:10:00",
            },
            {
                "event_id": "evt_201",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "new timeout",
                "timestamp": "2026-02-18T02:12:00",
            },
            {
                "event_id": "evt_202",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "fallback",
                "timestamp": "2026-02-18T02:13:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=bad-cursor&camera_id=%20usb:0%20&event_type=PROVIDER_ERROR&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_201"

    @pytest.mark.asyncio
    async def test_alerts_sorted_by_timestamp_then_event_id(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_300",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "latest",
                "timestamp": "2026-02-18T02:12:00",
            },
            {
                "event_id": "evt_100",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "same ts lower id",
                "timestamp": "2026-02-18T02:11:00",
            },
            {
                "event_id": "evt_200",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "same ts higher id",
                "timestamp": "2026-02-18T02:11:00",
            },
            {
                "event_id": "evt_050",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "earliest",
                "timestamp": "2026-02-18T02:10:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?event_type=provider_error")
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == [
                "evt_050",
                "evt_100",
                "evt_200",
                "evt_300",
            ]

            resp2 = await client.get("/alerts?event_type=provider_error&limit=2")
            assert resp2.status == 200
            data2 = await resp2.json()
            assert [e["event_id"] for e in data2["events"]] == ["evt_200", "evt_300"]

    @pytest.mark.asyncio
    async def test_since_boundary_is_exclusive(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_401",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "at boundary",
                "timestamp": "2026-02-18T02:11:00",
            },
            {
                "event_id": "evt_402",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "same second but later fraction",
                "timestamp": "2026-02-18T02:11:00.500000",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T02:11:00&event_type=provider_error"
            )
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == ["evt_402"]

    @pytest.mark.asyncio
    async def test_since_plus_limit_when_only_boundary_equal_events(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_500",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "boundary one",
                "timestamp": "2026-02-18T02:20:00",
            },
            {
                "event_id": "evt_501",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "boundary two",
                "timestamp": "2026-02-18T02:20:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T02:20:00&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 0
            assert data["events"] == []

    @pytest.mark.asyncio
    async def test_event_type_filter_matches_stored_uppercase_values(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_600",
                "event_type": "PROVIDER_ERROR",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "uppercase stored",
                "timestamp": "2026-02-18T02:30:00",
            }
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?event_type=provider_error")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_600"

    @pytest.mark.asyncio
    async def test_event_type_filter_trims_stored_values(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_700",
                "event_type": " provider_error ",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "whitespace stored",
                "timestamp": "2026-02-18T02:31:00",
            }
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?event_type=provider_error")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_700"

    @pytest.mark.asyncio
    async def test_camera_id_filter_trims_stored_values(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_710",
                "event_type": "provider_error",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "whitespace camera id",
                "timestamp": "2026-02-18T02:32:00",
            }
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?camera_id=usb:0")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_710"

    @pytest.mark.asyncio
    async def test_invalid_since_with_normalized_stored_fields_and_limit(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_801",
                "event_type": " PROVIDER_ERROR ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "older normalized row",
                "timestamp": "2026-02-18T02:40:00",
            },
            {
                "event_id": "evt_802",
                "event_type": " provider_error ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "newer normalized row",
                "timestamp": "2026-02-18T02:41:00",
            },
            {
                "event_id": "evt_803",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "non-matching",
                "timestamp": "2026-02-18T02:42:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=not-a-time&camera_id=%20usb:0%20&event_type=PROVIDER_ERROR&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_802"

    @pytest.mark.asyncio
    async def test_boundary_since_excludes_equal_with_normalized_stored_fields(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_811",
                "event_type": " PROVIDER_ERROR ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "boundary normalized row",
                "timestamp": "2026-02-18T02:45:00",
            },
            {
                "event_id": "evt_812",
                "event_type": " provider_error ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "later normalized row",
                "timestamp": "2026-02-18T02:45:00.250000",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T02:45:00&camera_id=%20usb:0%20&event_type=PROVIDER_ERROR"
            )
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == ["evt_812"]

    @pytest.mark.asyncio
    async def test_boundary_since_with_limit_one_normalized_fields(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_821",
                "event_type": " provider_error ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "boundary normalized row",
                "timestamp": "2026-02-18T02:50:00",
            },
            {
                "event_id": "evt_822",
                "event_type": " PROVIDER_ERROR ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "later normalized row A",
                "timestamp": "2026-02-18T02:50:00.100000",
            },
            {
                "event_id": "evt_823",
                "event_type": " provider_error ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "later normalized row B",
                "timestamp": "2026-02-18T02:50:00.200000",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T02:50:00&camera_id=%20usb:0%20&event_type=PROVIDER_ERROR&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_823"

    @pytest.mark.asyncio
    async def test_camera_alert_pending_eval_filter_normalized_and_limited(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_901",
                "event_type": " camera_alert_pending_eval ",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "pending eval older",
                "timestamp": "2026-02-18T03:10:00.100000",
            },
            {
                "event_id": "evt_902",
                "event_type": "CAMERA_ALERT_PENDING_EVAL",
                "camera_id": " usb:0 ",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "pending eval newer",
                "timestamp": "2026-02-18T03:10:00.200000",
            },
            {
                "event_id": "evt_903",
                "event_type": "watch_rule_triggered",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "r_1",
                "rule_name": "Door",
                "message": "person at door",
                "timestamp": "2026-02-18T03:10:00.300000",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?camera_id=%20usb:0%20&event_type=CAMERA_ALERT_PENDING_EVAL&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_902"
            assert data["events"][0]["event_type"] == "CAMERA_ALERT_PENDING_EVAL"

    @pytest.mark.asyncio
    async def test_malformed_timestamps_are_tolerated_and_sorted_deterministically(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_malformed_b",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "legacy malformed timestamp B",
                "timestamp": "not-a-time",
            },
            {
                "event_id": "evt_good_old",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "valid old",
                "timestamp": "2026-02-18T03:20:00",
            },
            {
                "event_id": "evt_malformed_a",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "legacy malformed timestamp A",
                "timestamp": "???",
            },
            {
                "event_id": "evt_good_new",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "valid new",
                "timestamp": "2026-02-18T03:21:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?event_type=provider_error")
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == [
                "evt_malformed_a",
                "evt_malformed_b",
                "evt_good_old",
                "evt_good_new",
            ]

    @pytest.mark.asyncio
    async def test_since_cursor_excludes_malformed_timestamps(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_bad_since",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "malformed row should be ignored by since cursor",
                "timestamp": "not-an-iso-time",
            },
            {
                "event_id": "evt_good_since",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "valid row after cursor",
                "timestamp": "2026-02-18T03:31:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T03:30:00&event_type=provider_error"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_good_since"

    @pytest.mark.asyncio
    async def test_since_cursor_accepts_z_timezone_and_skips_malformed(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_bad_z",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "legacy bad ts",
                "timestamp": "oops-not-time",
            },
            {
                "event_id": "evt_good_z_old",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "before cursor",
                "timestamp": "2026-02-18T03:29:00+00:00",
            },
            {
                "event_id": "evt_good_z_new",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "after cursor",
                "timestamp": "2026-02-18T03:31:00+00:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T03:30:00Z&event_type=provider_error"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_good_z_new"

    @pytest.mark.asyncio
    async def test_limit_with_mixed_timezone_rows_returns_newest_deterministically(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_tz_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "old aware",
                "timestamp": "2026-02-18T03:30:00+00:00",
            },
            {
                "event_id": "evt_tz_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "mid naive",
                "timestamp": "2026-02-18T03:30:30",
            },
            {
                "event_id": "evt_tz_3",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "new aware",
                "timestamp": "2026-02-18T03:31:00+00:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_tz_3"

    @pytest.mark.asyncio
    async def test_since_plus_limit_with_mixed_timezone_rows(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_mix_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "before cursor aware",
                "timestamp": "2026-02-18T03:29:00+00:00",
            },
            {
                "event_id": "evt_mix_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "after cursor naive",
                "timestamp": "2026-02-18T03:30:30",
            },
            {
                "event_id": "evt_mix_3",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "newest after cursor aware",
                "timestamp": "2026-02-18T03:31:00+00:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T03:30:00Z&camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_mix_3"

    @pytest.mark.asyncio
    async def test_boundary_equal_since_exclusive_with_mixed_timezone_rows(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_bmix_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "exact boundary aware",
                "timestamp": "2026-02-18T03:30:00+00:00",
            },
            {
                "event_id": "evt_bmix_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "exact boundary naive",
                "timestamp": "2026-02-18T03:30:00",
            },
            {
                "event_id": "evt_bmix_3",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "after boundary",
                "timestamp": "2026-02-18T03:30:00.100000",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T03:30:00Z&camera_id=usb:0&event_type=provider_error"
            )
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == ["evt_bmix_3"]

    @pytest.mark.asyncio
    async def test_invalid_since_with_mixed_timezones_and_limit_uses_unfiltered_cursor(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_ims_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "older aware",
                "timestamp": "2026-02-18T03:29:00+00:00",
            },
            {
                "event_id": "evt_ims_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "newer naive",
                "timestamp": "2026-02-18T03:31:00",
            },
            {
                "event_id": "evt_ims_3",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "non matching type",
                "timestamp": "2026-02-18T03:32:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=bad-cursor&camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_ims_2"

    @pytest.mark.asyncio
    async def test_malformed_timestamp_rows_with_equal_event_id_prefixes_sort_stably(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_bad_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "malformed B",
                "timestamp": "bad-ts-two",
            },
            {
                "event_id": "evt_bad_10",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "malformed A",
                "timestamp": "bad-ts-ten",
            },
            {
                "event_id": "evt_good_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "valid row",
                "timestamp": "2026-02-18T03:50:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?camera_id=usb:0&event_type=provider_error")
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == [
                "evt_bad_10",
                "evt_bad_2",
                "evt_good_1",
            ]

    @pytest.mark.asyncio
    async def test_limit_with_compound_filters_when_malformed_and_valid_rows_coexist(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_lmv_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "older malformed",
                "timestamp": "bad-ts-legacy",
            },
            {
                "event_id": "evt_lmv_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "valid newest",
                "timestamp": "2026-02-18T03:55:00",
            },
            {
                "event_id": "evt_lmv_3",
                "event_type": "provider_error",
                "camera_id": "usb:1",
                "camera_name": "Lab",
                "rule_id": "",
                "rule_name": "",
                "message": "different camera",
                "timestamp": "2026-02-18T03:56:00",
            },
            {
                "event_id": "evt_lmv_4",
                "event_type": "startup_warning",
                "camera_id": "",
                "camera_name": "",
                "rule_id": "",
                "rule_name": "",
                "message": "different type",
                "timestamp": "2026-02-18T03:57:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_lmv_2"

    @pytest.mark.asyncio
    async def test_valid_since_excludes_malformed_rows_under_compound_filters_and_limit(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_vsm_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "malformed row should be excluded by valid cursor",
                "timestamp": "bad-ts-legacy",
            },
            {
                "event_id": "evt_vsm_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "older valid row after cursor",
                "timestamp": "2026-02-18T03:59:00",
            },
            {
                "event_id": "evt_vsm_3",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "newest valid row after cursor",
                "timestamp": "2026-02-18T04:00:00",
            },
            {
                "event_id": "evt_vsm_4",
                "event_type": "provider_error",
                "camera_id": "usb:1",
                "camera_name": "Lab",
                "rule_id": "",
                "rule_name": "",
                "message": "different camera",
                "timestamp": "2026-02-18T04:01:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T03:58:00Z&camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_vsm_3"

    @pytest.mark.asyncio
    async def test_equivalent_utc_instants_tie_break_by_event_id(self, state_with_data):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_eq_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "same instant offset +08:00",
                "timestamp": "2026-02-18T12:00:00+08:00",
            },
            {
                "event_id": "evt_eq_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "same instant UTC",
                "timestamp": "2026-02-18T04:00:00+00:00",
            },
            {
                "event_id": "evt_eq_3",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "later instant",
                "timestamp": "2026-02-18T04:00:01+00:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/alerts?camera_id=usb:0&event_type=provider_error")
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == [
                "evt_eq_1",
                "evt_eq_2",
                "evt_eq_3",
            ]

    @pytest.mark.asyncio
    async def test_equivalent_instant_since_plus_limit_returns_latest(
        self, state_with_data
    ):
        state_with_data["alert_events"] = [
            {
                "event_id": "evt_eqs_1",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "same instant UTC",
                "timestamp": "2026-02-18T04:00:00+00:00",
            },
            {
                "event_id": "evt_eqs_2",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "same instant +08:00",
                "timestamp": "2026-02-18T12:00:00+08:00",
            },
            {
                "event_id": "evt_eqs_3",
                "event_type": "provider_error",
                "camera_id": "usb:0",
                "camera_name": "Office",
                "rule_id": "",
                "rule_name": "",
                "message": "later instant",
                "timestamp": "2026-02-18T04:00:02+00:00",
            },
        ]
        app = create_vision_routes(state_with_data)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/alerts?since=2026-02-18T04:00:00Z&camera_id=usb:0&event_type=provider_error&limit=1"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "evt_eqs_3"


# ── Rules owner_id support ───────────────────────────────────


def _make_rules_state() -> dict:
    """State dict with a rules engine for testing CRUD with owner_id."""
    from physical_mcp.rules.engine import RulesEngine

    state = _make_state(with_frame=False, with_scene=False)
    state["rules_engine"] = RulesEngine()
    return state


class TestRulesOwnerIdAPI:
    """Vision API rules endpoints with owner_id support."""

    @pytest.mark.asyncio
    async def test_create_rule_with_owner_id(self):
        """POST /rules with owner_id persists it."""
        state = _make_rules_state()
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/rules",
                json={
                    "name": "Grandma's door watch",
                    "condition": "person at door",
                    "owner_id": "whatsapp:+8613800138000",
                    "owner_name": "Grandma",
                    "custom_message": "Someone's at the door!",
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["owner_id"] == "whatsapp:+8613800138000"
            assert data["owner_name"] == "Grandma"
            assert data["custom_message"] == "Someone's at the door!"

    @pytest.mark.asyncio
    async def test_create_rule_without_owner_id_defaults_empty(self):
        """POST /rules without owner_id defaults to empty string."""
        state = _make_rules_state()
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/rules",
                json={
                    "name": "Test rule",
                    "condition": "test condition",
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["owner_id"] == ""
            assert data["owner_name"] == ""

    @pytest.mark.asyncio
    async def test_list_rules_filters_by_owner_id(self):
        """GET /rules?owner_id=X returns only that user's rules + global rules."""
        state = _make_rules_state()
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            # Create rules for different owners
            await client.post(
                "/rules",
                json={
                    "name": "Alice's rule",
                    "condition": "cat on couch",
                    "owner_id": "discord:111",
                },
            )
            await client.post(
                "/rules",
                json={
                    "name": "Bob's rule",
                    "condition": "dog in yard",
                    "owner_id": "discord:222",
                },
            )
            await client.post(
                "/rules",
                json={
                    "name": "Global rule",
                    "condition": "fire detected",
                    # No owner_id — global rule
                },
            )

            # Alice sees her rule + global
            resp = await client.get("/rules?owner_id=discord:111")
            data = await resp.json()
            names = {r["name"] for r in data}
            assert "Alice's rule" in names
            assert "Global rule" in names
            assert "Bob's rule" not in names

            # Bob sees his rule + global
            resp = await client.get("/rules?owner_id=discord:222")
            data = await resp.json()
            names = {r["name"] for r in data}
            assert "Bob's rule" in names
            assert "Global rule" in names
            assert "Alice's rule" not in names

            # No filter → all rules
            resp = await client.get("/rules")
            data = await resp.json()
            assert len(data) == 3

    @pytest.mark.asyncio
    async def test_delete_rule_ownership_check(self):
        """DELETE /rules/{id}?owner_id=X rejects if rule belongs to another user."""
        state = _make_rules_state()
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            # Create Alice's rule
            resp = await client.post(
                "/rules",
                json={
                    "name": "Alice's rule",
                    "condition": "cat on couch",
                    "owner_id": "discord:111",
                },
            )
            rule_id = (await resp.json())["id"]

            # Bob tries to delete → 403
            resp = await client.delete(f"/rules/{rule_id}?owner_id=discord:222")
            assert resp.status == 403
            data = await resp.json()
            assert data["code"] == "forbidden"

            # Alice deletes her own rule → 200
            resp = await client.delete(f"/rules/{rule_id}?owner_id=discord:111")
            assert resp.status == 200
            data = await resp.json()
            assert data["deleted"] == rule_id

    @pytest.mark.asyncio
    async def test_delete_rule_no_owner_id_always_works(self):
        """DELETE /rules/{id} without owner_id works (backward compatible)."""
        state = _make_rules_state()
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/rules",
                json={
                    "name": "Test rule",
                    "condition": "test",
                    "owner_id": "discord:111",
                },
            )
            rule_id = (await resp.json())["id"]

            # Delete without owner_id → works
            resp = await client.delete(f"/rules/{rule_id}")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_rule_to_dict_includes_owner_fields(self):
        """GET /rules response includes owner_id, owner_name, custom_message."""
        state = _make_rules_state()
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/rules",
                json={
                    "name": "Test rule",
                    "condition": "test",
                    "owner_id": "telegram:999",
                    "owner_name": "Grandpa",
                    "custom_message": "Alert!",
                },
            )
            resp = await client.get("/rules")
            data = await resp.json()
            assert len(data) == 1
            rule = data[0]
            assert rule["owner_id"] == "telegram:999"
            assert rule["owner_name"] == "Grandpa"
            assert rule["custom_message"] == "Alert!"


# ── Cloud camera ingestion endpoint ──────────────────────────


class TestIngestEndpoint:
    """POST /ingest/{camera_id} — cloud cameras push frames here."""

    @pytest.mark.asyncio
    async def test_ingest_to_nonexistent_camera(self):
        """POST /ingest for unknown camera → 404."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/ingest/cloud:unknown",
                data=b"\xff\xd8\xff\xe0fake",
            )
            assert resp.status == 404
            data = await resp.json()
            assert data["code"] == "camera_not_found"

    @pytest.mark.asyncio
    async def test_ingest_to_non_cloud_camera(self):
        """POST /ingest for a USB camera → 400."""
        state = _make_state(with_frame=True, with_scene=False)
        # Inject a non-cloud camera
        state["cameras"] = {"usb:0": MagicMock()}
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/ingest/usb:0",
                data=b"\xff\xd8\xff\xe0fake",
            )
            assert resp.status == 400
            data = await resp.json()
            assert data["code"] == "not_cloud_camera"

    @pytest.mark.asyncio
    async def test_ingest_with_invalid_token(self):
        """POST /ingest with wrong token → 401."""
        from physical_mcp.camera.cloud import CloudCamera
        from physical_mcp.camera.buffer import FrameBuffer

        cam = CloudCamera(camera_id="cloud:test", auth_token="secret123")
        await cam.open()

        state = _make_state(with_frame=False, with_scene=False)
        state["cameras"] = {"cloud:test": cam}
        state["frame_buffers"] = {"cloud:test": FrameBuffer()}

        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/ingest/cloud:test",
                data=b"\xff\xd8\xff\xe0fake",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401
            data = await resp.json()
            assert data["code"] == "invalid_camera_token"

        await cam.close()

    @pytest.mark.asyncio
    async def test_ingest_with_valid_token_and_jpeg(self):
        """POST /ingest with correct token + valid JPEG → 200."""
        import cv2
        import numpy as np
        from physical_mcp.camera.cloud import CloudCamera
        from physical_mcp.camera.buffer import FrameBuffer

        cam = CloudCamera(camera_id="cloud:door", auth_token="sk_door123")
        await cam.open()
        buf = FrameBuffer()

        state = _make_state(with_frame=False, with_scene=False)
        state["cameras"] = {"cloud:door": cam}
        state["frame_buffers"] = {"cloud:door": buf}

        # Create a valid JPEG
        image = np.random.randint(0, 255, (100, 160, 3), dtype=np.uint8)
        _, jpeg_buf = cv2.imencode(".jpg", image)
        jpeg_bytes = jpeg_buf.tobytes()

        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/ingest/cloud:door",
                data=jpeg_bytes,
                headers={"Authorization": "Bearer sk_door123"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["camera_id"] == "cloud:door"

        await cam.close()

    @pytest.mark.asyncio
    async def test_ingest_empty_body(self):
        """POST /ingest with empty body → 400."""
        from physical_mcp.camera.cloud import CloudCamera

        cam = CloudCamera(camera_id="cloud:test", auth_token="")
        await cam.open()

        state = _make_state(with_frame=False, with_scene=False)
        state["cameras"] = {"cloud:test": cam}

        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/ingest/cloud:test", data=b"")
            assert resp.status == 400
            data = await resp.json()
            assert data["code"] == "empty_body"

        await cam.close()

    @pytest.mark.asyncio
    async def test_ingest_invalid_jpeg(self):
        """POST /ingest with invalid JPEG data → 400."""
        from physical_mcp.camera.cloud import CloudCamera

        cam = CloudCamera(camera_id="cloud:test", auth_token="")
        await cam.open()

        state = _make_state(with_frame=False, with_scene=False)
        state["cameras"] = {"cloud:test": cam}

        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/ingest/cloud:test",
                data=b"this is not a jpeg image at all",
            )
            assert resp.status == 400
            data = await resp.json()
            assert data["code"] == "invalid_jpeg"

        await cam.close()


# ── Camera registration endpoints ────────────────────────────


class TestCameraRegistration:
    """POST /cameras/register, GET /cameras/pending, POST /cameras/{id}/accept."""

    @pytest.mark.asyncio
    async def test_register_new_camera(self):
        """POST /cameras/register creates a pending camera."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-A3F2B1",
                    "name": "Front Door Camera",
                    "capabilities": {"resolution": "1080p", "night_vision": True},
                    "firmware_version": "1.2.3",
                },
            )
            assert resp.status == 202
            data = await resp.json()
            assert data["status"] == "pending"
            assert data["camera_id"] == "decxin-A3F2B1"

    @pytest.mark.asyncio
    async def test_register_duplicate_camera(self):
        """POST /cameras/register for already-pending camera → 409."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-A3F2B1",
                    "name": "Front Door",
                },
            )
            resp = await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-A3F2B1",
                    "name": "Front Door Again",
                },
            )
            assert resp.status == 409
            data = await resp.json()
            assert data["code"] == "already_pending"

    @pytest.mark.asyncio
    async def test_list_pending_cameras(self):
        """GET /cameras/pending returns pending cameras without auth tokens."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-001",
                    "name": "Kitchen Cam",
                },
            )
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-002",
                    "name": "Living Room Cam",
                },
            )

            resp = await client.get("/cameras/pending")
            assert resp.status == 200
            data = await resp.json()
            assert len(data) == 2
            ids = {c["camera_id"] for c in data}
            assert "decxin-001" in ids
            assert "decxin-002" in ids
            # Auth token should NOT be exposed
            for cam in data:
                assert "auth_token" not in cam

    @pytest.mark.asyncio
    async def test_accept_pending_camera(self):
        """POST /cameras/{id}/accept creates a CloudCamera and returns token."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            # Register
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-ABC",
                    "name": "Garage Cam",
                },
            )

            # Accept
            resp = await client.post("/cameras/decxin-ABC/accept")
            assert resp.status == 201
            data = await resp.json()
            assert data["status"] == "accepted"
            assert data["camera_id"] == "decxin-ABC"
            assert "auth_token" in data
            assert data["ingest_url"] == "/ingest/decxin-ABC"

            # Pending list should be empty now
            resp = await client.get("/cameras/pending")
            data = await resp.json()
            assert len(data) == 0

    @pytest.mark.asyncio
    async def test_accept_nonexistent_camera(self):
        """POST /cameras/{id}/accept for unknown camera → 404."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/cameras/ghost-cam/accept")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_reject_pending_camera(self):
        """POST /cameras/{id}/reject removes from pending."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-REJECT",
                    "name": "Unwanted Cam",
                },
            )

            resp = await client.post("/cameras/decxin-REJECT/reject")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "rejected"

            # Pending list should be empty
            resp = await client.get("/cameras/pending")
            data = await resp.json()
            assert len(data) == 0

    @pytest.mark.asyncio
    async def test_register_missing_camera_id(self):
        """POST /cameras/register without camera_id → 400."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/cameras/register",
                json={
                    "name": "No ID Camera",
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert data["code"] == "missing_camera_id"

    @pytest.mark.asyncio
    async def test_ingest_to_pending_camera(self):
        """POST /ingest for a pending (not yet accepted) camera → 403."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            # Register but don't accept
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-PENDING",
                    "name": "Pending Cam",
                },
            )

            # Try to ingest → 403
            resp = await client.post(
                "/ingest/decxin-PENDING",
                data=b"\xff\xd8\xff\xe0fake",
            )
            assert resp.status == 403
            data = await resp.json()
            assert data["code"] == "camera_pending"


class TestCameraStatusPolling:
    """GET /cameras/{camera_id}/status — camera firmware polls for acceptance."""

    @pytest.mark.asyncio
    async def test_status_pending_camera(self):
        """Pending camera returns status=pending."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-POLL1",
                    "name": "Polling Cam",
                },
            )
            resp = await client.get("/cameras/decxin-POLL1/status")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "pending"
            assert data["camera_id"] == "decxin-POLL1"
            assert "auth_token" not in data

    @pytest.mark.asyncio
    async def test_status_accepted_camera(self):
        """Accepted camera returns status=accepted + auth_token + ingest_url."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-POLL2",
                    "name": "Accepted Cam",
                },
            )
            # Accept
            accept_resp = await client.post("/cameras/decxin-POLL2/accept")
            accept_data = await accept_resp.json()
            expected_token = accept_data["auth_token"]

            # Now poll status
            resp = await client.get("/cameras/decxin-POLL2/status")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "accepted"
            assert data["auth_token"] == expected_token
            assert data["ingest_url"] == "/ingest/decxin-POLL2"

    @pytest.mark.asyncio
    async def test_status_unknown_camera(self):
        """Unknown camera_id → 404."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/cameras/nonexistent-cam/status")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_status_no_auth_required(self):
        """Status endpoint works without auth token (camera doesn't have one yet)."""
        from physical_mcp.config import PhysicalMCPConfig, VisionAPIConfig

        state = _make_state(with_frame=False, with_scene=False)
        state["config"] = PhysicalMCPConfig(
            vision_api=VisionAPIConfig(auth_token="secret-global-token")
        )
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            # Register a camera (no auth needed for that)
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-NOAUTH",
                    "name": "No Auth Cam",
                },
            )

            # Status should work WITHOUT auth header
            resp = await client.get("/cameras/decxin-NOAUTH/status")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_full_registration_loop(self):
        """Full camera lifecycle: register → poll(pending) → accept → poll(accepted) → ingest."""
        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            # 1. Register
            resp = await client.post(
                "/cameras/register",
                json={
                    "camera_id": "decxin-LOOP",
                    "name": "Loop Cam",
                },
            )
            assert resp.status == 202

            # 2. Poll → pending
            resp = await client.get("/cameras/decxin-LOOP/status")
            data = await resp.json()
            assert data["status"] == "pending"

            # 3. Accept
            resp = await client.post("/cameras/decxin-LOOP/accept")
            assert resp.status == 201
            token = (await resp.json())["auth_token"]

            # 4. Poll → accepted + token
            resp = await client.get("/cameras/decxin-LOOP/status")
            data = await resp.json()
            assert data["status"] == "accepted"
            assert data["auth_token"] == token
            assert data["ingest_url"] == "/ingest/decxin-LOOP"


class TestPendingCameraPersistence:
    """Pending cameras are saved to and loaded from disk."""

    @pytest.mark.asyncio
    async def test_register_saves_to_disk(self, tmp_path, monkeypatch):
        """Registering a camera writes pending.yaml."""
        pending_path = tmp_path / "pending.yaml"
        monkeypatch.setattr("physical_mcp.vision_api._PENDING_PATH", pending_path)

        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/cameras/register",
                json={
                    "camera_id": "persist-001",
                    "name": "Persist Cam",
                },
            )
            assert resp.status == 202

        # File should exist and contain the camera
        assert pending_path.exists()
        import yaml

        data = yaml.safe_load(pending_path.read_text())
        assert "persist-001" in data
        assert data["persist-001"]["name"] == "Persist Cam"

    @pytest.mark.asyncio
    async def test_accept_removes_from_disk(self, tmp_path, monkeypatch):
        """Accepting a camera removes it from pending.yaml."""
        pending_path = tmp_path / "pending.yaml"
        monkeypatch.setattr("physical_mcp.vision_api._PENDING_PATH", pending_path)

        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "persist-002",
                    "name": "Accept Me",
                },
            )
            await client.post("/cameras/persist-002/accept")

        import yaml

        data = yaml.safe_load(pending_path.read_text())
        # Should be empty dict or None (no pending cameras)
        assert not data or "persist-002" not in data

    @pytest.mark.asyncio
    async def test_reject_removes_from_disk(self, tmp_path, monkeypatch):
        """Rejecting a camera removes it from pending.yaml."""
        pending_path = tmp_path / "pending.yaml"
        monkeypatch.setattr("physical_mcp.vision_api._PENDING_PATH", pending_path)

        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "persist-003",
                    "name": "Reject Me",
                },
            )
            await client.post("/cameras/persist-003/reject")

        import yaml

        data = yaml.safe_load(pending_path.read_text())
        assert not data or "persist-003" not in data

    @pytest.mark.asyncio
    async def test_load_on_startup(self, tmp_path, monkeypatch):
        """Pending cameras are loaded from disk on app creation."""
        import yaml

        pending_path = tmp_path / "pending.yaml"
        pending_path.write_text(
            yaml.dump(
                {
                    "preexist-cam": {
                        "camera_id": "preexist-cam",
                        "name": "Pre-existing Camera",
                        "auth_token": "pretoken123",
                        "capabilities": {},
                        "firmware_version": "2.0",
                        "registered_at": "2026-02-24T00:00:00+00:00",
                        "status": "pending",
                    }
                }
            )
        )
        monkeypatch.setattr("physical_mcp.vision_api._PENDING_PATH", pending_path)

        state = _make_state(with_frame=False, with_scene=False)
        # Remove pending_cameras so create_vision_routes loads from disk
        del state["pending_cameras"]
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/cameras/pending")
            data = await resp.json()
            assert len(data) == 1
            assert data[0]["camera_id"] == "preexist-cam"
            assert data[0]["name"] == "Pre-existing Camera"


class TestIngestHealthTracking:
    """POST /ingest updates camera_health last_frame_at."""

    @pytest.mark.asyncio
    async def test_ingest_updates_last_frame_at(self):
        """Successful ingest updates camera health timestamps."""
        import cv2
        import numpy as np

        state = _make_state(with_frame=False, with_scene=False)
        app = create_vision_routes(state)
        async with TestClient(TestServer(app)) as client:
            # Register and accept a camera
            await client.post(
                "/cameras/register",
                json={
                    "camera_id": "health-cam",
                    "name": "Health Tracking Cam",
                },
            )
            accept_resp = await client.post("/cameras/health-cam/accept")
            accept_data = await accept_resp.json()
            token = accept_data["auth_token"]

            # Health should initially have no last_frame_at
            health = state.get("camera_health", {}).get("health-cam", {})
            assert health.get("last_frame_at") is None

            # Push a valid JPEG frame
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            _, jpeg_bytes = cv2.imencode(".jpg", img)

            resp = await client.post(
                "/ingest/health-cam",
                data=jpeg_bytes.tobytes(),
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 200

            # Health should now have last_frame_at set
            health = state.get("camera_health", {}).get("health-cam", {})
            assert health.get("last_frame_at") is not None
            assert health.get("status") == "running"
            assert health.get("consecutive_errors") == 0
