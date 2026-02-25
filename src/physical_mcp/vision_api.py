"""HTTP Vision API — expose camera data to any system.

Simple REST endpoints that serve live camera frames and scene summaries.
Runs alongside the MCP server, sharing the same state dict.

Endpoints:
    GET /             → API overview
    GET /frame        → Latest camera frame (JPEG)
    GET /frame/{id}   → Frame from specific camera
    GET /stream       → MJPEG video stream (works in <img> tags)
    GET /stream/{id}  → MJPEG stream from specific camera
    GET /events       → SSE stream of scene changes
    GET /scene        → All camera scene summaries (JSON)
    GET /scene/{id}   → Scene for specific camera
    GET /changes      → Recent scene changes (supports long-poll)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from aiohttp import web

from .health import normalize_camera_health as _normalize_camera_health

logger = logging.getLogger("physical-mcp")


# ── Pending cameras persistence ────────────────────
_PENDING_PATH = Path("~/.physical-mcp/pending.yaml").expanduser()


def _save_pending(pending: dict[str, Any]) -> None:
    """Persist pending camera registrations to disk."""
    try:
        _PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PENDING_PATH.write_text(
            yaml.dump(pending, default_flow_style=False, sort_keys=False)
        )
    except Exception as e:
        logger.warning("Could not save pending cameras: %s", e)


def _load_pending() -> dict[str, Any]:
    """Load pending camera registrations from disk."""
    if not _PENDING_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(_PENDING_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Could not load pending cameras: %s", e)
        return {}


def _json_error(
    status: int, code: str, message: str, camera_id: str = ""
) -> web.Response:
    """Consistent JSON error payload for API + GPT Action compatibility."""
    payload = {"code": code, "message": message}
    if camera_id:
        payload["camera_id"] = camera_id
    return web.json_response(payload, status=status)


def _parse_int(
    value: str, *, default: int, minimum: int | None = None, maximum: int | None = None
) -> int:
    """Parse integer query params with clamping and fallback default."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _parse_float(
    value: str,
    *,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Parse float query params with clamping and fallback default."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _validated_since(value: str) -> str:
    """Return ISO timestamp when valid, else empty string (ignore bad cursor)."""
    if not value:
        return ""
    candidate = value.strip()
    if not candidate:
        return ""
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return candidate


def _norm_token(value: str) -> str:
    """Normalize filter/replay tokens for resilient matching."""
    return str(value or "").strip().lower()


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse ISO datetime safely; return UTC-normalized naive datetime."""
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None

    # Normalize aware datetimes to naive UTC so comparisons/sorting remain
    # stable across mixed legacy inputs (aware + naive).
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _event_sort_key(event: dict[str, Any]) -> tuple[datetime, str]:
    """Stable replay ordering key (timestamp then event_id)."""
    ts = _parse_iso_datetime(event.get("timestamp", "")) or datetime.min
    return (ts, str(event.get("event_id", "")))


def create_vision_routes(state: dict[str, Any]) -> web.Application:
    """Create aiohttp app with vision API routes.

    Args:
        state: Shared state dict from the MCP server. Contains
            scene_states, frame_buffers, camera_configs, etc.
    """

    # Load any persisted pending cameras from disk
    if "pending_cameras" not in state:
        state["pending_cameras"] = _load_pending()

    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(request: web.Request) -> web.Response:
        """API overview with available cameras and endpoints."""
        cameras = list(state.get("scene_states", {}).keys())
        return web.json_response(
            {
                "name": "physical-mcp",
                "description": "24/7 camera vision API",
                "cameras": cameras,
                "endpoints": {
                    "GET /frame": "Latest camera frame (JPEG)",
                    "GET /frame/{camera_id}": "Frame from specific camera",
                    "GET /stream": "MJPEG video stream (use in <img> tags)",
                    "GET /stream/{camera_id}": "MJPEG stream from specific camera",
                    "GET /events": "SSE stream of scene changes (real-time)",
                    "GET /scene": "Current scene summaries (JSON)",
                    "GET /scene/{camera_id}": "Scene for specific camera",
                    "GET /changes": "Recent changes (?wait=true for long-poll)",
                    "GET /health": "Per-camera health (errors/backoff/last success)",
                    "GET /alerts": "Replay recent alert events",
                    "GET /cameras": "List all cameras with scene state",
                    "POST /cameras/open": "Open all configured cameras on demand",
                    "GET /rules": "List watch rules",
                    "POST /rules": "Create a new watch rule",
                    "DELETE /rules/{rule_id}": "Delete a watch rule",
                    "PUT /rules/{rule_id}/toggle": "Toggle rule on/off",
                },
            }
        )

    @routes.get("/frame")
    @routes.get("/frame/{camera_id}")
    async def get_frame(request: web.Request) -> web.Response:
        """Return latest camera frame as JPEG image."""
        camera_id = request.match_info.get("camera_id", "")
        quality = _parse_int(
            request.query.get("quality", "80"), default=80, minimum=1, maximum=100
        )
        buffers = state.get("frame_buffers", {})

        if not buffers:
            return _json_error(503, "no_cameras_active", "No cameras active")

        # Get specific or first camera
        if camera_id and camera_id in buffers:
            buf = buffers[camera_id]
        elif not camera_id:
            buf = next(iter(buffers.values()))
        else:
            return _json_error(
                404,
                "camera_not_found",
                f"Camera '{camera_id}' not found",
                camera_id=camera_id,
            )

        frame = await buf.latest()

        # Fallback: if buffer is empty (perception loop not running),
        # grab directly from the camera. This lets Flutter app get frames
        # even without active watch rules.
        if frame is None:
            cameras = state.get("cameras", {})
            resolved_id = camera_id or next(iter(buffers.keys()), "")
            cam = cameras.get(resolved_id)
            if cam and cam.is_open():
                try:
                    frame = await cam.grab_frame()
                except Exception:
                    pass

        if frame is None:
            return _json_error(503, "no_frame_available", "No frame available yet")

        jpeg_bytes = frame.to_jpeg_bytes(quality=quality)
        return web.Response(
            body=jpeg_bytes,
            content_type="image/jpeg",
            headers={"Cache-Control": "no-cache"},
        )

    # ── Snapshot (JSON with base64 image — for GPT Actions) ─

    @routes.get("/snapshot")
    @routes.get("/snapshot/{camera_id}")
    async def get_snapshot(request: web.Request) -> web.Response:
        """Return latest frame as JSON with base64-encoded JPEG.

        ChatGPT GPT Actions can't handle binary image responses,
        so this endpoint wraps the frame in JSON with a data URL.
        """
        camera_id = request.match_info.get("camera_id", "")
        quality = _parse_int(
            request.query.get("quality", "60"), default=60, minimum=1, maximum=100
        )
        buffers = state.get("frame_buffers", {})

        if not buffers:
            return _json_error(503, "no_cameras_active", "No cameras active")

        if camera_id and camera_id in buffers:
            buf = buffers[camera_id]
            resolved_id = camera_id
        elif not camera_id:
            resolved_id = next(iter(buffers.keys()))
            buf = buffers[resolved_id]
        else:
            return _json_error(
                404,
                "camera_not_found",
                f"Camera '{camera_id}' not found",
                camera_id=camera_id,
            )

        frame = await buf.latest()

        # Fallback: grab directly from camera if buffer empty
        if frame is None:
            cameras = state.get("cameras", {})
            cam = cameras.get(resolved_id)
            if cam and cam.is_open():
                try:
                    frame = await cam.grab_frame()
                except Exception:
                    pass

        if frame is None:
            return _json_error(503, "no_frame_available", "No frame available yet")

        # Build the public frame URL so ChatGPT can render it inline.
        host = (
            request.headers.get("X-Forwarded-Host")
            or request.headers.get("Host")
            or request.host
        )
        scheme = request.headers.get("X-Forwarded-Proto") or request.scheme
        frame_url = f"{scheme}://{host}/frame/{resolved_id}?quality={quality}"

        return web.json_response(
            {
                "camera_id": resolved_id,
                "image_url": frame_url,
                "width": frame.resolution[0],
                "height": frame.resolution[1],
                "timestamp": frame.timestamp.isoformat(),
                "display": f"![Camera {resolved_id}]({frame_url})",
            }
        )

    # ── MJPEG Stream ────────────────────────────────────────

    @routes.get("/stream")
    @routes.get("/stream/{camera_id}")
    async def mjpeg_stream(request: web.Request) -> web.StreamResponse:
        """Continuous MJPEG video stream — works in any <img> tag or browser.

        Usage:
            <img src="http://localhost:8090/stream" />
            curl http://localhost:8090/stream --output -

        Query params:
            fps:     Target frame rate (default: 5, max: 30)
            quality: JPEG quality 1-100 (default: 60)
        """
        camera_id = request.match_info.get("camera_id", "")
        fps = _parse_int(
            request.query.get("fps", "5"), default=5, minimum=1, maximum=30
        )
        quality = _parse_int(
            request.query.get("quality", "60"), default=60, minimum=1, maximum=100
        )
        buffers = state.get("frame_buffers", {})

        if not buffers:
            return _json_error(503, "no_cameras_active", "No cameras active")

        if camera_id and camera_id in buffers:
            buf = buffers[camera_id]
        elif not camera_id:
            buf = next(iter(buffers.values()))
        else:
            return _json_error(
                404,
                "camera_not_found",
                f"Camera '{camera_id}' not found",
                camera_id=camera_id,
            )

        boundary = "frame"
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                # Disable proxy buffering for low-latency multi-client streaming
                # (notably nginx-compatible reverse proxies).
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(request)

        # Resolve camera for direct grab fallback
        cameras = state.get("cameras", {})
        resolved_id = camera_id or next(iter(buffers.keys()), "")
        cam = cameras.get(resolved_id)

        interval = 1.0 / fps
        try:
            while True:
                frame = await buf.wait_for_frame(timeout=interval)

                # Fallback: grab directly from camera if buffer empty
                if frame is None and cam and cam.is_open():
                    try:
                        frame = await cam.grab_frame()
                    except Exception:
                        pass

                if frame is None:
                    await asyncio.sleep(interval)
                    continue

                jpeg_bytes = frame.to_jpeg_bytes(quality=quality)
                await resp.write(
                    f"--{boundary}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg_bytes)}\r\n\r\n".encode()
                    + jpeg_bytes
                    + b"\r\n"
                )
                await asyncio.sleep(interval)
        except (asyncio.CancelledError, ConnectionResetError):
            pass  # Client disconnected
        return resp

    # ── Server-Sent Events ────────────────────────────────

    @routes.get("/events")
    async def sse_events(request: web.Request) -> web.StreamResponse:
        """Real-time Server-Sent Events stream of scene changes.

        Usage:
            const es = new EventSource('http://localhost:8090/events');
            es.addEventListener('scene', (e) => console.log(JSON.parse(e.data)));
            es.addEventListener('change', (e) => console.log(JSON.parse(e.data)));

        Events emitted:
            scene  — full scene update (summary, objects, people)
            change — scene change detected (timestamp, description)
            ping   — keepalive every 15s

        Query params:
            camera_id: Filter to specific camera (default: all)
        """
        camera_id = request.query.get("camera_id", "")

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await resp.prepare(request)

        # Track what we've already sent to avoid duplicates
        last_update_counts: dict[str, int] = {}
        last_change_times: dict[str, str] = {}

        try:
            while True:
                scenes = state.get("scene_states", {})
                for cid, scene in scenes.items():
                    if camera_id and cid != camera_id:
                        continue

                    # Emit scene event when update_count changes
                    if scene.update_count != last_update_counts.get(cid, -1):
                        last_update_counts[cid] = scene.update_count
                        scene_data = scene.to_dict()
                        cam_cfg = state.get("camera_configs", {}).get(cid)
                        if cam_cfg and cam_cfg.name:
                            scene_data["name"] = cam_cfg.name
                        scene_data["camera_id"] = cid
                        await resp.write(
                            f"event: scene\ndata: {json.dumps(scene_data)}\n\n".encode()
                        )

                    # Emit change events from the change log
                    recent = scene.get_change_log(minutes=1)
                    if recent:
                        latest_ts = recent[-1]["timestamp"]
                        if latest_ts != last_change_times.get(cid, ""):
                            last_change_times[cid] = latest_ts
                            for entry in recent:
                                if entry["timestamp"] > last_change_times.get(
                                    cid + "_sent", ""
                                ):
                                    await resp.write(
                                        f"event: change\n"
                                        f"data: {json.dumps({'camera_id': cid, **entry})}\n\n".encode()
                                    )
                            last_change_times[cid + "_sent"] = latest_ts

                # Keepalive ping
                await resp.write(b": ping\n\n")
                await asyncio.sleep(1.0)
        except (asyncio.CancelledError, ConnectionResetError):
            pass  # Client disconnected
        return resp

    # ── Scene endpoints ───────────────────────────────────

    @routes.get("/scene")
    async def get_scene(request: web.Request) -> web.Response:
        """Return all camera scene summaries as JSON."""
        scenes = state.get("scene_states", {})
        result = {}
        for cid, scene in scenes.items():
            result[cid] = scene.to_dict()
            cam_cfg = state.get("camera_configs", {}).get(cid)
            if cam_cfg and cam_cfg.name:
                result[cid]["name"] = cam_cfg.name
        return web.json_response(
            {
                "cameras": result,
                "timestamp": time.time(),
            }
        )

    @routes.get("/scene/{camera_id}")
    async def get_scene_camera(request: web.Request) -> web.Response:
        """Return scene summary for a specific camera."""
        camera_id = request.match_info["camera_id"]
        scenes = state.get("scene_states", {})
        if camera_id not in scenes:
            return _json_error(
                404,
                "camera_not_found",
                f"Camera '{camera_id}' not found",
                camera_id=camera_id,
            )
        result = scenes[camera_id].to_dict()
        cam_cfg = state.get("camera_configs", {}).get(camera_id)
        if cam_cfg and cam_cfg.name:
            result["name"] = cam_cfg.name
        return web.json_response(result)

    @routes.get("/changes")
    async def get_changes(request: web.Request) -> web.Response:
        """Return recent scene changes across cameras.

        Query params:
            minutes:   How far back to look (default: 5)
            camera_id: Filter to specific camera
            wait:      If "true", long-poll until a new change occurs
            timeout:   Max wait time in seconds for long-poll (default: 30)
            since:     ISO timestamp — only return changes after this time
        """
        minutes = _parse_int(
            request.query.get("minutes", "5"), default=5, minimum=1, maximum=120
        )
        camera_id = request.query.get("camera_id", "").strip()
        wait = request.query.get("wait", "").lower() == "true"
        timeout = _parse_float(
            request.query.get("timeout", "30"), default=30.0, minimum=1.0, maximum=120.0
        )
        since = _validated_since(request.query.get("since", ""))

        def _get_changes() -> dict:
            scenes = state.get("scene_states", {})
            result = {}
            for cid, scene in scenes.items():
                if camera_id and cid != camera_id:
                    continue
                changes = scene.get_change_log(minutes)
                if since:
                    changes = [c for c in changes if c["timestamp"] > since]
                result[cid] = changes
            return result

        if not wait:
            result = _get_changes()
            return web.json_response({"changes": result, "minutes": minutes})

        # Long-poll: wait for new changes
        start = time.monotonic()
        # Snapshot current state to detect new changes
        initial = _get_changes()
        initial_count = sum(len(v) for v in initial.values())

        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.5)
            current = _get_changes()
            current_count = sum(len(v) for v in current.values())
            if current_count > initial_count:
                return web.json_response({"changes": current, "minutes": minutes})

        # Timeout — return whatever we have
        result = _get_changes()
        return web.json_response(
            {"changes": result, "minutes": minutes, "timeout": True}
        )

    @routes.get("/health")
    @routes.get("/health/{camera_id}")
    async def get_health(request: web.Request) -> web.Response:
        """Return per-camera health state (errors/backoff/last success)."""
        camera_id = request.match_info.get("camera_id", "")
        health = state.get("camera_health", {})
        if camera_id:
            return web.json_response(
                {
                    "camera_id": camera_id,
                    "health": _normalize_camera_health(
                        camera_id, health.get(camera_id)
                    ),
                }
            )

        normalized = {
            cid: _normalize_camera_health(cid, row) for cid, row in health.items()
        }
        return web.json_response({"cameras": normalized, "timestamp": time.time()})

    @routes.get("/alerts")
    async def get_alerts(request: web.Request) -> web.Response:
        """Replay recent alert events.

        Query params:
            limit: max events to return (default 50, max 500)
            since: ISO timestamp filter (exclusive)
            camera_id: filter by camera id
            event_type: filter by event type
        """
        limit = _parse_int(
            request.query.get("limit", "50"), default=50, minimum=1, maximum=500
        )
        since = _validated_since(request.query.get("since", ""))
        since_dt = _parse_iso_datetime(since) if since else None
        camera_id = request.query.get("camera_id", "").strip()
        event_type = _norm_token(request.query.get("event_type", ""))

        events = list(state.get("alert_events", []))
        if since_dt:
            # Cursor semantics only apply to valid timestamps; malformed legacy
            # rows are ignored for cursor queries instead of causing crashes or
            # non-deterministic lexical ordering artifacts.
            filtered = []
            for event in events:
                event_ts = _parse_iso_datetime(event.get("timestamp", ""))
                if event_ts and event_ts > since_dt:
                    filtered.append(event)
            events = filtered
        if camera_id:
            events = [
                e for e in events if str(e.get("camera_id", "")).strip() == camera_id
            ]
        if event_type:
            events = [
                e for e in events if _norm_token(e.get("event_type", "")) == event_type
            ]

        # Deterministic replay ordering for clients:
        # oldest → newest by parsed timestamp (malformed timestamps sort first),
        # tie-broken by event_id.
        events.sort(key=_event_sort_key)

        if limit > 0:
            events = events[-limit:]

        return web.json_response(
            {
                "events": events,
                "count": len(events),
                "timestamp": time.time(),
            }
        )

    # ── Dashboard + PWA routes ─────────────────────────
    from .dashboard import DASHBOARD_HTML, MANIFEST_JSON

    @routes.get("/dashboard")
    async def get_dashboard(request: web.Request) -> web.Response:
        """Serve the web dashboard (mobile-friendly, works on iOS)."""
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    @routes.get("/manifest.json")
    async def get_manifest(request: web.Request) -> web.Response:
        """PWA manifest for Add to Home Screen."""
        return web.Response(
            text=MANIFEST_JSON, content_type="application/manifest+json"
        )

    def _rule_to_dict(r: Any) -> dict[str, Any]:
        """Convert a WatchRule to a JSON-serializable dict."""
        return {
            "id": r.id,
            "name": r.name,
            "condition": r.condition,
            "camera_id": r.camera_id,
            "priority": r.priority.value
            if hasattr(r.priority, "value")
            else str(r.priority),
            "enabled": r.enabled,
            "cooldown_seconds": r.cooldown_seconds,
            "notification_type": r.notification.type
            if hasattr(r, "notification")
            else "local",
            "trigger_count": getattr(r, "trigger_count", 0),
            "last_triggered": r.last_triggered.isoformat()
            if r.last_triggered
            else None,
            "created_at": r.created_at.isoformat()
            if hasattr(r, "created_at") and r.created_at
            else None,
            "owner_id": getattr(r, "owner_id", ""),
            "owner_name": getattr(r, "owner_name", ""),
            "custom_message": getattr(r, "custom_message", None),
        }

    @routes.get("/rules")
    async def get_rules(request: web.Request) -> web.Response:
        """Return active watch rules as JSON.

        Query params:
            owner_id: Filter to rules owned by this user (+ global rules with empty owner_id)
        """
        engine = state.get("rules_engine")
        if engine is None:
            return web.json_response([])
        rules = engine.list_rules()
        # Filter by owner_id if provided
        owner_id = request.query.get("owner_id", "").strip()
        if owner_id:
            rules = [
                r
                for r in rules
                if getattr(r, "owner_id", "") == owner_id
                or getattr(r, "owner_id", "") == ""
            ]
        return web.json_response([_rule_to_dict(r) for r in rules])

    @routes.post("/rules")
    async def create_rule(request: web.Request) -> web.Response:
        """Create a new watch rule via API.

        JSON body: {name, condition, camera_id?, priority?, notification_type?,
                     cooldown_seconds?}
        """
        from .rules.models import NotificationTarget, RulePriority, WatchRule
        import uuid

        engine = state.get("rules_engine")
        if engine is None:
            return _json_error(503, "rules_unavailable", "Rules engine not initialized")

        try:
            body = await request.json()
        except Exception:
            return _json_error(400, "invalid_json", "Request body must be JSON")

        name = body.get("name", "").strip()
        condition = body.get("condition", "").strip()
        if not name or not condition:
            return _json_error(
                400,
                "missing_fields",
                "Both 'name' and 'condition' are required",
            )

        # Parse priority
        priority_str = body.get("priority", "medium").lower()
        try:
            priority = RulePriority(priority_str)
        except ValueError:
            priority = RulePriority.MEDIUM

        # Parse notification — auto-fill openclaw from config if available
        notif_type = body.get("notification_type", "local")
        notif_channel = body.get("notification_channel") or None
        notif_target = body.get("notification_target") or None
        config = state.get("config")
        if (
            notif_type == "local"
            and config
            and getattr(getattr(config, "notifications", None), "openclaw_channel", "")
        ):
            notif_type = "openclaw"
            notif_channel = notif_channel or config.notifications.openclaw_channel
            notif_target = notif_target or config.notifications.openclaw_target
        notification = NotificationTarget(
            type=notif_type,
            url=body.get("notification_url") or None,
            channel=notif_channel,
            target=notif_target,
        )

        rule = WatchRule(
            id=f"r_{uuid.uuid4().hex[:8]}",
            name=name,
            condition=condition,
            camera_id=body.get("camera_id", ""),
            priority=priority,
            notification=notification,
            cooldown_seconds=int(body.get("cooldown_seconds", 60)),
            owner_id=body.get("owner_id", ""),
            owner_name=body.get("owner_name", ""),
            custom_message=body.get("custom_message") or None,
        )
        engine.add_rule(rule)
        return web.json_response(_rule_to_dict(rule), status=201)

    @routes.delete("/rules/{rule_id}")
    async def delete_rule(request: web.Request) -> web.Response:
        """Delete a watch rule by ID.

        Query params:
            owner_id: If provided, only delete if the rule belongs to this owner.
                      Returns 403 if the rule belongs to a different owner.
        """
        engine = state.get("rules_engine")
        if engine is None:
            return _json_error(503, "rules_unavailable", "Rules engine not initialized")

        rule_id = request.match_info["rule_id"]
        owner_id = request.query.get("owner_id", "").strip()

        # Ownership check: find the rule first
        if owner_id:
            rules = engine.list_rules()
            target = None
            for r in rules:
                if r.id == rule_id:
                    target = r
                    break
            if target is None:
                return _json_error(404, "rule_not_found", f"Rule '{rule_id}' not found")
            rule_owner = getattr(target, "owner_id", "")
            if rule_owner and rule_owner != owner_id:
                return _json_error(
                    403, "forbidden", f"Rule '{rule_id}' belongs to another user"
                )

        removed = engine.remove_rule(rule_id)
        if not removed:
            return _json_error(404, "rule_not_found", f"Rule '{rule_id}' not found")
        return web.json_response({"deleted": rule_id})

    @routes.put("/rules/{rule_id}/toggle")
    async def toggle_rule(request: web.Request) -> web.Response:
        """Toggle a watch rule on/off."""
        engine = state.get("rules_engine")
        if engine is None:
            return _json_error(503, "rules_unavailable", "Rules engine not initialized")

        rule_id = request.match_info["rule_id"]
        # Find the rule
        rules = engine.list_rules()
        target = None
        for r in rules:
            if r.id == rule_id:
                target = r
                break

        if target is None:
            return _json_error(404, "rule_not_found", f"Rule '{rule_id}' not found")

        target.enabled = not target.enabled
        return web.json_response(_rule_to_dict(target))

    # ── Cameras endpoint ───────────────────────────────

    @routes.get("/cameras")
    async def get_cameras(request: web.Request) -> web.Response:
        """List all cameras with config and current scene state."""
        scene_states = state.get("scene_states", {})
        camera_configs = state.get("camera_configs", {})
        camera_health = state.get("camera_health", {})

        cameras = []
        for cam_id in scene_states:
            config = camera_configs.get(cam_id, {})
            scene = scene_states.get(cam_id)
            health = _normalize_camera_health(camera_health.get(cam_id, {}), cam_id)

            scene_data = None
            if scene:
                summary = scene.summary if hasattr(scene, "summary") else ""
                objects = scene.objects if hasattr(scene, "objects") else []
                people = scene.people_count if hasattr(scene, "people_count") else None
                scene_data = {
                    "summary": summary,
                    "objects": objects,
                    "people_count": people,
                }

            cam_name = cam_id
            if hasattr(config, "name") and config.name:
                cam_name = config.name
            elif isinstance(config, dict) and config.get("name"):
                cam_name = config["name"]

            cameras.append(
                {
                    "id": cam_id,
                    "name": cam_name,
                    "type": "usb"
                    if cam_id.startswith("usb")
                    else "rtsp"
                    if cam_id.startswith("rtsp")
                    else "http"
                    if cam_id.startswith("http")
                    else "unknown",
                    "enabled": health.get("status") != "error",
                    "scene": scene_data,
                }
            )

        return web.json_response(cameras)

    @routes.post("/cameras/open")
    async def open_cameras(request: web.Request) -> web.Response:
        """Open all configured cameras on demand.

        In stdio mode, cameras are lazy-loaded (only opened on MCP tool call).
        This endpoint lets HTTP clients (like the Flutter app) trigger camera
        opening without an MCP connection.
        """
        from .camera.factory import create_camera
        from .camera.buffer import FrameBuffer
        from .perception.scene_state import SceneState

        config = state.get("config")
        if not config:
            return _json_error(500, "no_config", "Server config not loaded")

        opened = []
        failed = []
        cameras_dict = state.setdefault("cameras", {})

        for cam_config in config.cameras:
            if not cam_config.enabled:
                continue
            cid = cam_config.id
            # Skip already-open cameras
            if cid in cameras_dict and cameras_dict[cid].is_open():
                opened.append(cid)
                continue
            try:
                camera = create_camera(cam_config)
                await camera.open()
                cameras_dict[cid] = camera
                state.setdefault("camera_configs", {})[cid] = cam_config
                state.setdefault("frame_buffers", {})[cid] = FrameBuffer(
                    max_frames=config.perception.buffer_size
                )
                state.setdefault("scene_states", {})[cid] = SceneState()
                state.setdefault("camera_health", {})[cid] = {
                    "camera_id": cid,
                    "camera_name": cam_config.name or cid,
                    "consecutive_errors": 0,
                    "backoff_until": None,
                    "last_success_at": None,
                    "last_error": "",
                    "last_frame_at": None,
                    "status": "running",
                }
                opened.append(cid)
            except Exception as e:
                failed.append({"id": cid, "error": str(e)})

        return web.json_response(
            {"opened": opened, "failed": failed, "count": len(opened)}
        )

    # ── Cloud camera frame ingestion ─────────────────────
    @routes.post("/ingest/{camera_id}")
    async def ingest_frame(request: web.Request) -> web.Response:
        """Receive a JPEG frame pushed from a cloud camera.

        Cloud cameras POST raw JPEG bytes with per-camera auth token.
        This endpoint bypasses the global Vision API auth (handled in
        auth_middleware skip list) and uses per-camera token validation.

        Headers:
            Authorization: Bearer <per-camera-token>
        Body:
            Raw JPEG bytes (max 5MB)
        """
        from .camera.cloud import CloudCamera

        camera_id = request.match_info["camera_id"]

        # Find the camera in state
        cameras = state.get("cameras", {})
        camera = cameras.get(camera_id)

        if camera is None:
            # Check pending registrations
            pending = state.get("pending_cameras", {})
            if camera_id in pending:
                return _json_error(
                    403, "camera_pending", f"Camera '{camera_id}' is pending approval"
                )
            return _json_error(
                404, "camera_not_found", f"Camera '{camera_id}' not registered"
            )

        # Must be a CloudCamera
        if not isinstance(camera, CloudCamera):
            return _json_error(
                400, "not_cloud_camera", "Only cloud cameras accept pushed frames"
            )

        # Validate per-camera auth token
        auth_header = request.headers.get("Authorization", "")
        token = (
            auth_header.removeprefix("Bearer ").strip()
            if auth_header.startswith("Bearer ")
            else ""
        )
        if not camera.validate_token(token):
            return _json_error(401, "invalid_camera_token", "Invalid camera auth token")

        # Read JPEG body
        body = await request.read()
        if len(body) == 0:
            return _json_error(400, "empty_body", "No JPEG data in request body")
        if len(body) > 5 * 1024 * 1024:  # 5MB limit
            return _json_error(413, "frame_too_large", "Frame exceeds 5MB limit")

        try:
            frame = await camera.receive_frame(body)
        except ValueError as e:
            return _json_error(400, "invalid_jpeg", str(e))

        # Push to FrameBuffer so streaming endpoints (/frame, /stream) work
        buf = state.get("frame_buffers", {}).get(camera_id)
        if buf and frame:
            await buf.push(frame)

        # Update camera health — track last frame time
        health = state.get("camera_health", {}).get(camera_id)
        if health:
            health["last_frame_at"] = datetime.now(timezone.utc).isoformat()
            health["last_success_at"] = health["last_frame_at"]
            health["consecutive_errors"] = 0
            health["status"] = "running"

        return web.json_response({"status": "ok", "camera_id": camera_id})

    # ── Camera status polling (for camera firmware) ────
    @routes.get("/cameras/{camera_id}/status")
    async def camera_registration_status(request: web.Request) -> web.Response:
        """Camera polls this after registering to learn if it's been accepted.

        Returns:
            - ``{"status": "pending"}`` while waiting for admin approval.
            - ``{"status": "accepted", "auth_token": "...", "ingest_url": "..."}``
              once accepted.
            - 404 if the camera_id is unknown.

        This endpoint is **unauthenticated** — the camera doesn't have a token
        until it's accepted.
        """
        camera_id = request.match_info["camera_id"]

        # Check pending first
        pending = state.get("pending_cameras", {})
        if camera_id in pending:
            return web.json_response(
                {
                    "status": "pending",
                    "camera_id": camera_id,
                    "message": "Waiting for admin approval.",
                }
            )

        # Check active cameras
        cameras = state.get("cameras", {})
        if camera_id in cameras:
            # Find auth_token from the camera object
            camera = cameras[camera_id]
            auth_token_val = getattr(camera, "_auth_token", "")
            return web.json_response(
                {
                    "status": "accepted",
                    "camera_id": camera_id,
                    "auth_token": auth_token_val,
                    "ingest_url": f"/ingest/{camera_id}",
                }
            )

        return _json_error(404, "not_found", f"Camera '{camera_id}' is not registered")

    # ── Camera self-registration ──────────────────────
    @routes.post("/cameras/register")
    async def register_camera(request: web.Request) -> web.Response:
        """Camera self-registration endpoint.

        When a new Decxin camera powers on and connects to WiFi, it
        POSTs here to register itself. The camera goes into "pending"
        state until approved by the dashboard admin.

        JSON body:
            camera_id: Unique camera identifier (e.g., "decxin-A3F2B1")
            name: Human-readable name (e.g., "Front Door Camera")
            capabilities: Optional dict (resolution, fps, night_vision, etc.)
            firmware_version: Optional firmware string
        """
        import secrets as _secrets

        try:
            body = await request.json()
        except Exception:
            return _json_error(400, "invalid_json", "Request body must be JSON")

        camera_id = body.get("camera_id", "").strip()
        if not camera_id:
            return _json_error(400, "missing_camera_id", "camera_id is required")

        # Check if already registered
        cameras = state.get("cameras", {})
        if camera_id in cameras:
            return _json_error(
                409, "already_registered", f"Camera '{camera_id}' is already registered"
            )

        # Check if already pending
        pending = state.setdefault("pending_cameras", {})
        if camera_id in pending:
            return _json_error(
                409,
                "already_pending",
                f"Camera '{camera_id}' is already pending approval",
            )

        auth_token = _secrets.token_urlsafe(32)
        name = body.get("name", camera_id)

        pending[camera_id] = {
            "camera_id": camera_id,
            "name": name,
            "auth_token": auth_token,
            "capabilities": body.get("capabilities", {}),
            "firmware_version": body.get("firmware_version", ""),
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }

        logger.info("Camera '%s' (%s) registered — pending approval", name, camera_id)
        _save_pending(pending)

        return web.json_response(
            {
                "status": "pending",
                "camera_id": camera_id,
                "message": "Registration pending approval. Camera will receive token once accepted.",
            },
            status=202,
        )

    @routes.get("/cameras/pending")
    async def get_pending_cameras(request: web.Request) -> web.Response:
        """List cameras awaiting approval."""
        pending = state.get("pending_cameras", {})
        # Don't expose auth_token in the listing (dashboard shouldn't see it)
        result = []
        for cam_id, info in pending.items():
            result.append(
                {
                    "camera_id": info["camera_id"],
                    "name": info["name"],
                    "capabilities": info.get("capabilities", {}),
                    "firmware_version": info.get("firmware_version", ""),
                    "registered_at": info.get("registered_at", ""),
                    "status": info.get("status", "pending"),
                }
            )
        return web.json_response(result)

    @routes.post("/cameras/{camera_id}/accept")
    async def accept_camera(request: web.Request) -> web.Response:
        """Accept a pending camera registration.

        Creates a CloudCamera instance and starts accepting frames.
        Persists the camera config so it survives restarts.
        """
        from .camera.cloud import CloudCamera
        from .camera.buffer import FrameBuffer
        from .perception.scene_state import SceneState

        camera_id = request.match_info["camera_id"]
        pending = state.get("pending_cameras", {})

        if camera_id not in pending:
            return _json_error(404, "not_found", f"No pending camera '{camera_id}'")

        reg = pending.pop(camera_id)
        _save_pending(pending)
        auth_token = reg["auth_token"]
        name = reg.get("name", camera_id)

        # Create and open CloudCamera
        camera = CloudCamera(
            camera_id=camera_id,
            auth_token=auth_token,
            name=name,
        )
        await camera.open()

        # Register in state
        cameras_dict = state.setdefault("cameras", {})
        cameras_dict[camera_id] = camera

        config = state.get("config")
        buf_size = config.perception.buffer_size if config else 300

        state.setdefault("frame_buffers", {})[camera_id] = FrameBuffer(
            max_frames=buf_size
        )
        state.setdefault("scene_states", {})[camera_id] = SceneState()
        state.setdefault("camera_health", {})[camera_id] = {
            "camera_id": camera_id,
            "camera_name": name,
            "consecutive_errors": 0,
            "backoff_until": None,
            "last_success_at": None,
            "last_error": "",
            "last_frame_at": None,
            "status": "running",
        }

        # Persist to config so camera survives restart
        if config:
            from ..config import CameraConfig as CamCfg, save_config

            cam_cfg = CamCfg(
                id=camera_id,
                name=name,
                type="cloud",
                auth_token=auth_token,
                enabled=True,
            )
            state.setdefault("camera_configs", {})[camera_id] = cam_cfg
            config.cameras.append(cam_cfg)
            try:
                save_config(config)
                logger.info("Camera '%s' config saved to disk", camera_id)
            except Exception as e:
                logger.warning("Could not save camera config: %s", e)

        logger.info("Camera '%s' (%s) accepted — ready for frames", name, camera_id)

        return web.json_response(
            {
                "status": "accepted",
                "camera_id": camera_id,
                "auth_token": auth_token,
                "ingest_url": f"/ingest/{camera_id}",
            },
            status=201,
        )

    @routes.post("/cameras/{camera_id}/reject")
    async def reject_camera(request: web.Request) -> web.Response:
        """Reject a pending camera registration."""
        camera_id = request.match_info["camera_id"]
        pending = state.get("pending_cameras", {})

        if camera_id not in pending:
            return _json_error(404, "not_found", f"No pending camera '{camera_id}'")

        pending.pop(camera_id)
        _save_pending(pending)
        logger.info("Camera '%s' registration rejected", camera_id)
        return web.json_response({"status": "rejected", "camera_id": camera_id})

    # ── Auth middleware ─────────────────────────────────
    config = state.get("config")
    auth_token = (config.vision_api.auth_token if config else "") or ""

    @web.middleware
    async def auth_middleware(
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Optional bearer token authentication."""
        if not auth_token:
            return await handler(request)
        # Skip auth for CORS preflight, PWA manifest, and cloud camera endpoints
        # (cloud camera endpoints use per-camera tokens, not the global API token)
        if (
            request.method == "OPTIONS"
            or request.path == "/manifest.json"
            or request.path.startswith("/ingest/")
            or request.path == "/cameras/register"
            or (
                request.path.startswith("/cameras/")
                and request.path.endswith("/status")
            )
        ):
            return await handler(request)
        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {auth_token}":
            return await handler(request)
        # Also accept ?token= query param (for browser streams/img tags)
        if request.query.get("token") == auth_token:
            return await handler(request)
        return _json_error(401, "unauthorized", "Invalid or missing auth token")

    # ── CORS middleware ──────────────────────────────────
    @web.middleware
    async def cors_middleware(
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Allow any origin — needed for browser extensions, web apps."""
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*, Authorization"
        return resp

    # ── Camera offline detection ───────────────────────
    _offline_task_key = web.AppKey("_offline_task", asyncio.Task)
    # Tracks which cameras we've already alerted about (avoids spam)
    _offline_alerted: set[str] = set()

    async def _offline_checker(app: web.Application) -> None:
        """Background task: check cloud cameras for staleness every 60s.

        If a cloud camera hasn't pushed a frame in 5+ minutes, log a
        warning and update camera_health status to 'offline'.  When the
        camera comes back, clear the alert.
        """
        from .camera.cloud import CloudCamera

        OFFLINE_THRESHOLD_SECONDS = 300  # 5 minutes

        while True:
            await asyncio.sleep(60)
            try:
                cameras = state.get("cameras", {})
                health_dict = state.get("camera_health", {})
                for cam_id, camera in cameras.items():
                    if not isinstance(camera, CloudCamera):
                        continue
                    health = health_dict.get(cam_id, {})
                    last_frame = health.get("last_frame_at")
                    if not last_frame:
                        # Never received a frame — camera may not have started yet
                        continue
                    try:
                        last_dt = datetime.fromisoformat(
                            last_frame.replace("Z", "+00:00")
                        )
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                    except (ValueError, AttributeError):
                        continue

                    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    if elapsed > OFFLINE_THRESHOLD_SECONDS:
                        if cam_id not in _offline_alerted:
                            _offline_alerted.add(cam_id)
                            cam_name = health.get("camera_name", cam_id)
                            health["status"] = "offline"
                            health["last_error"] = (
                                f"No frames received for {int(elapsed)}s"
                            )
                            logger.warning(
                                "Camera '%s' (%s) appears offline — no frames for %ds",
                                cam_name,
                                cam_id,
                                int(elapsed),
                            )
                    else:
                        # Camera is back online — clear alert
                        if cam_id in _offline_alerted:
                            _offline_alerted.discard(cam_id)
                            cam_name = health.get("camera_name", cam_id)
                            health["status"] = "running"
                            health["last_error"] = ""
                            logger.info(
                                "Camera '%s' (%s) is back online",
                                cam_name,
                                cam_id,
                            )
            except Exception as e:
                logger.debug("Offline checker error: %s", e)

    async def _start_offline_checker(app: web.Application) -> None:
        app[_offline_task_key] = asyncio.create_task(_offline_checker(app))

    async def _stop_offline_checker(app: web.Application) -> None:
        task = app.get(_offline_task_key)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = web.Application(middlewares=[auth_middleware, cors_middleware])
    app.add_routes(routes)
    app.on_startup.append(_start_offline_checker)
    app.on_cleanup.append(_stop_offline_checker)
    return app
