"""Tests for MCP log formatting and alert event recording helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from physical_mcp.server import (
    _emit_startup_fallback_warning,
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
        assert "fallback" in evt["message"].lower()

        # MCP log sent with same event id
        kwargs = session.send_log_message.await_args.kwargs
        assert f"event_id={evt['event_id']}" in kwargs["data"]

        # Second call should no-op
        emitted2 = await _emit_startup_fallback_warning(state)
        assert emitted2 is False
        assert len(state["alert_events"]) == 1
