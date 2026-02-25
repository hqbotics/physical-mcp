"""MCP log emission and alert-event recording helpers.

Shared by both the MCP server tool layer and the perception loop.
All functions are self-contained — they operate on a ``shared_state``
dict and have no implicit global state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def new_event_id() -> str:
    """Generate a short event id for MCP notifications."""
    return f"evt_{uuid.uuid4().hex[:10]}"


async def send_mcp_log(
    shared_state: dict[str, Any] | None,
    level: str,
    message: str,
    event_type: str = "system",
    camera_id: str = "",
    rule_id: str = "",
    event_id: str = "",
    timestamp: str = "",
) -> None:
    """Best-effort MCP log emission + structured internal fanout."""
    if not shared_state:
        return

    eid = event_id or new_event_id()
    parts = [f"PMCP[{event_type.upper()}]", f"event_id={eid}"]
    if camera_id:
        parts.append(f"camera_id={camera_id}")
    if rule_id:
        parts.append(f"rule_id={rule_id}")
    prefix = " | ".join(parts)
    data = f"{prefix} | {message}"

    payload = {
        "event_type": event_type,
        "event_id": eid,
        "camera_id": camera_id,
        "rule_id": rule_id,
        "level": level,
        "message": message,
        "data": data,
        "logger": "physical-mcp",
        "timestamp": timestamp or datetime.now().isoformat(),
    }

    # Structured in-process fanout for subscribers (metrics, relays, etc.).
    event_bus = shared_state.get("event_bus")
    if event_bus:
        try:
            await event_bus.publish("mcp_log", payload)
        except Exception:
            pass

    session = shared_state.get("_session")
    if not session:
        pending = shared_state.setdefault("_pending_session_logs", [])
        pending.append(payload)
        max_pending = int(shared_state.get("_pending_session_logs_max", 100))
        if len(pending) > max_pending:
            del pending[: len(pending) - max_pending]
        return

    try:
        await session.send_log_message(
            level=level,
            data=data,
            logger="physical-mcp",
        )
    except Exception:
        pass


async def flush_pending_session_logs(shared_state: dict[str, Any] | None) -> int:
    """Flush buffered MCP logs to session once available.

    Returns count of successfully flushed buffered entries.
    """
    if not shared_state:
        return 0

    session = shared_state.get("_session")
    pending: list[dict[str, Any]] = shared_state.get("_pending_session_logs") or []
    if not session or not pending:
        return 0

    flushed = 0
    for payload in pending:
        try:
            await session.send_log_message(
                level=payload.get("level", "info"),
                data=payload.get("data", ""),
                logger=payload.get("logger", "physical-mcp"),
            )
            flushed += 1
        except Exception:
            break

    if flushed:
        del pending[:flushed]
    return flushed


def record_alert_event(
    shared_state: dict[str, Any] | None,
    *,
    event_type: str,
    camera_id: str = "",
    camera_name: str = "",
    rule_id: str = "",
    rule_name: str = "",
    message: str = "",
) -> str:
    """Record alert-like events for replay endpoints (bounded in-memory)."""
    event_id = new_event_id()
    if not shared_state:
        return event_id

    events = shared_state.setdefault("alert_events", [])
    events.append(
        {
            "event_id": event_id,
            "event_type": event_type,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "rule_id": rule_id,
            "rule_name": rule_name,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
    )
    max_events = int(shared_state.get("alert_events_max", 200))
    if len(events) > max_events:
        del events[: len(events) - max_events]
    return event_id


def alert_event_timestamp(
    shared_state: dict[str, Any] | None,
    event_id: str,
) -> str:
    """Resolve recorded alert-event timestamp for a known event id."""
    if not shared_state or not event_id:
        return ""

    for event in reversed(shared_state.get("alert_events", [])):
        if event.get("event_id") == event_id:
            return str(event.get("timestamp", ""))
    return ""
