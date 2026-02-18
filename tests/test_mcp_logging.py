"""Tests for MCP log formatting and alert event recording helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from physical_mcp.config import PhysicalMCPConfig
from physical_mcp.server import (
    _apply_provider_configuration,
    _emit_fallback_mode_warning,
    _emit_startup_fallback_warning,
    _perception_loop,
    _record_alert_event,
    _send_mcp_log,
)


class TestMcpLogFormatting:
    @pytest.mark.asyncio
    async def test_send_mcp_log_includes_prefix_metadata(self):
        session = AsyncMock()
        shared_state = {"_session": session}

        await _send_mcp_log(
            shared_state,
            "warning",
            "Rule triggered",
            event_type="watch_rule_triggered",
            camera_id="usb:0",
            rule_id="r_123",
            event_id="evt_fixed",
        )

        session.send_log_message.assert_awaited_once()
        kwargs = session.send_log_message.await_args.kwargs
        assert kwargs["level"] == "warning"
        assert kwargs["logger"] == "physical-mcp"
        assert kwargs["data"].startswith(
            "PMCP[WATCH_RULE_TRIGGERED] | event_id=evt_fixed | camera_id=usb:0 | rule_id=r_123 |"
        )

    @pytest.mark.asyncio
    async def test_send_mcp_log_generates_event_id_when_missing(self):
        session = AsyncMock()
        shared_state = {"_session": session}

        await _send_mcp_log(
            shared_state,
            "info",
            "hello",
            event_type="startup_warning",
        )

        kwargs = session.send_log_message.await_args.kwargs
        assert "PMCP[STARTUP_WARNING]" in kwargs["data"]
        assert "event_id=evt_" in kwargs["data"]

    @pytest.mark.asyncio
    async def test_send_mcp_log_without_session_is_noop(self):
        shared_state = {}
        # Should not raise
        await _send_mcp_log(shared_state, "info", "hello")

    @pytest.mark.asyncio
    async def test_send_mcp_log_publishes_structured_event_bus_payload(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        shared_state = {"_session": session, "event_bus": event_bus}

        await _send_mcp_log(
            shared_state,
            "warning",
            "Provider timeout",
            event_type="provider_error",
            camera_id="usb:0",
            rule_id="r_42",
            event_id="evt_struct",
        )

        event_bus.publish.assert_awaited_once()
        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_type"] == "provider_error"
        assert payload["event_id"] == "evt_struct"
        assert payload["camera_id"] == "usb:0"
        assert payload["rule_id"] == "r_42"
        assert payload["level"] == "warning"
        assert payload["logger"] == "physical-mcp"
        assert payload["data"].startswith(
            "PMCP[PROVIDER_ERROR] | event_id=evt_struct | camera_id=usb:0 | rule_id=r_42 |"
        )

    @pytest.mark.asyncio
    async def test_send_mcp_log_without_session_still_fanouts_to_event_bus(self):
        event_bus = AsyncMock()
        shared_state = {"event_bus": event_bus}

        await _send_mcp_log(
            shared_state,
            "info",
            "background signal",
            event_type="system",
            event_id="evt_bus_only",
        )

        event_bus.publish.assert_awaited_once()
        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_id"] == "evt_bus_only"


class TestAlertEventRecording:
    def test_record_alert_event_capped(self):
        state = {"alert_events": [], "alert_events_max": 2}

        _record_alert_event(state, event_type="system", message="a")
        _record_alert_event(state, event_type="system", message="b")
        _record_alert_event(state, event_type="system", message="c")

        events = state["alert_events"]
        assert len(events) == 2
        assert events[0]["message"] == "b"
        assert events[1]["message"] == "c"
        assert all(e["event_id"].startswith("evt_") for e in events)

    def test_record_alert_event_includes_timestamp_and_type(self):
        state = {"alert_events": [], "alert_events_max": 10}

        _record_alert_event(state, event_type="startup_warning", message="fallback")
        evt = state["alert_events"][0]

        assert evt["event_type"] == "startup_warning"
        assert evt["message"] == "fallback"
        # ISO-like timestamp from datetime.now().isoformat()
        assert "T" in evt["timestamp"]


class TestMcpReplayAndFanoutCorrelation:
    @pytest.mark.asyncio
    async def test_provider_error_replay_and_event_bus_share_event_id(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        state = {
            "_session": session,
            "event_bus": event_bus,
            "alert_events": [],
            "alert_events_max": 50,
        }

        evt_id = _record_alert_event(
            state,
            event_type="provider_error",
            camera_id="usb:0",
            camera_name="Office",
            message="Vision provider timeout",
        )

        await _send_mcp_log(
            state,
            "error",
            "[Office (usb:0)] Vision provider timeout",
            event_type="provider_error",
            camera_id="usb:0",
            event_id=evt_id,
        )

        assert state["alert_events"][0]["event_id"] == evt_id

        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_type"] == "provider_error"
        assert payload["event_id"] == evt_id
        assert payload["camera_id"] == "usb:0"

        kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={evt_id}" in kwargs["data"]

    @pytest.mark.asyncio
    async def test_watch_rule_triggered_replay_and_event_bus_share_event_id(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        state = {
            "_session": session,
            "event_bus": event_bus,
            "alert_events": [],
            "alert_events_max": 50,
        }

        evt_id = _record_alert_event(
            state,
            event_type="watch_rule_triggered",
            camera_id="usb:0",
            camera_name="Office",
            rule_id="r_123",
            rule_name="Front Door Watch",
            message="Person detected at the door",
        )

        await _send_mcp_log(
            state,
            "warning",
            "WATCH RULE TRIGGERED [Office (usb:0)]: Front Door Watch — Person detected",
            event_type="watch_rule_triggered",
            camera_id="usb:0",
            rule_id="r_123",
            event_id=evt_id,
        )

        assert state["alert_events"][0]["event_id"] == evt_id

        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_type"] == "watch_rule_triggered"
        assert payload["event_id"] == evt_id
        assert payload["camera_id"] == "usb:0"
        assert payload["rule_id"] == "r_123"

        kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={evt_id}" in kwargs["data"]


class TestCameraAlertPendingEval:
    @pytest.mark.asyncio
    async def test_recorded_event_id_is_reused_in_standardized_log(self):
        session = AsyncMock()
        state = {
            "_session": session,
            "alert_events": [],
            "alert_events_max": 50,
        }

        evt_id = _record_alert_event(
            state,
            event_type="camera_alert_pending_eval",
            camera_id="usb:0",
            camera_name="Desk Cam",
            message="major scene change; active rules: door",
        )

        await _send_mcp_log(
            state,
            "warning",
            "CAMERA ALERT [Desk Cam (usb:0)] ...",
            event_type="camera_alert_pending_eval",
            camera_id="usb:0",
            event_id=evt_id,
        )

        kwargs = session.send_log_message.await_args.kwargs
        assert kwargs["data"].startswith(
            "PMCP[CAMERA_ALERT_PENDING_EVAL] | "
            f"event_id={evt_id} | camera_id=usb:0 |"
        )
        assert state["alert_events"][0]["event_id"] == evt_id


class TestPerceptionLoopProviderErrorCorrelation:
    @pytest.mark.asyncio
    async def test_provider_error_branch_replay_and_mcp_log_fanout_share_event_id(self):
        frame = MagicMock()
        camera = AsyncMock()
        camera.grab_frame = AsyncMock(side_effect=[frame, asyncio.CancelledError()])

        frame_buffer = AsyncMock()
        sampler = MagicMock()
        change = SimpleNamespace(
            level=SimpleNamespace(value="major"),
            description="major scene change",
            hash_distance=22,
            pixel_diff_pct=42.0,
        )
        sampler.should_analyze.return_value = (True, change)

        analyzer = MagicMock()
        analyzer.has_provider = True
        analyzer.analyze_scene = AsyncMock(side_effect=Exception("provider timeout"))

        scene_state = MagicMock()
        rules_engine = MagicMock()
        rules_engine.get_active_rules.return_value = []
        stats = MagicMock()
        stats.budget_exceeded.return_value = False

        config = PhysicalMCPConfig()
        config.perception.capture_fps = 1000  # keep loop fast in test

        alert_queue = AsyncMock()
        session = AsyncMock()
        event_bus = AsyncMock()
        shared_state = {
            "_session": session,
            "event_bus": event_bus,
            "alert_events": [],
            "alert_events_max": 50,
            "camera_health": {},
        }

        with pytest.raises(asyncio.CancelledError):
            await _perception_loop(
                camera=camera,
                frame_buffer=frame_buffer,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene_state,
                rules_engine=rules_engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                notifier=None,
                memory=None,
                shared_state=shared_state,
                camera_id="usb:0",
                camera_name="Office",
            )

        assert len(shared_state["alert_events"]) == 1
        replay_evt = shared_state["alert_events"][0]
        assert replay_evt["event_type"] == "provider_error"

        # EventBus fanout should carry same event_id
        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_type"] == "provider_error"
        assert payload["event_id"] == replay_evt["event_id"]
        assert payload["camera_id"] == "usb:0"

        # Session log should carry same event_id too
        kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={replay_evt['event_id']}" in kwargs["data"]


    @pytest.mark.asyncio
    async def test_watch_rule_triggered_branch_replay_and_mcp_log_fanout_share_event_id(self):
        frame = MagicMock()
        frame.to_base64.return_value = "fake-b64"

        camera = AsyncMock()
        camera.grab_frame = AsyncMock(side_effect=[frame, asyncio.CancelledError()])

        frame_buffer = AsyncMock()
        sampler = MagicMock()
        change = SimpleNamespace(
            level=SimpleNamespace(value="major"),
            description="major scene change",
            hash_distance=22,
            pixel_diff_pct=42.0,
        )
        sampler.should_analyze.return_value = (True, change)

        analyzer = MagicMock()
        analyzer.has_provider = True
        analyzer.analyze_scene = AsyncMock(return_value={
            "summary": "person near door",
            "objects": ["person", "door"],
            "people_count": 1,
        })
        analyzer.evaluate_rules = AsyncMock(return_value=[{"rule_id": "r_123", "triggered": True}])

        scene_state = MagicMock()
        rules_engine = MagicMock()
        active_rule = SimpleNamespace(id="r_123", name="Front Door Watch")
        rules_engine.get_active_rules.return_value = [active_rule]
        alert = SimpleNamespace(
            rule=SimpleNamespace(id="r_123", name="Front Door Watch"),
            evaluation=SimpleNamespace(confidence=0.91, reasoning="Person detected at the door"),
        )
        rules_engine.process_evaluations.return_value = [alert]

        stats = MagicMock()
        stats.budget_exceeded.return_value = False

        config = PhysicalMCPConfig()
        config.perception.capture_fps = 1000

        alert_queue = AsyncMock()
        session = AsyncMock()
        event_bus = AsyncMock()
        shared_state = {
            "_session": session,
            "event_bus": event_bus,
            "alert_events": [],
            "alert_events_max": 50,
            "camera_health": {},
        }

        with pytest.raises(asyncio.CancelledError):
            await _perception_loop(
                camera=camera,
                frame_buffer=frame_buffer,
                sampler=sampler,
                analyzer=analyzer,
                scene_state=scene_state,
                rules_engine=rules_engine,
                stats=stats,
                config=config,
                alert_queue=alert_queue,
                notifier=None,
                memory=None,
                shared_state=shared_state,
                camera_id="usb:0",
                camera_name="Office",
            )

        replay_evt = shared_state["alert_events"][0]
        assert replay_evt["event_type"] == "watch_rule_triggered"

        publish_calls = event_bus.publish.await_args_list
        mcp_calls = [c for c in publish_calls if c.args and c.args[0] == "mcp_log"]
        assert len(mcp_calls) >= 1
        _, mcp_payload = mcp_calls[-1].args

        assert mcp_payload["event_type"] == "watch_rule_triggered"
        assert mcp_payload["event_id"] == replay_evt["event_id"]
        assert mcp_payload["camera_id"] == "usb:0"
        assert mcp_payload["rule_id"] == "r_123"

        kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={replay_evt['event_id']}" in kwargs["data"]

    @pytest.mark.asyncio
    async def test_provider_error_mcp_log_payload_data_parity_with_session_log(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        state = {
            "_session": session,
            "event_bus": event_bus,
            "alert_events": [],
            "alert_events_max": 50,
        }

        evt_id = _record_alert_event(
            state,
            event_type="provider_error",
            camera_id="usb:0",
            camera_name="Office",
            message="Vision provider timeout",
        )

        await _send_mcp_log(
            state,
            "error",
            "[Office (usb:0)] Vision provider timeout",
            event_type="provider_error",
            camera_id="usb:0",
            event_id=evt_id,
        )

        _, payload = event_bus.publish.await_args.args
        session_kwargs = session.send_log_message.await_args.kwargs
        assert payload["data"] == session_kwargs["data"]

    @pytest.mark.asyncio
    async def test_watch_rule_mcp_log_payload_data_parity_with_session_log(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        state = {
            "_session": session,
            "event_bus": event_bus,
            "alert_events": [],
            "alert_events_max": 50,
        }

        evt_id = _record_alert_event(
            state,
            event_type="watch_rule_triggered",
            camera_id="usb:0",
            camera_name="Office",
            rule_id="r_123",
            rule_name="Front Door Watch",
            message="Person detected at the door",
        )

        await _send_mcp_log(
            state,
            "warning",
            "WATCH RULE TRIGGERED [Office (usb:0)]: Front Door Watch — Person detected",
            event_type="watch_rule_triggered",
            camera_id="usb:0",
            rule_id="r_123",
            event_id=evt_id,
        )

        _, payload = event_bus.publish.await_args.args
        session_kwargs = session.send_log_message.await_args.kwargs
        assert payload["data"] == session_kwargs["data"]


class TestStartupFallbackWarningLifespan:
    @pytest.mark.asyncio
    async def test_startup_warning_through_server_lifespan_emits_empty_field_event(self):
        """Test startup warning as emitted through full server lifespan path.

        Simulates state initialized during app_lifespan with _fallback_warning_pending
        and verifies empty-field contract is maintained.
        """
        session = AsyncMock()
        event_bus = AsyncMock()

        # State structure mirrors what app_lifespan creates
        state = {
            "_session": session,
            "event_bus": event_bus,
            "_fallback_warning_pending": True,  # Set when no provider configured
            "alert_events": [],
            "alert_events_max": 50,
            "camera_health": {},
        }

        await _emit_startup_fallback_warning(state)

        assert state["_fallback_warning_pending"] is False
        assert len(state["alert_events"]) == 1
        evt = state["alert_events"][0]
        assert evt["event_type"] == "startup_warning"
        assert evt["camera_id"] == ""
        assert evt["camera_name"] == ""
        assert evt["rule_id"] == ""
        assert evt["rule_name"] == ""
        assert "fallback" in evt["message"].lower()

        # Verify event_bus fanout has same event_id
        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_id"] == evt["event_id"]


class TestStartupFallbackWarning:
    @pytest.mark.asyncio
    async def test_emits_once_and_records_replay_event(self):
        session = AsyncMock()
        state = {
            "_session": session,
            "_fallback_warning_pending": True,
            "alert_events": [],
            "alert_events_max": 50,
        }

        emitted = await _emit_startup_fallback_warning(state)
        assert emitted is True
        assert state["_fallback_warning_pending"] is False

        # Replay event recorded
        assert len(state["alert_events"]) == 1
        evt = state["alert_events"][0]
        assert evt["event_type"] == "startup_warning"
        assert evt["camera_id"] == ""
        assert evt["camera_name"] == ""
        assert evt["rule_id"] == ""
        assert evt["rule_name"] == ""
        assert "fallback" in evt["message"].lower()

        # MCP log sent with same event id
        kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={evt['event_id']}" in kwargs["data"]

        # Second call should no-op
        emitted2 = await _emit_startup_fallback_warning(state)
        assert emitted2 is False
        assert len(state["alert_events"]) == 1

    @pytest.mark.asyncio
    async def test_runtime_switch_emits_fallback_warning(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        state = {
            "_session": session,
            "event_bus": event_bus,
            "alert_events": [],
            "alert_events_max": 50,
        }

        emitted = await _emit_fallback_mode_warning(state, reason="runtime_switch")
        assert emitted is True
        assert len(state["alert_events"]) == 1

        evt = state["alert_events"][0]
        assert evt["event_type"] == "startup_warning"
        assert "runtime switched to fallback" in evt["message"].lower()

        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_id"] == evt["event_id"]
        assert payload["event_type"] == "startup_warning"

        session_kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={evt['event_id']}" in session_kwargs["data"]
        assert "restore non-blocking server-side monitoring" in session_kwargs["data"].lower()

    @pytest.mark.asyncio
    async def test_startup_warning_event_bus_and_session_log_parity(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        state = {
            "_session": session,
            "event_bus": event_bus,
            "_fallback_warning_pending": True,
            "alert_events": [],
            "alert_events_max": 50,
        }

        emitted = await _emit_startup_fallback_warning(state)
        assert emitted is True
        assert len(state["alert_events"]) == 1
        evt = state["alert_events"][0]
        assert evt["event_type"] == "startup_warning"

        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        assert payload["event_type"] == "startup_warning"
        assert payload["event_id"] == evt["event_id"]

        session_kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={evt['event_id']}" in session_kwargs["data"]
        assert payload["data"] == session_kwargs["data"]

    @pytest.mark.asyncio
    async def test_startup_warning_mcp_log_payload_has_required_metadata_keys(self):
        session = AsyncMock()
        event_bus = AsyncMock()
        state = {
            "_session": session,
            "event_bus": event_bus,
            "_fallback_warning_pending": True,
            "alert_events": [],
            "alert_events_max": 50,
        }

        emitted = await _emit_startup_fallback_warning(state)
        assert emitted is True

        topic, payload = event_bus.publish.await_args.args
        assert topic == "mcp_log"
        for key in ("event_type", "event_id", "level", "data", "logger"):
            assert key in payload
        assert payload["event_type"] == "startup_warning"
        assert payload["level"] == "warning"
        assert payload["logger"] == "physical-mcp"

    @pytest.mark.asyncio
    async def test_without_session_records_event_but_no_log(self):
        state = {
            "_fallback_warning_pending": True,
            "alert_events": [],
            "alert_events_max": 50,
        }

        emitted = await _emit_startup_fallback_warning(state)
        assert emitted is True
        assert state["_fallback_warning_pending"] is False
        assert len(state["alert_events"]) == 1
        evt = state["alert_events"][0]
        assert evt["event_type"] == "startup_warning"
        assert evt["camera_id"] == ""
        assert evt["camera_name"] == ""
        assert evt["rule_id"] == ""
        assert evt["rule_name"] == ""


class TestConfigureProviderContract:
    @pytest.mark.asyncio
    async def test_runtime_downgrade_emits_warning_and_sets_contract_flag(self, monkeypatch):
        cfg = PhysicalMCPConfig()
        analyzer = MagicMock()
        analyzer.has_provider = True

        state = {
            "config": cfg,
            "analyzer": analyzer,
            "_fallback_warning_pending": False,
        }

        emit_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("physical_mcp.server._emit_fallback_mode_warning", emit_mock)
        monkeypatch.setattr("physical_mcp.server._create_provider", lambda _cfg: None)

        result = await _apply_provider_configuration(
            state,
            provider="",
            api_key="",
        )

        assert result["reasoning_mode"] == "client"
        assert result["fallback_warning_emitted"] is True
        assert result["provider"] == "none"
        assert result["model"] == "none"
        analyzer.set_provider.assert_called_once_with(None)
        emit_mock.assert_awaited_once_with(state, reason="runtime_switch")

    @pytest.mark.asyncio
    async def test_runtime_upgrade_clears_pending_without_warning(self, monkeypatch):
        cfg = PhysicalMCPConfig()
        analyzer = MagicMock()
        analyzer.has_provider = False

        state = {
            "config": cfg,
            "analyzer": analyzer,
            "_fallback_warning_pending": True,
        }

        provider_obj = SimpleNamespace(model_name="gpt-4o-mini")
        emit_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("physical_mcp.server._emit_fallback_mode_warning", emit_mock)
        monkeypatch.setattr("physical_mcp.server._create_provider", lambda _cfg: provider_obj)

        result = await _apply_provider_configuration(
            state,
            provider="openai",
            api_key="test-key",
            model="gpt-4o-mini",
        )

        assert result["reasoning_mode"] == "server"
        assert result["fallback_warning_emitted"] is False
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4o-mini"
        assert state["_fallback_warning_pending"] is False
        analyzer.set_provider.assert_called_once_with(provider_obj)
        emit_mock.assert_not_awaited()
