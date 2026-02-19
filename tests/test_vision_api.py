"""Tests for the HTTP Vision API."""

from __future__ import annotations

import asyncio
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


# ── SSE events endpoint ──────────────────────────────────────


class TestSSEEvents:
    @pytest.mark.asyncio
    async def test_events_returns_sse(self, state_with_data):
        """Events endpoint returns text/event-stream with scene data."""

        iteration = 0

        # We need to make the SSE loop terminate after sending initial data
        original_scenes = state_with_data["scene_states"]
        original_get = dict.get

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
    async def test_health_single_non_dict_row_falls_back_to_defaults(self, state_with_data):
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
            assert health["message"] == "No health data yet."

    @pytest.mark.asyncio
    async def test_health_single_malformed_row_contains_required_camera_health_keys(self, state_with_data):
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
    async def test_health_single_malformed_row_nullable_fields_remain_null(self, state_with_data):
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
    async def test_health_all_normalizes_empty_camera_name_to_camera_id(self, state_with_data):
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
    async def test_health_all_normalizes_missing_camera_id_to_map_key(self, state_with_data):
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
    async def test_health_all_non_dict_row_falls_back_to_defaults(self, state_with_data):
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
    async def test_health_all_normalization_matrix_unknown_empty_malformed(self, state_with_data):
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
            assert unknown["message"] == "No health data yet."

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
            resp = await client.get("/alerts?camera_id=usb:0&event_type=watch_rule_triggered")
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
    async def test_since_then_limit_returns_most_recent_filtered_events(self, state_with_data):
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
            resp = await client.get("/alerts?since=2026-02-18T02:11:00&event_type=provider_error")
            assert resp.status == 200
            data = await resp.json()
            assert [e["event_id"] for e in data["events"]] == ["evt_402"]

    @pytest.mark.asyncio
    async def test_since_plus_limit_when_only_boundary_equal_events(self, state_with_data):
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
    async def test_event_type_filter_matches_stored_uppercase_values(self, state_with_data):
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
    async def test_invalid_since_with_normalized_stored_fields_and_limit(self, state_with_data):
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
    async def test_boundary_since_excludes_equal_with_normalized_stored_fields(self, state_with_data):
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
    async def test_boundary_since_with_limit_one_normalized_fields(self, state_with_data):
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
    async def test_camera_alert_pending_eval_filter_normalized_and_limited(self, state_with_data):
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
    async def test_malformed_timestamps_are_tolerated_and_sorted_deterministically(self, state_with_data):
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
    async def test_since_cursor_accepts_z_timezone_and_skips_malformed(self, state_with_data):
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
    async def test_limit_with_mixed_timezone_rows_returns_newest_deterministically(self, state_with_data):
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
    async def test_boundary_equal_since_exclusive_with_mixed_timezone_rows(self, state_with_data):
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
    async def test_invalid_since_with_mixed_timezones_and_limit_uses_unfiltered_cursor(self, state_with_data):
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
    async def test_malformed_timestamp_rows_with_equal_event_id_prefixes_sort_stably(self, state_with_data):
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
    async def test_limit_with_compound_filters_when_malformed_and_valid_rows_coexist(self, state_with_data):
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
    async def test_valid_since_excludes_malformed_rows_under_compound_filters_and_limit(self, state_with_data):
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
    async def test_equivalent_instant_since_plus_limit_returns_latest(self, state_with_data):
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
