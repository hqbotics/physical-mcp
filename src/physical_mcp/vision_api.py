"""HTTP Vision API — expose camera data to any system.

Simple REST endpoints that serve live camera frames and scene summaries.
Runs alongside the MCP server, sharing the same state dict.

Endpoints:
    GET /             → API overview
    GET /frame        → Latest camera frame (JPEG)
    GET /frame/{id}   → Frame from specific camera
    GET /scene        → All camera scene summaries (JSON)
    GET /scene/{id}   → Scene for specific camera
    GET /changes      → Recent scene changes (supports long-poll)
    GET /health       → Per-camera health
    GET /alerts       → Recent alert events
    GET /cameras      → List all cameras
    POST /cameras     → Add a camera dynamically
    GET /rules        → List watch rules
    POST /rules       → Create a watch rule
    DELETE /rules/{id}       → Delete a watch rule
    PUT /rules/{id}/toggle   → Toggle rule on/off
    GET /templates           → List rule templates
    POST /templates/{id}/create → Create rule from template
    GET /discover            → Scan network for cameras
    GET /dashboard           → Self-contained web dashboard
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from .health import normalize_camera_health as _normalize_camera_health

_STATIC_DIR = Path(__file__).parent / "static"

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
                    "GET /scene": "Current scene summaries (JSON)",
                    "GET /scene/{camera_id}": "Scene for specific camera",
                    "GET /changes": "Recent changes (?wait=true for long-poll)",
                    "GET /health": "Per-camera health",
                    "GET /alerts": "Recent alert events",
                    "GET /cameras": "List all cameras",
                    "POST /cameras/open": "Open configured cameras",
                    "GET /rules": "List watch rules",
                    "POST /rules": "Create a watch rule",
                    "DELETE /rules/{rule_id}": "Delete a watch rule",
                    "PUT /rules/{rule_id}/toggle": "Toggle rule on/off",
                    "GET /templates": "List rule templates (?category=security)",
                    "POST /templates/{id}/create": "Create rule from template",
                    "GET /discover": "Scan local network for RTSP cameras",
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
        store = state.get("rules_store")
        if store:
            store.save(engine.list_rules())

        # Start perception loops now that we have an active rule
        ensure_loops = state.get("_ensure_perception_loops")
        if ensure_loops:
            asyncio.ensure_future(ensure_loops())

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
        store = state.get("rules_store")
        if store:
            store.save(engine.list_rules())
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
        store = state.get("rules_store")
        if store:
            store.save(engine.list_rules())
        return web.json_response(_rule_to_dict(target))

    # ── Rule Templates ─────────────────────────────────

    @routes.get("/templates")
    async def list_templates_endpoint(request: web.Request) -> web.Response:
        """List pre-built rule templates for common monitoring scenarios."""
        from .rules.templates import get_categories, list_templates

        category = request.query.get("category", "")
        templates = list_templates(category if category else None)
        return web.json_response(
            {
                "templates": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "icon": t.icon,
                        "description": t.description,
                        "category": t.category,
                        "condition": t.condition,
                        "priority": t.priority,
                        "cooldown_seconds": t.cooldown_seconds,
                    }
                    for t in templates
                ],
                "categories": get_categories(),
            }
        )

    @routes.post("/templates/{template_id}/create")
    async def create_from_template(request: web.Request) -> web.Response:
        """Create a watch rule from a pre-built template."""
        from .rules.templates import get_template

        template_id = request.match_info["template_id"]
        template = get_template(template_id)
        if template is None:
            return _json_error(
                404, "template_not_found", f"No template with id '{template_id}'"
            )

        engine = state.get("rules_engine")
        if engine is None:
            return _json_error(503, "rules_unavailable", "Rules engine not initialized")

        # Parse optional overrides from body
        try:
            body = await request.json()
        except Exception:
            body = {}

        import uuid as _uuid

        from .rules.models import NotificationTarget, RulePriority, WatchRule

        notification_type = body.get("notification_type", "local")
        # Auto-select best notification from config
        cfg = state.get("_config")
        if notification_type == "local" and cfg:
            ncfg = cfg.notifications
            if ncfg.telegram_bot_token:
                notification_type = "telegram"
            elif ncfg.discord_webhook_url:
                notification_type = "discord"
            elif ncfg.slack_webhook_url:
                notification_type = "slack"
            elif ncfg.ntfy_topic:
                notification_type = "ntfy"

        notif_target = None
        notif_channel = body.get("notification_channel") or None
        if notification_type == "telegram" and cfg:
            notif_target = cfg.notifications.telegram_chat_id or None

        rule = WatchRule(
            id=f"r_{_uuid.uuid4().hex[:8]}",
            name=template.name,
            condition=template.condition,
            camera_id=body.get("camera_id", ""),
            priority=RulePriority(template.priority),
            notification=NotificationTarget(
                type=notification_type,
                url=body.get("notification_url") or None,
                channel=notif_channel,
                target=notif_target,
            ),
            cooldown_seconds=template.cooldown_seconds,
            custom_message=body.get("custom_message") or None,
            owner_id=body.get("owner_id", ""),
            owner_name=body.get("owner_name", ""),
        )
        engine.add_rule(rule)
        store = state.get("rules_store")
        if store:
            store.save(engine.list_rules())

        # Start perception loops
        ensure_loops = state.get("_ensure_perception_loops")
        if ensure_loops:
            asyncio.ensure_future(ensure_loops())

        return web.json_response(_rule_to_dict(rule), status=201)

    # ── Discovery endpoint ─────────────────────────────

    @routes.get("/discover")
    async def discover_cameras_endpoint(request: web.Request) -> web.Response:
        """Scan local network for RTSP/ONVIF cameras."""
        from .camera.discover import discover_cameras

        subnet = request.query.get("subnet", "")
        timeout_str = request.query.get("timeout", "2.0")
        try:
            timeout_val = max(0.5, min(10.0, float(timeout_str)))
        except ValueError:
            timeout_val = 2.0

        result = await discover_cameras(subnet=subnet, timeout=timeout_val)

        return web.json_response(
            {
                "cameras": [
                    {
                        "ip": c.ip,
                        "port": c.port,
                        "rtsp_url": c.url,
                        "brand": c.brand,
                        "method": c.method,
                        "name": c.name,
                    }
                    for c in result.cameras
                ],
                "scanned_hosts": result.scanned_hosts,
                "scan_time_seconds": round(result.scan_time_seconds, 1),
                "errors": result.errors,
                "hint": (
                    "Use POST /cameras with the rtsp_url to add a discovered camera."
                    if result.cameras
                    else "No cameras found. Ensure cameras are on the same network."
                ),
            }
        )

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

    @routes.post("/cameras")
    async def add_camera(request: web.Request) -> web.Response:
        """Register and open a new camera at runtime.

        Body: {"type": "rtsp", "url": "rtsp://...", "name": "Kitchen", "id": "kitchen"}
        Opens the camera, adds it to state, and starts the perception loop if available.
        """
        from .camera.factory import create_camera
        from .camera.buffer import FrameBuffer
        from .perception.scene_state import SceneState
        from .config import CameraConfig

        try:
            body = await request.json()
        except Exception:
            return _json_error(400, "invalid_json", "Request body must be JSON")

        cam_url = body.get("url", "")
        cam_type = body.get("type", "")
        if not cam_url or cam_type not in ("rtsp", "http"):
            return _json_error(
                400,
                "invalid_camera",
                "Required: 'url' and 'type' (rtsp or http)",
            )

        cam_id = body.get("id", f"cam:{len(state.get('cameras', {}))}")
        cam_name = body.get("name", cam_id)

        # Check for duplicate
        if cam_id in state.get("cameras", {}):
            return _json_error(409, "duplicate", f"Camera '{cam_id}' already exists")

        cam_config = CameraConfig(
            id=cam_id,
            name=cam_name,
            type=cam_type,
            url=cam_url,
            width=body.get("width", 1280),
            height=body.get("height", 720),
        )

        config = state.get("config")
        try:
            camera = create_camera(cam_config)
            await camera.open()
        except Exception as e:
            return _json_error(502, "camera_open_failed", f"Failed to open camera: {e}")

        cameras_dict = state.setdefault("cameras", {})
        cameras_dict[cam_id] = camera
        state.setdefault("camera_configs", {})[cam_id] = cam_config
        state.setdefault("frame_buffers", {})[cam_id] = FrameBuffer(
            max_frames=config.perception.buffer_size if config else 300
        )
        state.setdefault("scene_states", {})[cam_id] = SceneState()
        state.setdefault("camera_health", {})[cam_id] = {
            "camera_id": cam_id,
            "camera_name": cam_name,
            "consecutive_errors": 0,
            "backoff_until": None,
            "last_success_at": None,
            "last_error": "",
            "last_frame_at": None,
            "status": "running",
        }

        # Start perception loop for the new camera if rules exist
        engine = state.get("rules_engine")
        ensure_loops = state.get("_ensure_perception_loops")
        if ensure_loops and engine and engine.get_active_rules():
            asyncio.ensure_future(ensure_loops())

        return web.json_response(
            {
                "id": cam_id,
                "name": cam_name,
                "type": cam_type,
                "status": "opened",
                "message": f"Camera '{cam_name}' registered and streaming",
            },
            status=201,
        )

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
        # Skip auth for CORS preflight and health checks
        if request.method == "OPTIONS":
            return await handler(request)
        if request.path == "/health" or request.path.startswith("/health/"):
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

    # ── Dashboard ───────────────────────────────────────

    @routes.get("/dashboard")
    async def dashboard(request: web.Request) -> web.Response:
        """Serve the web dashboard (single-page, self-contained HTML)."""
        token = state.get("_config", None)
        auth_token = ""
        if token:
            auth_token = token.vision_api.auth_token or ""
        # Allow token from query param for easy sharing
        qt = request.query.get("token", "")
        if qt:
            auth_token = qt

        html = _build_dashboard_html(auth_token)
        return web.Response(text=html, content_type="text/html")

    # ── Factory Blueprint ────────────────────────────────

    @routes.get("/factory")
    async def factory_view(request: web.Request) -> web.Response:
        """Serve the interactive Factorio-style factory blueprint."""
        token_cfg = state.get("_config", None)
        auth_token = ""
        if token_cfg:
            auth_token = token_cfg.vision_api.auth_token or ""
        qt = request.query.get("token", "")
        if qt:
            auth_token = qt
        html_path = _STATIC_DIR / "factory.html"
        html = html_path.read_text()
        html = html.replace("{{AUTH_TOKEN}}", auth_token)
        return web.Response(text=html, content_type="text/html")

    app = web.Application(middlewares=[auth_middleware, cors_middleware])
    app.add_routes(routes)
    return app


def _build_dashboard_html(auth_token: str = "") -> str:
    """Generate self-contained dashboard HTML with DJI-style dark theme."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0A0A0F">
<title>physical-mcp Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --bg: #0A0A0F; --surface: #141419; --border: #2A2A35;
  --text: #E8E8ED; --dim: #8B8B96; --accent: #0971CE;
  --green: #34C759; --red: #FF453A; --orange: #FF9F0A; --yellow: #FFD60A;
}}
body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', system-ui, sans-serif; min-height: 100vh; }}
.header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 18px; font-weight: 600; }}
.header .status {{ display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--dim); }}
.header .dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--green); }}
.header .dot.off {{ background: var(--red); }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px; max-width: 1400px; margin: 0 auto; }}
@media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
.card-header {{ padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }}
.card-header h2 {{ font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--dim); }}
.card-body {{ padding: 16px; }}
.camera-feed {{ width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 8px; object-fit: contain; }}
.camera-feed.no-feed {{ display: flex; align-items: center; justify-content: center; color: var(--dim); font-size: 14px; }}
.scene-text {{ font-size: 14px; line-height: 1.6; color: var(--text); }}
.scene-meta {{ font-size: 12px; color: var(--dim); margin-top: 8px; }}
.rule {{ display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }}
.rule:last-child {{ border-bottom: none; }}
.rule .priority {{ width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }}
.rule .priority.low {{ background: var(--accent); }}
.rule .priority.medium {{ background: var(--yellow); }}
.rule .priority.high {{ background: var(--orange); }}
.rule .priority.critical {{ background: var(--red); }}
.rule .info {{ flex: 1; }}
.rule .name {{ font-size: 14px; font-weight: 500; }}
.rule .condition {{ font-size: 12px; color: var(--dim); margin-top: 2px; }}
.rule .badge {{ font-size: 11px; padding: 2px 8px; border-radius: 10px; background: var(--border); color: var(--dim); }}
.rule .badge.active {{ background: rgba(52,199,89,0.15); color: var(--green); }}
.alert {{ padding: 10px 0; border-bottom: 1px solid var(--border); }}
.alert:last-child {{ border-bottom: none; }}
.alert .alert-time {{ font-size: 11px; color: var(--dim); }}
.alert .alert-name {{ font-size: 14px; font-weight: 500; margin-top: 2px; }}
.alert .alert-reason {{ font-size: 12px; color: var(--dim); margin-top: 2px; }}
.templates {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }}
.tpl-btn {{ background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer; text-align: center; transition: all 0.15s; }}
.tpl-btn:hover {{ border-color: var(--accent); background: rgba(9,113,206,0.08); }}
.tpl-btn .icon {{ font-size: 20px; }}
.tpl-btn .label {{ font-size: 11px; color: var(--dim); margin-top: 4px; }}
.empty {{ color: var(--dim); font-size: 13px; text-align: center; padding: 20px; }}
.full-width {{ grid-column: 1 / -1; }}
#toast {{ position: fixed; bottom: 20px; right: 20px; background: var(--green); color: #fff; padding: 10px 20px; border-radius: 8px; font-size: 14px; display: none; z-index: 100; }}
</style>
</head>
<body>
<div class="header">
  <h1>physical-mcp</h1>
  <div class="status"><div class="dot" id="statusDot"></div><span id="statusText">Connecting...</span></div>
</div>
<div class="grid">
  <div class="card">
    <div class="card-header"><h2>Camera Feed</h2><span id="cameraName" style="font-size:12px;color:var(--dim)"></span></div>
    <div class="card-body">
      <img id="cameraFeed" class="camera-feed" alt="Camera feed" style="display:none">
      <div id="noFeed" class="camera-feed no-feed">No camera connected</div>
    </div>
  </div>
  <div class="card">
    <div class="card-header"><h2>Scene Analysis</h2><span id="sceneTime" style="font-size:12px;color:var(--dim)"></span></div>
    <div class="card-body">
      <div id="sceneText" class="scene-text empty">Waiting for analysis...</div>
      <div id="sceneMeta" class="scene-meta"></div>
    </div>
  </div>
  <div class="card">
    <div class="card-header"><h2>Watch Rules</h2><span id="ruleCount" style="font-size:12px;color:var(--dim)"></span></div>
    <div class="card-body" id="rulesList"><div class="empty">No rules configured</div></div>
  </div>
  <div class="card">
    <div class="card-header"><h2>Recent Alerts</h2></div>
    <div class="card-body" id="alertsList"><div class="empty">No alerts yet</div></div>
  </div>
  <div class="card full-width">
    <div class="card-header"><h2>Quick Add Rule</h2></div>
    <div class="card-body">
      <div class="templates" id="templateGrid"></div>
    </div>
  </div>
</div>
<div id="toast"></div>
<script>
const TOKEN = '{auth_token}';
const BASE = window.location.origin;
const headers = TOKEN ? {{'Authorization': 'Bearer ' + TOKEN}} : {{}};

function api(path) {{ return fetch(BASE + path, {{headers}}).then(r => r.json()); }}
function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}}

async function refresh() {{
  try {{
    const [health, scene, rules, alerts, templates] = await Promise.all([
      api('/health'), api('/scene'), api('/rules'), api('/alerts'), api('/templates')
    ]);

    // Status
    const cams = Object.keys(health.cameras || {{}});
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');
    if (cams.length > 0) {{
      dot.className = 'dot'; txt.textContent = cams.length + ' camera' + (cams.length > 1 ? 's' : '') + ' active';
    }} else {{
      dot.className = 'dot off'; txt.textContent = 'No cameras';
    }}

    // Camera feed
    const feed = document.getElementById('cameraFeed');
    const noFeed = document.getElementById('noFeed');
    if (cams.length > 0) {{
      feed.src = BASE + '/frame?' + (TOKEN ? 'token=' + TOKEN : '') + '&t=' + Date.now();
      feed.style.display = 'block'; noFeed.style.display = 'none';
      document.getElementById('cameraName').textContent = cams[0];
    }} else {{
      feed.style.display = 'none'; noFeed.style.display = 'flex';
    }}

    // Scene
    const scenes = scene.cameras || {{}};
    const sceneKeys = Object.keys(scenes);
    if (sceneKeys.length > 0) {{
      const s = scenes[sceneKeys[0]];
      document.getElementById('sceneText').textContent = s.summary || 'No analysis yet';
      document.getElementById('sceneText').className = 'scene-text';
      const objs = (s.objects_present || []).join(', ');
      const ppl = s.people_count || 0;
      document.getElementById('sceneMeta').textContent = (objs ? 'Objects: ' + objs + ' | ' : '') + 'People: ' + ppl;
      if (s.last_updated) {{
        const ago = Math.round((Date.now()/1000) - new Date(s.last_updated).getTime()/1000);
        document.getElementById('sceneTime').textContent = ago < 60 ? ago + 's ago' : Math.round(ago/60) + 'm ago';
      }}
    }}

    // Rules
    const rl = document.getElementById('rulesList');
    const ruleData = Array.isArray(rules) ? rules : (rules.rules || []);
    document.getElementById('ruleCount').textContent = ruleData.length + ' rules';
    if (ruleData.length === 0) {{
      rl.innerHTML = '<div class="empty">No rules configured</div>';
    }} else {{
      rl.innerHTML = ruleData.map(r => `
        <div class="rule">
          <div class="priority ${{r.priority}}"></div>
          <div class="info">
            <div class="name">${{r.name}}</div>
            <div class="condition">${{r.condition}}</div>
          </div>
          <span class="badge ${{r.enabled ? 'active' : ''}}">${{r.enabled ? 'Active' : 'Paused'}}</span>
        </div>
      `).join('');
    }}

    // Alerts
    const al = document.getElementById('alertsList');
    const alertData = Array.isArray(alerts) ? alerts : (alerts.alerts || []);
    if (alertData.length === 0) {{
      al.innerHTML = '<div class="empty">No alerts yet</div>';
    }} else {{
      al.innerHTML = alertData.slice(0, 10).map(a => `
        <div class="alert">
          <div class="alert-time">${{new Date(a.timestamp || a.created_at).toLocaleTimeString()}}</div>
          <div class="alert-name">${{a.rule_name || a.name || 'Alert'}}</div>
          <div class="alert-reason">${{a.reasoning || a.description || ''}}</div>
        </div>
      `).join('');
    }}

    // Templates
    const tg = document.getElementById('templateGrid');
    const tplData = templates.templates || [];
    tg.innerHTML = tplData.map(t => `
      <div class="tpl-btn" onclick="createFromTemplate('${{t.id}}', '${{t.name}}')">
        <div class="icon">${{t.icon}}</div>
        <div class="label">${{t.name}}</div>
      </div>
    `).join('');

  }} catch(e) {{
    document.getElementById('statusDot').className = 'dot off';
    document.getElementById('statusText').textContent = 'Error: ' + e.message;
  }}
}}

async function createFromTemplate(id, name) {{
  try {{
    const resp = await fetch(BASE + '/templates/' + id + '/create', {{
      method: 'POST', headers: {{'Content-Type': 'application/json', ...headers}}, body: '{{}}'
    }});
    if (resp.ok) {{
      showToast('Rule created: ' + name);
      setTimeout(refresh, 500);
    }} else {{
      const err = await resp.json();
      showToast('Error: ' + (err.message || 'Failed'));
    }}
  }} catch(e) {{ showToast('Error: ' + e.message); }}
}}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""
