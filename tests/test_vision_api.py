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
            assert data["health"]["status"] == "unknown"

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
