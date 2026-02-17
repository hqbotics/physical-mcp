"""Tests for MCP log formatting and alert event recording helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from physical_mcp.server import _record_alert_event, _send_mcp_log


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
