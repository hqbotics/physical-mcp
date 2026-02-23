#!/usr/bin/env python3
"""Vision API proxy with built-in perception loop for physical-mcp.

Serves HTTP endpoints AND runs a 24/7 perception loop that:
  - Captures camera frames continuously
  - Detects scene changes locally (perceptual hashing, free)
  - Calls vision LLM on significant changes (cost-controlled)
  - Evaluates watch rules and dispatches notifications (OpenClaw, desktop, etc.)

This is the main long-running daemon. The MCP server (stdio mode) handles
tool calls from Claude Desktop but cannot run background tasks. This proxy
fills that gap with an always-active event loop.

Usage:
    .venv/bin/python vision_proxy.py [--port 8090]
"""

import asyncio
import json
import logging
import secrets
import sys
import time
from pathlib import Path

import yaml
from aiohttp import web

# physical-mcp modules (available via project venv)
from physical_mcp.camera.factory import create_camera
from physical_mcp.camera.buffer import FrameBuffer
from physical_mcp.config import load_config, PhysicalMCPConfig
from physical_mcp.notifications import NotificationDispatcher
from physical_mcp.perception.change_detector import ChangeDetector
from physical_mcp.perception.frame_sampler import FrameSampler
from physical_mcp.perception.scene_state import SceneState
from physical_mcp.reasoning.analyzer import FrameAnalyzer
from physical_mcp.rules.engine import RulesEngine
from physical_mcp.rules.store import RulesStore
from physical_mcp.server import _create_provider
from physical_mcp.stats import StatsTracker

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("vision-proxy")

SCENE_CACHE = Path.home() / ".physical-mcp" / "scene_cache.json"
CONFIG_FILE = Path.home() / ".physical-mcp" / "config.yaml"
RULES_FILE = Path.home() / ".physical-mcp" / "rules.yaml"
FRAME_PATH = Path("/tmp/physical-mcp-frame.jpg")
DEFAULT_PORT = 8090


# ── File helpers (fallbacks when perception loop not running) ──────────


def _load_scene_from_file() -> dict:
    """Load cached scene state from JSON file."""
    if SCENE_CACHE.exists():
        try:
            return json.loads(SCENE_CACHE.read_text())
        except Exception:
            pass
    return {"cameras": {}, "timestamp": time.time()}


def _load_rules() -> list:
    """Load rules from YAML file."""
    if RULES_FILE.exists():
        try:
            data = yaml.safe_load(RULES_FILE.read_text())
            return data.get("rules", []) if data else []
        except Exception:
            pass
    return []


def _save_rules(rules: list) -> None:
    """Save rules to YAML file."""
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(yaml.dump({"rules": rules}, default_flow_style=False))


def _load_config_raw() -> dict:
    """Load config as raw dict (for openclaw auto-fill)."""
    if CONFIG_FILE.exists():
        try:
            return yaml.safe_load(CONFIG_FILE.read_text()) or {}
        except Exception:
            pass
    return {}


def _write_scene_cache(camera_id: str, scene_state: SceneState) -> None:
    """Write scene state to cache file for MCP server + backward compat."""
    try:
        SCENE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "cameras": {
                camera_id: {
                    "summary": scene_state.summary,
                    "objects_present": scene_state.objects_present,
                    "people_count": scene_state.people_count,
                    "last_updated": (
                        scene_state.last_updated.isoformat()
                        if scene_state.last_updated
                        else None
                    ),
                    "last_change": scene_state.last_change_description,
                    "update_count": scene_state.update_count,
                }
            },
            "timestamp": time.time(),
        }
        SCENE_CACHE.write_text(json.dumps(cache_data))
    except Exception as e:
        logger.warning(f"Cache write failed: {e}")


def _force_reload_rules(app: web.Application) -> None:
    """Reload rules from disk into the live RulesEngine."""
    state = app.get("_proxy_state", {})
    engine = state.get("rules_engine")
    store = state.get("rules_store")
    if engine and store:
        try:
            engine.load_rules(store.load())
        except Exception as e:
            logger.warning(f"Rules reload failed: {e}")


# ── Perception loop ───────────────────────────────────────────────────


async def _proxy_perception_loop(state: dict) -> None:
    """Background perception loop — capture, detect, analyze, evaluate, notify.

    Simplified port of server.py _perception_loop() adapted for the proxy.
    Runs as long as the aiohttp app is alive.
    """
    config: PhysicalMCPConfig = state["config"]
    camera = state["camera"]
    camera_id: str = state["camera_id"]
    frame_buffer: FrameBuffer = state["frame_buffer"]
    scene_state: SceneState = state["scene_state"]
    sampler: FrameSampler = state["sampler"]
    analyzer: FrameAnalyzer = state["analyzer"]
    rules_engine: RulesEngine = state["rules_engine"]
    rules_store: RulesStore = state["rules_store"]
    stats: StatsTracker = state["stats"]
    notifier: NotificationDispatcher = state["notifier"]

    interval = 1.0 / max(config.perception.capture_fps, 0.1)
    max_backoff = 45.0
    consecutive_errors = 0
    backoff_until = 0.0
    rules_reload_interval = 5.0
    last_rules_reload = 0.0

    logger.info(
        f"Perception loop started — {config.perception.capture_fps} FPS, "
        f"camera={camera_id}, provider={'yes' if analyzer.has_provider else 'none'}"
    )

    while True:
        try:
            # ── Reload rules from disk periodically ──
            now_mono = time.monotonic()
            if now_mono - last_rules_reload >= rules_reload_interval:
                try:
                    rules_engine.load_rules(rules_store.load())
                    last_rules_reload = now_mono
                except Exception as e:
                    logger.warning(f"Rules reload: {e}")

            # ── Capture frame ──
            try:
                frame = await camera.grab_frame()
            except Exception as e:
                logger.warning(f"Frame grab failed: {e}")
                await asyncio.sleep(interval)
                continue

            await frame_buffer.push(frame)

            # Write frame to /tmp for OpenClaw notifier media attachment
            try:
                FRAME_PATH.write_bytes(frame.to_jpeg_bytes(quality=80))
            except Exception:
                pass

            # ── Change detection + sampling ──
            has_active_rules = len(rules_engine.get_active_rules()) > 0
            should_analyze, change = sampler.should_analyze(frame, has_active_rules)

            if change.level.value != "none":
                scene_state.record_change(change.description)

            # ── Server-side LLM analysis (COMBINED single call) ──
            if should_analyze and analyzer.has_provider and not stats.budget_exceeded():
                # Respect backoff
                if time.monotonic() < backoff_until:
                    await asyncio.sleep(interval)
                    continue

                active_rules = rules_engine.get_active_rules()

                try:
                    # ONE combined call: scene analysis + rule evaluation
                    result = await analyzer.analyze_and_evaluate(
                        frame, scene_state, active_rules, config
                    )
                except Exception as e:
                    consecutive_errors += 1
                    wait = min(5.0 * (2 ** (consecutive_errors - 1)), max_backoff)
                    backoff_until = time.monotonic() + wait
                    logger.error(
                        f"Analysis error #{consecutive_errors}, "
                        f"backoff {wait:.0f}s: {str(e)[:150]}"
                    )
                    await asyncio.sleep(interval)
                    continue

                scene_data = result.get("scene", {})
                evaluations = result.get("evaluations", [])

                # Update scene state with valid data only
                summary = scene_data.get("summary", "")
                if (
                    summary
                    and not summary.startswith("Analysis error:")
                    and not summary.lstrip().startswith("```")
                ):
                    scene_state.update(
                        summary=summary,
                        objects=scene_data.get("objects", []),
                        people_count=scene_data.get("people_count", 0),
                        change_desc=change.description,
                    )
                    _write_scene_cache(camera_id, scene_state)

                stats.record_analysis()
                consecutive_errors = 0
                logger.info(f"Scene: {summary[:120]}")

                # ── Process rule evaluations from combined call ──
                if evaluations and active_rules:
                    frame_b64 = frame.to_base64(quality=config.reasoning.image_quality)
                    alerts = rules_engine.process_evaluations(
                        evaluations, scene_state, frame_base64=frame_b64
                    )
                    for alert in alerts:
                        logger.info(
                            f"🔔 ALERT: {alert.rule.name} — "
                            f"{alert.evaluation.reasoning}"
                        )
                        try:
                            await notifier.dispatch(alert)
                        except Exception as e:
                            logger.error(f"Dispatch failed: {e}")

        except asyncio.CancelledError:
            logger.info("Perception loop stopped")
            break
        except Exception as e:
            logger.error(f"Perception loop error: {e}")

        await asyncio.sleep(interval)


# ── App lifecycle ─────────────────────────────────────────────────────


async def on_startup(app: web.Application) -> None:
    """Open camera, create perception components, start loop."""
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Config load failed: {e}")
        return

    cam_configs = [c for c in config.cameras if c.enabled]
    if not cam_configs:
        logger.warning("No enabled cameras in config — perception loop disabled")
        return

    cam_config = cam_configs[0]
    camera_id = cam_config.id

    # Open camera (retry up to 30s for macOS TCC permission dialog)
    camera = None
    for attempt in range(6):
        try:
            camera = create_camera(cam_config)
            await camera.open()
            logger.info(f"Camera {camera_id} opened")
            break
        except Exception as e:
            if attempt < 5:
                logger.warning(
                    f"Camera open attempt {attempt + 1}/6 failed: {e} "
                    f"(retrying in 5s — check macOS camera permission dialog)"
                )
                await asyncio.sleep(5)
            else:
                logger.error(f"Camera open failed after 6 attempts: {e}")

    if camera is None:
        logger.warning(
            "Running without camera — perception loop disabled, file proxy only"
        )
        return

    # Change detection + sampling
    cd = config.perception.change_detection
    change_detector = ChangeDetector(
        minor_threshold=cd.minor_threshold,
        moderate_threshold=cd.moderate_threshold,
        major_threshold=cd.major_threshold,
    )
    sp = config.perception.sampling
    sampler = FrameSampler(
        change_detector=change_detector,
        heartbeat_interval=sp.heartbeat_interval,
        debounce_seconds=sp.debounce_seconds,
        cooldown_seconds=sp.cooldown_seconds,
    )

    # Vision provider
    provider = _create_provider(config)
    analyzer = FrameAnalyzer(provider)
    if provider:
        logger.info(
            f"Vision provider: {provider.provider_name} / {provider.model_name}"
        )
    else:
        logger.warning(
            "No vision provider — perception loop runs change detection only"
        )

    # Rules
    rules_store = RulesStore(str(config.rules_file))
    rules_engine = RulesEngine()
    try:
        rules_engine.load_rules(rules_store.load())
        logger.info(f"Loaded {len(rules_engine.list_rules())} rules")
    except Exception as e:
        logger.warning(f"Rules load: {e}")

    # Stats + notifications
    stats = StatsTracker(
        daily_budget=config.cost_control.daily_budget_usd,
        max_per_hour=config.cost_control.max_analyses_per_hour,
    )
    notifier = NotificationDispatcher(config.notifications)

    state = {
        "config": config,
        "camera": camera,
        "camera_id": camera_id,
        "camera_name": cam_config.name or camera_id,
        "frame_buffer": FrameBuffer(max_frames=config.perception.buffer_size),
        "scene_state": SceneState(),
        "sampler": sampler,
        "analyzer": analyzer,
        "rules_engine": rules_engine,
        "rules_store": rules_store,
        "stats": stats,
        "notifier": notifier,
    }
    app["_proxy_state"] = state

    # Start perception loop
    app["_perception_task"] = asyncio.create_task(_proxy_perception_loop(state))


async def on_shutdown(app: web.Application) -> None:
    """Stop perception loop, close camera."""
    task = app.get("_perception_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    state = app.get("_proxy_state", {})
    camera = state.get("camera")
    if camera:
        try:
            await camera.close()
        except Exception:
            pass
    notifier = state.get("notifier")
    if notifier:
        try:
            await notifier.close()
        except Exception:
            pass
    logger.info("Proxy shutdown complete")


# ── HTTP handlers ─────────────────────────────────────────────────────


async def handle_health(request: web.Request) -> web.Response:
    state = request.app.get("_proxy_state", {})
    rules = _load_rules()
    camera_id = state.get("camera_id", "usb:0")
    analyzer = state.get("analyzer")

    return web.json_response(
        {
            "cameras": {
                camera_id: {
                    "camera_id": camera_id,
                    "camera_name": state.get("camera_name", camera_id),
                    "consecutive_errors": 0,
                    "backoff_until": None,
                    "last_success_at": None,
                    "last_error": "",
                    "last_frame_at": None,
                    "status": "running" if state.get("camera") else "disconnected",
                    "message": (
                        "Active perception loop"
                        if state.get("camera")
                        else "No camera — file proxy only"
                    ),
                }
            },
            "active_rules": len(rules),
            "perception_loop": bool(request.app.get("_perception_task")),
            "has_provider": analyzer.has_provider if analyzer else False,
            "timestamp": time.time(),
        }
    )


async def handle_scene(request: web.Request) -> web.Response:
    state = request.app.get("_proxy_state", {})
    scene = state.get("scene_state")
    if scene and scene.summary:
        camera_id = state.get("camera_id", "usb:0")
        return web.json_response(
            {
                "cameras": {camera_id: scene.to_dict()},
                "timestamp": time.time(),
            }
        )
    return web.json_response(_load_scene_from_file())


async def handle_frame(request: web.Request) -> web.Response:
    state = request.app.get("_proxy_state", {})
    fb = state.get("frame_buffer")
    if fb:
        frame = await fb.latest()
        if frame:
            quality = int(request.query.get("quality", "85"))
            return web.Response(
                body=frame.to_jpeg_bytes(quality=quality),
                content_type="image/jpeg",
            )
    # Fallback to file
    if FRAME_PATH.exists():
        return web.Response(body=FRAME_PATH.read_bytes(), content_type="image/jpeg")
    return web.json_response({"error": "No frame available"}, status=404)


async def handle_rules_list(request: web.Request) -> web.Response:
    rules = _load_rules()
    return web.json_response({"rules": rules})


async def handle_rules_create(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    condition = data.get("condition", "")
    if not condition:
        return web.json_response({"error": "condition is required"}, status=400)

    rule_id = f"r_{secrets.token_hex(4)}"

    # Auto-fill openclaw from config when notification_type is local
    notif_type = data.get("notification_type", "local")
    notif_channel = data.get("notification_channel")
    notif_target = data.get("notification_target")
    if notif_type == "local":
        cfg = _load_config_raw()
        notifications = cfg.get("notifications", {})
        oc_channel = notifications.get("openclaw_channel", "")
        oc_target = notifications.get("openclaw_target", "")
        if oc_channel:
            notif_type = "openclaw"
            notif_channel = notif_channel or oc_channel
            notif_target = notif_target or oc_target

    new_rule = {
        "id": rule_id,
        "name": data.get("name", "skill-watch"),
        "condition": condition,
        "camera_id": data.get("camera_id", ""),
        "priority": data.get("priority", "medium"),
        "enabled": True,
        "notification": {
            "type": notif_type,
            "url": data.get("notification_url"),
            "channel": notif_channel,
            "target": notif_target,
        },
        "cooldown_seconds": data.get("cooldown_seconds", 60),
        "custom_message": data.get("custom_message") or None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_triggered": None,
    }

    rules = _load_rules()
    rules.append(new_rule)
    _save_rules(rules)

    # Force-reload into live perception loop
    _force_reload_rules(request.app)

    return web.json_response(new_rule, status=201)


async def handle_rules_delete(request: web.Request) -> web.Response:
    rule_id = request.match_info["rule_id"]
    rules = _load_rules()
    new_rules = [r for r in rules if r.get("id") != rule_id]
    if len(new_rules) == len(rules):
        return web.json_response({"error": f"Rule {rule_id} not found"}, status=404)
    _save_rules(new_rules)
    _force_reload_rules(request.app)
    return web.json_response({"deleted": rule_id})


async def handle_rules_toggle(request: web.Request) -> web.Response:
    rule_id = request.match_info["rule_id"]
    rules = _load_rules()
    for r in rules:
        if r.get("id") == rule_id:
            r["enabled"] = not r.get("enabled", True)
            _save_rules(rules)
            _force_reload_rules(request.app)
            return web.json_response(r)
    return web.json_response({"error": f"Rule {rule_id} not found"}, status=404)


async def handle_changes(request: web.Request) -> web.Response:
    """Return recent scene changes."""
    state = request.app.get("_proxy_state", {})
    scene = state.get("scene_state")
    minutes = int(request.query.get("minutes", "5"))
    if scene:
        return web.json_response(
            {
                "changes": scene.get_change_log(minutes),
                "timestamp": time.time(),
            }
        )
    return web.json_response({"changes": [], "timestamp": time.time()})


async def handle_cameras(request: web.Request) -> web.Response:
    state = request.app.get("_proxy_state", {})
    camera_id = state.get("camera_id", "usb:0")
    camera_name = state.get("camera_name", "Built-in Webcam")
    has_camera = state.get("camera") is not None
    return web.json_response(
        {
            "cameras": [
                {
                    "id": camera_id,
                    "type": "usb",
                    "name": camera_name,
                    "status": "running" if has_camera else "disconnected",
                }
            ]
        }
    )


# ── App factory ───────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()

    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    app.middlewares.append(cors_middleware)

    app.router.add_get("/health", handle_health)
    app.router.add_get("/scene", handle_scene)
    app.router.add_get("/frame", handle_frame)
    app.router.add_get("/rules", handle_rules_list)
    app.router.add_post("/rules", handle_rules_create)
    app.router.add_delete("/rules/{rule_id}", handle_rules_delete)
    app.router.add_put("/rules/{rule_id}/toggle", handle_rules_toggle)
    app.router.add_get("/changes", handle_changes)
    app.router.add_get("/cameras", handle_cameras)

    # Lifecycle hooks
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


def main():
    port = DEFAULT_PORT
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    logger.info(f"Vision proxy starting on port {port}")
    logger.info(f"Scene cache: {SCENE_CACHE}")
    logger.info(f"Rules file: {RULES_FILE}")

    app = create_app()
    web.run_app(app, host="127.0.0.1", port=port, print=lambda x: logger.info(x))


if __name__ == "__main__":
    main()
