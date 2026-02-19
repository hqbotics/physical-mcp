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
from typing import Any

from aiohttp import web

logger = logging.getLogger("physical-mcp")


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


def _default_camera_health(camera_id: str) -> dict[str, Any]:
    """Consistent unknown-health shape for cameras without data yet."""
    return {
        "camera_id": camera_id,
        "camera_name": camera_id,
        "consecutive_errors": 0,
        "backoff_until": None,
        "last_success_at": None,
        "last_error": "",
        "last_frame_at": None,
        "status": "unknown",
        "message": "No health data yet.",
    }


def _normalize_camera_health(
    camera_id: str, health: dict[str, Any] | None
) -> dict[str, Any]:
    """Fill missing camera-health keys with safe defaults."""
    base = _default_camera_health(camera_id)
    if not isinstance(health, dict):
        return base
    merged = {**base, **health}
    merged["camera_id"] = str(merged.get("camera_id") or camera_id)
    if not merged.get("camera_name"):
        merged["camera_name"] = merged["camera_id"]
    return merged


def create_vision_routes(state: dict[str, Any]) -> web.Application:
    """Create aiohttp app with vision API routes.

    Args:
        state: Shared state dict from the MCP server. Contains
            scene_states, frame_buffers, camera_configs, etc.
    """

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

        interval = 1.0 / fps
        try:
            while True:
                frame = await buf.wait_for_frame(timeout=interval)
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

    @routes.get("/rules")
    async def get_rules(request: web.Request) -> web.Response:
        """Return active watch rules as JSON."""
        engine = state.get("rules_engine")
        if engine is None:
            return web.json_response({"rules": [], "count": 0})
        rules = engine.list_rules()
        return web.json_response(
            {
                "rules": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "condition": r.condition,
                        "camera_id": r.camera_id,
                        "priority": r.priority.value
                        if hasattr(r.priority, "value")
                        else str(r.priority),
                        "enabled": r.enabled,
                        "cooldown_seconds": r.cooldown_seconds,
                        "last_triggered": r.last_triggered.isoformat()
                        if r.last_triggered
                        else None,
                    }
                    for r in rules
                ],
                "count": len(rules),
            }
        )

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
        # Skip auth for CORS preflight and PWA manifest
        if request.method == "OPTIONS" or request.path == "/manifest.json":
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
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*, Authorization"
        return resp

    app = web.Application(middlewares=[auth_middleware, cors_middleware])
    app.add_routes(routes)
    return app
