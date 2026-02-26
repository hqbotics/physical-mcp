"""FastMCP server — tool registrations and lifespan management.

Dual-mode architecture:
  - Server-side reasoning (RECOMMENDED): User provides API key, server calls
    external LLM API directly for scene analysis and rule evaluation.
  - Client-side reasoning (fallback): No API key needed. Camera frames returned
    as ImageContent for the MCP client to analyze.

Multi-camera: Each camera gets its own FrameBuffer, SceneState, and perception
loop. The LLM picks which camera to use based on room names in the instructions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ImageContent, TextContent

from .alert_queue import AlertQueue
from .camera.buffer import FrameBuffer
from .camera.factory import create_camera
from .camera.usb import USBCamera
from .config import CameraConfig, PhysicalMCPConfig
from .events import EventBus
from .health import normalize_camera_health as _normalize_camera_health
from .mcp_logging import (
    alert_event_timestamp as _alert_event_timestamp,
    flush_pending_session_logs as _flush_pending_session_logs,
    record_alert_event as _record_alert_event,
    send_mcp_log as _send_mcp_log,
)
from .memory import MemoryStore
from .notifications import NotificationDispatcher
from .perception.change_detector import ChangeDetector
from .perception.frame_sampler import FrameSampler
from .perception.loop import perception_loop as _perception_loop
from .perception.scene_state import SceneState
from .reasoning.analyzer import FrameAnalyzer
from .reasoning.factory import create_provider as _create_provider
from .rules.engine import RulesEngine
from .rules.store import RulesStore
from .stats import StatsTracker

logger = logging.getLogger("physical-mcp")


def _cam_label(cam_config: CameraConfig | None, camera_id: str = "") -> str:
    """Human-readable camera label: 'Kitchen (usb:0)' or just 'usb:0'."""
    if cam_config and cam_config.name:
        return f"{cam_config.name} ({cam_config.id})"
    return camera_id or "unknown"


async def _emit_fallback_mode_warning(
    shared_state: dict[str, Any] | None,
    *,
    reason: str,
) -> bool:
    """Emit fallback-mode warning and record replay event.

    reason:
      - "startup": emitted once during startup when no provider is configured
      - "runtime_switch": emitted when configure_provider switches from
        server-side mode to client-side fallback mode
    """
    if not shared_state:
        return False

    if reason == "startup":
        replay_message = (
            "Server is running in fallback client-side reasoning mode. "
            "Recommended: configure provider for server-side monitoring."
        )
        log_message = (
            "Server is running in fallback client-side reasoning mode. "
            "Recommended: call configure_provider(provider, api_key, model) "
            "to enable non-blocking server-side monitoring."
        )
    else:
        replay_message = (
            "Runtime switched to fallback client-side reasoning mode. "
            "Recommended default remains server-side: configure provider "
            "for non-blocking continuous monitoring."
        )
        log_message = (
            "Runtime switched to fallback client-side reasoning mode. "
            "Recommended: call configure_provider(provider, api_key, model) "
            "to restore non-blocking server-side monitoring."
        )

    event_id = _record_alert_event(
        shared_state,
        event_type="startup_warning",
        message=replay_message,
    )
    event_timestamp = _alert_event_timestamp(shared_state, event_id)

    await _send_mcp_log(
        shared_state,
        "warning",
        log_message,
        event_type="startup_warning",
        event_id=event_id,
        timestamp=event_timestamp,
    )
    return True


async def _emit_startup_fallback_warning(shared_state: dict[str, Any] | None) -> bool:
    """Emit one-shot startup warning for fallback mode and record replay event."""
    if not shared_state or not shared_state.get("_fallback_warning_pending"):
        return False

    shared_state["_fallback_warning_pending"] = False
    return await _emit_fallback_mode_warning(shared_state, reason="startup")


async def _apply_provider_configuration(
    state: dict[str, Any],
    *,
    provider: str,
    api_key: str,
    model: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    """Apply provider config and return the public configure_provider contract."""
    cfg: PhysicalMCPConfig = state["config"]
    cfg.reasoning.provider = provider
    cfg.reasoning.api_key = api_key
    if model:
        cfg.reasoning.model = model
    if base_url:
        cfg.reasoning.base_url = base_url

    new_provider = _create_provider(cfg)
    analyzer_inst: FrameAnalyzer = state["analyzer"]
    had_provider = analyzer_inst.has_provider
    analyzer_inst.set_provider(new_provider)

    switched_to_fallback = had_provider and not new_provider
    fallback_warning_reason = ""
    if switched_to_fallback:
        await _emit_fallback_mode_warning(state, reason="runtime_switch")
        fallback_warning_reason = "runtime_switch"
    if new_provider:
        state["_fallback_warning_pending"] = False

    mode = "server" if new_provider else "client"
    return {
        "status": "configured",
        "provider": provider or "none",
        "model": new_provider.model_name if new_provider else "none",
        "reasoning_mode": mode,
        "fallback_warning_emitted": switched_to_fallback,
        "fallback_warning_reason": fallback_warning_reason,
    }


def create_server(config: PhysicalMCPConfig) -> FastMCP:
    """Create and configure the FastMCP server with all tools."""

    # Shared state — initialized in lifespan, accessed by tools
    state: dict[str, Any] = {}

    # Determine instructions based on reasoning mode
    has_provider = bool(config.reasoning.provider and config.reasoning.api_key)
    if has_provider:
        instructions_text = (
            "Physical MCP — Ambient perception server with camera access. "
            "RECOMMENDED MODE: server-side reasoning (active). "
            "Monitoring runs in the background and alert notifications appear in-chat "
            "without blocking normal conversation. "
            "Use capture_frame for live view, analyze_now for on-demand analysis, "
            "and add_watch_rule for continuous monitoring."
        )
    else:
        instructions_text = (
            "Physical MCP — Ambient perception server with camera access. "
            "Current mode: client-side reasoning (fallback mode).\n\n"
            "IMPORTANT: For best UX, switch to server-side reasoning by calling "
            "configure_provider(provider, api_key, model). This avoids polling loops "
            "and keeps chat free while monitoring runs in background.\n\n"
            "Fallback monitoring protocol (only when no provider key is available):\n"
            "1. When the user asks you to watch/monitor/alert, call add_watch_rule().\n"
            "2. Poll check_camera_alerts() every 10-15 seconds while rules are active.\n"
            "3. For each alert frame, evaluate rules and call report_rule_evaluation().\n"
            "4. If log notifications say 'CAMERA ALERT', check immediately.\n\n"
            "For one-time viewing, use capture_frame() or analyze_now()."
        )

    def _capture_session(ctx: Context) -> None:
        """Grab the session reference from the first tool call for background use."""
        if state.get("_session") is None:
            state["_session"] = ctx.session
            asyncio.create_task(_flush_pending_session_logs(state))

            if state.get("_fallback_warning_pending"):
                asyncio.create_task(_emit_startup_fallback_warning(state))

            # Auto-start perception loops if rules exist from previous session
            engine = state.get("rules_engine")
            if engine and engine.get_active_rules():
                asyncio.create_task(_ensure_perception_loops())

    async def _ensure_cameras() -> dict:
        """Open ALL enabled cameras. Lazy — only opens cameras not yet open."""
        cameras = state["cameras"]
        for cam_config in config.cameras:
            if not cam_config.enabled:
                continue
            cid = cam_config.id
            if cid in cameras and cameras[cid].is_open():
                continue
            try:
                camera = create_camera(cam_config)
                await camera.open()
                cameras[cid] = camera
                state["camera_configs"][cid] = cam_config
                if cid not in state["frame_buffers"]:
                    state["frame_buffers"][cid] = FrameBuffer(
                        max_frames=config.perception.buffer_size
                    )
                if cid not in state["scene_states"]:
                    state["scene_states"][cid] = SceneState()
                logger.info(f"Camera {_cam_label(cam_config, cid)} opened")
            except Exception as e:
                logger.error(f"Failed to open camera {cid}: {e}")
        return cameras

    async def _get_camera(camera_id: str = "") -> tuple:
        """Get a specific camera, or the first/only camera if none specified.

        Returns (camera, camera_id, cam_config) or (None, '', None).
        """
        cameras = await _ensure_cameras()
        if not cameras:
            return None, "", None

        if camera_id and camera_id in cameras:
            return cameras[camera_id], camera_id, state["camera_configs"][camera_id]

        # Default: first (or only) camera
        first_id = next(iter(cameras))
        return cameras[first_id], first_id, state["camera_configs"][first_id]

    async def _ensure_perception_loops() -> None:
        """Start a perception loop for every open camera that doesn't have one."""
        cameras = await _ensure_cameras()
        for cid, camera in cameras.items():
            task = state["_loop_tasks"].get(cid)
            if task is not None and not task.done():
                continue

            cam_config = state["camera_configs"][cid]
            change_detector = ChangeDetector(
                minor_threshold=config.perception.change_detection.minor_threshold,
                moderate_threshold=config.perception.change_detection.moderate_threshold,
                major_threshold=config.perception.change_detection.major_threshold,
            )
            sampler = FrameSampler(
                change_detector=change_detector,
                heartbeat_interval=config.perception.sampling.heartbeat_interval,
                debounce_seconds=config.perception.sampling.debounce_seconds,
                cooldown_seconds=config.perception.sampling.cooldown_seconds,
            )
            state["_loop_tasks"][cid] = asyncio.create_task(
                _perception_loop(
                    camera,
                    state["frame_buffers"][cid],
                    sampler,
                    state["analyzer"],
                    state["scene_states"][cid],
                    state["rules_engine"],
                    state["stats"],
                    config,
                    state["alert_queue"],
                    notifier=state.get("notifier"),
                    memory=state.get("memory"),
                    shared_state=state,
                    camera_id=cid,
                    camera_name=cam_config.name,
                )
            )
            logger.info(f"Perception loop started for {_cam_label(cam_config, cid)}")

    @asynccontextmanager
    async def app_lifespan(server: FastMCP):
        # LAZY INIT: Camera and perception loop are NOT started here.
        # - Cameras open on first tool call (_ensure_cameras)
        # - Perception loops start only when watch rules are added
        # This prevents the crash loop where Claude Desktop reconnects to MCP
        # and immediately gets flooded with camera frames + perception data.

        rules_engine = RulesEngine()
        rules_store = RulesStore(config.rules_file)
        rules_engine.load_rules(rules_store.load())

        try:
            provider = _create_provider(config)
        except Exception as e:
            logger.warning(
                "Vision provider init failed (%s) — running without analysis", e
            )
            provider = None
        analyzer = FrameAnalyzer(provider)
        # Fire-and-forget: pre-establish HTTP connection pool for faster first call
        asyncio.create_task(analyzer.warmup())
        stats = StatsTracker(
            daily_budget=config.cost_control.daily_budget_usd,
            max_per_hour=config.cost_control.max_analyses_per_hour,
        )
        alert_queue = AlertQueue(max_size=50, ttl_seconds=300)
        memory = MemoryStore(config.memory_file)
        notifier = NotificationDispatcher(config.notifications)
        event_bus = EventBus()

        mode = "server-side" if provider else "client-side"
        logger.info(f"Reasoning mode: {mode} (cameras deferred until first use)")
        if not provider:
            logger.warning(
                "Startup in fallback mode (client-side reasoning). "
                "Recommended default is server-side: configure_provider(...)"
            )

        # Inject memory + camera roster into instructions
        nonlocal instructions_text
        memory_content = memory.read_all()
        if memory_content:
            instructions_text += (
                "\n\n--- PERSISTENT MEMORY (from previous sessions) ---\n"
                + memory_content
            )

        # Camera roster for LLM routing
        enabled_cams = [c for c in config.cameras if c.enabled]
        if enabled_cams:
            cam_ids = [c.id for c in enabled_cams]
            instructions_text += (
                "\n\nAVAILABLE CAMERAS: "
                + ", ".join(cam_ids)
                + "\n\nCall list_cameras() to see what each camera currently "
                "shows, then use camera_id to target the right one(s). "
                "You can use multiple cameras if needed."
            )

        state.update(
            {
                "cameras": {},
                "frame_buffers": {},
                "scene_states": {},
                "camera_configs": {},
                "_loop_tasks": {},
                "rules_engine": rules_engine,
                "rules_store": rules_store,
                "analyzer": analyzer,
                "stats": stats,
                "config": config,
                "alert_queue": alert_queue,
                "memory": memory,
                "notifier": notifier,
                "event_bus": event_bus,
                "_session": None,
                "_fallback_warning_pending": not bool(provider),
                "_pending_session_logs": [],
                "_pending_session_logs_max": 100,
                "camera_health": {},
                "alert_events": [],
                "alert_events_max": 200,
                "_ensure_perception_loops": _ensure_perception_loops,
            }
        )

        # Emit fallback startup warning immediately so Vision API/EventBus
        # observers can see startup mode without requiring an MCP tool call.
        if state.get("_fallback_warning_pending"):
            await _emit_startup_fallback_warning(state)

        # ── Start Vision API (HTTP endpoints for non-MCP systems) ──
        vision_runner = None
        if config.vision_api.enabled:
            try:
                from aiohttp import web as aio_web
                from .vision_api import create_vision_routes

                vision_app = create_vision_routes(state)
                vision_runner = aio_web.AppRunner(vision_app)
                await vision_runner.setup()
                site = aio_web.TCPSite(
                    vision_runner,
                    config.vision_api.host,
                    config.vision_api.port,
                )
                await site.start()
                logger.info(
                    f"Vision API: http://{config.vision_api.host}:"
                    f"{config.vision_api.port}"
                )
            except Exception as e:
                logger.warning(f"Vision API failed to start: {e}")
                vision_runner = None

        # ── Auto-start perception loops if rules exist from previous session ──
        engine = state.get("rules_engine")
        if engine and engine.list_rules():
            asyncio.create_task(_ensure_perception_loops())

        try:
            yield
        finally:
            if vision_runner:
                await vision_runner.cleanup()
            for task in state.get("_loop_tasks", {}).values():
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            for cam in state.get("cameras", {}).values():
                if cam:
                    await cam.close()
            await notifier.close()

    mcp = FastMCP(
        "physical-mcp",
        instructions=instructions_text,
        host=config.server.host,
        port=config.server.port,
        lifespan=app_lifespan,
    )

    # ── Camera Tools ────────────────────────────────────────────

    @mcp.tool()
    async def capture_frame(
        camera_id: str = "",
        quality: int = 85,
        ctx: Context = None,
    ) -> list:
        """Capture and view what the camera currently sees right now.

        Use this when the user asks about their physical space, room,
        surroundings, home, office, or any real-world environment. Also
        use this when you need to see what's happening before setting up
        monitoring.

        Returns a live image from the connected camera that you can see
        and describe.

        Examples of when to use this:
        - "What's in my room right now?"
        - "Show me what the camera sees"
        - "Is anyone in the office?"
        - "What does my front door look like?"

        Args:
            camera_id: Which camera to use (e.g. "usb:0"). Leave empty for
                the default camera. Call list_cameras() to see available
                cameras and their room names.
            quality: JPEG quality 1-100.
        """
        if ctx:
            _capture_session(ctx)
        camera, cid, cam_cfg = await _get_camera(camera_id)
        if not camera:
            return [
                TextContent(
                    type="text",
                    text="Error: No camera available. Run 'physical-mcp setup' to configure.",
                )
            ]

        engine: RulesEngine = state["rules_engine"]
        if engine.get_active_rules():
            await _ensure_perception_loops()

        frame = await camera.grab_frame()
        b64 = frame.to_base64(quality)
        label = _cam_label(cam_cfg, cid)
        return [
            ImageContent(type="image", data=b64, mimeType="image/jpeg"),
            TextContent(
                type="text",
                text=f"Live frame from {label} at {frame.timestamp.isoformat()}. "
                f"Resolution: {frame.resolution[0]}x{frame.resolution[1]}.",
            ),
        ]

    @mcp.tool()
    async def list_cameras() -> dict:
        """List all available camera sources and their status.

        Includes a live scene summary for each camera so you can see
        what each one is currently looking at and pick the right one(s).
        """
        available = USBCamera.enumerate_cameras()
        cameras = await _ensure_cameras()
        scene_states = state.get("scene_states", {})
        active_cameras = []
        for cid, cam in cameras.items():
            cfg = state["camera_configs"].get(cid)
            scene = scene_states.get(cid, SceneState())
            active_cameras.append(
                {
                    "id": cid,
                    "name": cfg.name if cfg else "",
                    "status": "active" if cam.is_open() else "disconnected",
                    "scene_summary": scene.summary,
                    "objects_present": scene.objects_present,
                }
            )
        return {
            "available_hardware": available,
            "configured_cameras": active_cameras,
        }

    @mcp.tool()
    async def get_camera_status(camera_id: str = "") -> dict:
        """Get status of the active camera: resolution, buffer size, uptime.

        Args:
            camera_id: Which camera. Leave empty for default.
        """
        camera, cid, cam_cfg = await _get_camera(camera_id)
        if not camera:
            return {"status": "disconnected"}
        fb = state["frame_buffers"].get(cid)
        frame = await camera.grab_frame()
        return {
            "status": "active",
            "camera_id": cid,
            "name": cam_cfg.name if cam_cfg else "",
            "resolution": f"{frame.resolution[0]}x{frame.resolution[1]}",
            "buffer_size": await fb.size() if fb else 0,
            "latest_frame_seq": frame.sequence_number,
        }

    # ── Scene Tools ─────────────────────────────────────────────

    @mcp.tool()
    async def get_scene_state() -> dict:
        """Get the current scene state summary and system reasoning mode.

        Returns cached scene information from the most recent analysis.
        Also indicates whether the system is in client-side reasoning mode
        (you analyze camera frames) or server-side mode (external API does it).

        This does NOT capture a new frame or make any API calls.
        """
        analyzer_inst: FrameAnalyzer = state["analyzer"]
        queue: AlertQueue = state["alert_queue"]
        scene_states = state.get("scene_states", {})

        if len(scene_states) <= 1:
            # Single camera — flat response for backward compat
            scene = next(iter(scene_states.values()), SceneState())
            result = scene.to_dict()
            result["reasoning_mode"] = (
                "server" if analyzer_inst.has_provider else "client"
            )
            result["pending_alerts"] = await queue.size()
            return result

        # Multi-camera — return per-camera scenes
        scenes = {}
        for cid, scene in scene_states.items():
            cfg = state["camera_configs"].get(cid)
            scenes[cid] = {
                "name": cfg.name if cfg else "",
                **scene.to_dict(),
            }
        return {
            "cameras": scenes,
            "reasoning_mode": "server" if analyzer_inst.has_provider else "client",
            "pending_alerts": await queue.size(),
        }

    @mcp.tool()
    async def get_recent_changes(minutes: int = 5, camera_id: str = "") -> list[dict]:
        """Get a timeline of scene changes detected in the last N minutes.
        Changes are detected locally using perceptual hashing (free, no API cost).

        Args:
            minutes: How far back to look.
            camera_id: Filter to specific camera. Empty = all cameras.
        """
        scene_states = state.get("scene_states", {})

        if camera_id and camera_id in scene_states:
            changes = scene_states[camera_id].get_change_log(minutes=minutes)
            for c in changes:
                c["camera_id"] = camera_id
            return changes

        # All cameras
        all_changes = []
        for cid, scene in scene_states.items():
            cfg = state["camera_configs"].get(cid)
            changes = scene.get_change_log(minutes=minutes)
            for c in changes:
                c["camera_id"] = cid
                c["camera_name"] = cfg.name if cfg else ""
            all_changes.extend(changes)
        all_changes.sort(key=lambda x: x.get("timestamp", ""))
        return all_changes

    @mcp.tool()
    async def analyze_now(question: str = "", camera_id: str = "") -> list:
        """Analyze the current camera frame right now.

        Captures a fresh frame and returns it for analysis. In server-side
        mode (API key configured), the server performs the analysis using
        the configured provider. In client-side mode (no API key), the
        frame is returned as an image for YOU to analyze visually.

        Use this for on-demand analysis when the user asks a specific
        question about the physical space. For continuous monitoring,
        use add_watch_rule() instead.

        Args:
            question: Optional specific question about the scene.
                Examples: "Is the oven on?", "How many people are in the room?"
            camera_id: Which camera to use. Leave empty for default.
        """
        camera, cid, cam_cfg = await _get_camera(camera_id)
        analyzer_inst: FrameAnalyzer = state["analyzer"]
        scene = state["scene_states"].get(cid, SceneState())
        stats_tracker: StatsTracker = state["stats"]

        if not camera:
            return [
                TextContent(
                    type="text",
                    text="Error: No camera available. Run 'physical-mcp setup' to configure.",
                )
            ]

        frame = await camera.grab_frame()
        label = _cam_label(cam_cfg, cid)

        # ── Server-side mode: use configured provider ────────
        if analyzer_inst.has_provider:
            if stats_tracker.budget_exceeded():
                return [TextContent(type="text", text="Error: Daily budget exceeded.")]
            cfg = state["config"]
            result = await analyzer_inst.analyze_scene(
                frame, scene, cfg, question=question
            )
            stats_tracker.record_analysis()

            summary = result.get("summary", "")
            if (
                summary
                and not summary.startswith("Analysis error:")
                and not summary.lstrip().startswith("```")
            ):
                scene.update(
                    summary=summary,
                    objects=result.get("objects", []),
                    people_count=result.get("people_count", 0),
                    change_desc="Manual analysis",
                )
            return [
                TextContent(
                    type="text",
                    text=str(result),
                )
            ]

        # ── Client-side mode: return frame for client AI ─────
        # Return the image with descriptive metadata (NOT imperative instructions).
        # MCP clients like ChatGPT naturally analyze ImageContent — imperative
        # prompts ("Describe what you see...") get echoed to users as system output.
        result = []
        result.append(
            ImageContent(
                type="image",
                data=frame.to_base64(quality=85),
                mimeType="image/jpeg",
            )
        )

        meta = f"Live frame from {label} captured for analysis."
        if scene.summary:
            meta += f" Previous scene: {scene.summary}"
        if question:
            meta += f" User's question: {question}"

        result.append(TextContent(type="text", text=meta))
        return result

    # ── Client-Side Reasoning Tools ────────────────────────────

    @mcp.tool()
    async def check_camera_alerts(ctx: Context = None) -> list:
        """Check for camera scene changes that need your visual analysis.

        Call this tool when you are actively monitoring a physical space
        for the user. The camera's local change detection system (runs
        continuously, no API cost) identifies when something significant
        changes in the scene. This tool returns those changes along with
        camera frame images for YOU to visually analyze.

        When to call this:
        - Periodically while watch rules are active (every 10-30 seconds)
        - When the user asks "what's happening?" or "any updates?"
        - After setting up a new watch rule, to establish a baseline

        Returns camera frames as images you can see, plus the active watch
        rules you need to evaluate. After analyzing, call
        report_rule_evaluation() with your findings.

        Returns quickly with no alerts if the scene is stable.
        """
        if ctx:
            _capture_session(ctx)
        queue: AlertQueue = state["alert_queue"]
        engine: RulesEngine = state["rules_engine"]

        if engine.get_active_rules():
            await _ensure_perception_loops()

        alerts = await queue.pop_all()

        if not alerts:
            active_count = len(engine.get_active_rules())
            msg = f"No pending camera alerts. Scene is stable. Active watch rules: {active_count}."
            return [TextContent(type="text", text=msg)]

        latest = alerts[-1]

        # Cache frame so report_rule_evaluation can attach it to notifications
        state["_last_alert_frame"] = latest.frame_base64

        result = []

        result.append(
            ImageContent(
                type="image",
                data=latest.frame_base64,
                mimeType="image/jpeg",
            )
        )

        cam_label_str = latest.camera_name or latest.camera_id or "unknown"
        rules_text = "\n".join(
            f'  - Rule "{r["name"]}" (id={r["id"]}): {r["condition"]}'
            for r in latest.active_rules
        )

        result.append(
            TextContent(
                type="text",
                text=(
                    f"Camera alert from {cam_label_str}: "
                    f"{latest.change_level} scene change detected.\n"
                    f"Time: {latest.timestamp.isoformat()}\n"
                    f"Change: {latest.change_description}\n"
                    f"Scene context: {latest.scene_context}\n"
                    f"Alert count: {len(alerts)}\n\n"
                    f"Active watch rules:\n{rules_text}"
                ),
            )
        )

        return result

    @mcp.tool()
    async def report_rule_evaluation(evaluations: str) -> dict:
        """Report your visual analysis of watch rules after checking camera alerts.

        After calling check_camera_alerts() and analyzing the camera frame,
        use this tool to report which rules were triggered. This records
        the evaluation, manages cooldown timers, and generates notifications.

        Args:
            evaluations: JSON string with a list of evaluation objects:
                [
                    {
                        "rule_id": "r_abc123",
                        "triggered": true,
                        "confidence": 0.85,
                        "reasoning": "I can see a person at the front door"
                    }
                ]

                Each evaluation must include:
                - rule_id: The rule ID from the alert's active_rules list
                - triggered: true if the condition IS met, false otherwise
                - confidence: 0.0 to 1.0 (only triggered=true with >= 0.7 will alert)
                - reasoning: Brief explanation of what you observed
        """

        engine: RulesEngine = state["rules_engine"]
        # Use first available scene state for context
        scene_states = state.get("scene_states", {})
        scene = (
            next(iter(scene_states.values()), SceneState())
            if scene_states
            else SceneState()
        )
        stats_tracker: StatsTracker = state["stats"]

        try:
            eval_list = (
                json.loads(evaluations) if isinstance(evaluations, str) else evaluations
            )
        except json.JSONDecodeError:
            return {"error": "Invalid JSON in evaluations parameter"}

        if not isinstance(eval_list, list):
            return {"error": "evaluations must be a JSON array"}

        frame_b64 = state.get("_last_alert_frame")
        triggered_alerts = engine.process_client_evaluations(
            eval_list,
            scene,
            frame_base64=frame_b64,
        )
        notifier_inst: NotificationDispatcher = state["notifier"]
        memory_inst: MemoryStore = state["memory"]

        triggered_rules = []
        for alert in triggered_alerts:
            stats_tracker.record_alert()
            triggered_rules.append(
                {
                    "rule_id": alert.rule.id,
                    "rule_name": alert.rule.name,
                    "reasoning": alert.evaluation.reasoning,
                }
            )
            logger.info(
                f"CLIENT ALERT: {alert.rule.name} — {alert.evaluation.reasoning}"
            )
            await notifier_inst.dispatch(alert)
            if "event_bus" in state:
                await state["event_bus"].publish(
                    "alert",
                    {
                        "type": "watch_rule_triggered",
                        "rule_id": alert.rule.id,
                        "rule_name": alert.rule.name,
                        "confidence": alert.evaluation.confidence,
                        "reasoning": alert.evaluation.reasoning,
                    },
                )
            memory_inst.append_event(
                f"ALERT: {alert.rule.name} triggered — {alert.evaluation.reasoning}"
            )
            event_id = _record_alert_event(
                state,
                event_type="watch_rule_triggered",
                rule_id=alert.rule.id,
                rule_name=alert.rule.name,
                message=alert.evaluation.reasoning,
            )
            await _send_mcp_log(
                state,
                "warning",
                f"WATCH RULE TRIGGERED: {alert.rule.name} — {alert.evaluation.reasoning}",
                event_type="watch_rule_triggered",
                rule_id=alert.rule.id,
                event_id=event_id,
                timestamp=_alert_event_timestamp(state, event_id),
            )

        return {
            "processed": len(eval_list),
            "triggered": len(triggered_rules),
            "triggered_rules": triggered_rules,
            "message": (
                f"{len(triggered_rules)} rule(s) triggered. "
                "Notify the user about triggered rules!"
                if triggered_rules
                else "No rules triggered. Scene appears normal."
            ),
        }

    # ── Watch Rules Tools ───────────────────────────────────────

    @mcp.tool()
    async def add_watch_rule(
        name: str,
        condition: str,
        camera_id: str = "",
        priority: str = "medium",
        notification_type: str = "local",
        notification_url: str = "",
        notification_channel: str = "",
        cooldown_seconds: int = 60,
        custom_message: str = "",
        owner_id: str = "",
        owner_name: str = "",
        ctx: Context = None,
    ) -> dict:
        """Set up continuous monitoring for a physical condition or event.

        When the user says things like "watch for...", "alert me if...",
        "monitor...", "let me know when...", "keep an eye on...",
        "notify me if...", or "tell me when...", use this tool to create
        a watch rule.

        The camera will continuously detect scene changes locally (free).
        When a significant change occurs, you will be asked to visually
        evaluate whether the condition is met (via check_camera_alerts).

        Examples:
        - "Watch my kids" -> condition="children leave the room or go near the door"
        - "Alert me if someone comes to the door" -> condition="a person appears at the front door"
        - "Let me know when it starts raining" -> condition="rain is visible through the window"
        - "Keep an eye on the stove" -> condition="something is burning or smoke is visible"
        - "Monitor the baby" -> condition="baby is crying, in distress, or has left the crib"
        - "Tell me if the dog gets on the couch" -> condition="a dog is on the couch"
        - "Say 'hello!' when someone waves" -> condition="person waving", custom_message="hello!"

        Args:
            name: Human-readable name for this rule (e.g., "Front door watch")
            condition: Natural language description of what to watch for
            camera_id: Which camera to monitor (e.g. "usb:0"). Leave empty
                to monitor all cameras. Use list_cameras() to see available
                cameras and pick the right one based on room name.
            priority: "low", "medium", "high", or "critical"
            notification_type: "local" (in-chat only, default), "desktop"
                (OS notification), "ntfy" (push to phone via ntfy.sh),
                "telegram" (direct Telegram Bot API), "discord" (Discord webhook),
                "slack" (Slack webhook), "webhook" (generic HTTP POST),
                "openclaw" (deliver via OpenClaw CLI)
            notification_url: URL for webhook notifications (leave empty otherwise)
            notification_channel: ntfy topic override for this rule (uses
                server default if empty)
            cooldown_seconds: Min seconds between repeated alerts (default 60)
            custom_message: Custom notification text sent when rule triggers.
                When set, this exact text replaces the default alert format.
                Use when the user says "say X when Y happens" or "reply X".
            owner_id: Identity of the rule creator (e.g. "slack:U12345",
                "discord:987654321"). Used for multi-user rule isolation.
                Leave empty for shared/global rules.
            owner_name: Human-readable name of the owner (e.g. "Mom", "Alice").
        """
        engine: RulesEngine = state["rules_engine"]
        store: RulesStore = state["rules_store"]

        if ctx:
            _capture_session(ctx)

        from .rules.models import WatchRule, NotificationTarget, RulePriority

        # Auto-select best notification channel when user didn't override
        if notification_type == "local":
            if config.notifications.telegram_bot_token:
                notification_type = "telegram"
            elif config.notifications.discord_webhook_url:
                notification_type = "discord"
            elif config.notifications.slack_webhook_url:
                notification_type = "slack"
            elif config.notifications.openclaw_channel:
                notification_type = "openclaw"
            elif config.notifications.ntfy_topic:
                notification_type = "ntfy"

        # Resolve notification target fields
        notif_channel = notification_channel if notification_channel else None
        notif_target = None
        if notification_type == "telegram":
            notif_target = config.notifications.telegram_chat_id or None
        elif notification_type == "openclaw":
            notif_channel = notif_channel or config.notifications.openclaw_channel
            notif_target = config.notifications.openclaw_target or None

        rule = WatchRule(
            id=f"r_{uuid.uuid4().hex[:8]}",
            name=name,
            condition=condition,
            camera_id=camera_id,
            priority=RulePriority(priority),
            notification=NotificationTarget(
                type=notification_type,
                url=notification_url if notification_url else None,
                channel=notif_channel,
                target=notif_target,
            ),
            cooldown_seconds=cooldown_seconds,
            custom_message=custom_message if custom_message else None,
            owner_id=owner_id,
            owner_name=owner_name,
        )
        engine.add_rule(rule)
        store.save(engine.list_rules())

        # Log to persistent memory
        memory: MemoryStore = state["memory"]
        cam_cfg = state["camera_configs"].get(camera_id)
        cam_note = f" on {_cam_label(cam_cfg, camera_id)}" if camera_id else ""
        memory.append_event(f"Rule '{name}' created{cam_note}: {condition}")
        memory.set_rule_context(rule.id, f"{name}{cam_note} — {condition}")

        # Start perception loops now that we have an active rule
        await _ensure_perception_loops()

        analyzer_inst: FrameAnalyzer = state["analyzer"]
        mode_hint = ""
        if not analyzer_inst.has_provider:
            mode_hint = (
                " Call check_camera_alerts() periodically to monitor "
                "for scene changes and evaluate this rule."
            )

        return {
            "id": rule.id,
            "name": rule.name,
            "condition": rule.condition,
            "camera_id": camera_id,
            "status": "active",
            "message": f"Watch rule '{rule.name}' created{cam_note}.{mode_hint}",
        }

    @mcp.tool()
    async def list_watch_rules() -> list[dict]:
        """List all configured watch rules and their status."""
        engine: RulesEngine = state["rules_engine"]
        return [r.model_dump(mode="json") for r in engine.list_rules()]

    @mcp.tool()
    async def remove_watch_rule(rule_id: str) -> dict:
        """Remove a watch rule by its ID."""
        engine: RulesEngine = state["rules_engine"]
        store: RulesStore = state["rules_store"]
        removed = engine.remove_rule(rule_id)
        if removed:
            store.save(engine.list_rules())
            queue: AlertQueue = state["alert_queue"]
            await queue.flush_rule(rule_id)
            memory: MemoryStore = state["memory"]
            memory.append_event(f"Rule '{rule_id}' removed")
            memory.remove_rule_context(rule_id)
        return {"removed": removed, "rule_id": rule_id}

    # ── Rule Templates ───────────────────────────────────────────

    @mcp.tool()
    async def list_rule_templates(category: str = "") -> dict:
        """List pre-built rule templates for common monitoring scenarios.

        Returns ready-to-use rule presets that users can pick from instead
        of writing conditions from scratch.

        Categories: security, pets, family, automation, business

        Args:
            category: Filter by category (empty = all templates).
        """
        from .rules.templates import get_categories, list_templates

        templates = list_templates(category if category else None)
        return {
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
            "count": len(templates),
        }

    @mcp.tool()
    async def create_rule_from_template(
        template_id: str,
        camera_id: str = "",
        notification_type: str = "local",
        notification_url: str = "",
        notification_channel: str = "",
        custom_message: str = "",
        owner_id: str = "",
        owner_name: str = "",
        ctx: Context = None,
    ) -> dict:
        """Create a watch rule from a pre-built template.

        Use list_rule_templates() to see available templates, then pass
        the template_id here. The template's condition, priority, and
        cooldown are used automatically.

        Args:
            template_id: Template ID (e.g. "person-detection", "baby-monitor").
            camera_id: Camera to monitor (empty = all cameras).
            notification_type: Notification channel (same as add_watch_rule).
            notification_url: Webhook URL if applicable.
            notification_channel: ntfy topic or channel override.
            custom_message: Custom notification text override.
            owner_id: Rule creator identity for multi-user isolation.
            owner_name: Human-readable owner name.
        """
        from .rules.templates import get_template

        template = get_template(template_id)
        if template is None:
            return {"error": f"Unknown template: {template_id}"}

        # Delegate to add_watch_rule with template values
        return await add_watch_rule(
            name=template.name,
            condition=template.condition,
            camera_id=camera_id,
            priority=template.priority,
            notification_type=notification_type,
            notification_url=notification_url,
            notification_channel=notification_channel,
            cooldown_seconds=template.cooldown_seconds,
            custom_message=custom_message,
            owner_id=owner_id,
            owner_name=owner_name,
            ctx=ctx,
        )

    # ── System Tools ────────────────────────────────────────────

    @mcp.tool()
    async def get_system_stats() -> dict:
        """Get system statistics: reasoning mode, API calls, cost, alerts, uptime."""
        stats_tracker: StatsTracker = state["stats"]
        analyzer_inst: FrameAnalyzer = state["analyzer"]
        queue: AlertQueue = state["alert_queue"]

        return {
            **stats_tracker.summary(),
            "provider": analyzer_inst.provider_info,
            "reasoning_mode": "server" if analyzer_inst.has_provider else "client",
            "pending_alerts": await queue.size(),
            "active_cameras": len(state.get("cameras", {})),
        }

    @mcp.tool()
    async def get_camera_health(camera_id: str = "") -> dict:
        """Get per-camera health snapshot: errors, backoff window, last success.

        Args:
            camera_id: Optional camera id filter (empty = all cameras).
        """
        health_map = state.get("camera_health", {})
        if camera_id:
            return {
                "camera_id": camera_id,
                "health": _normalize_camera_health(
                    camera_id, health_map.get(camera_id)
                ),
            }
        return {
            "cameras": {
                cid: _normalize_camera_health(cid, row)
                for cid, row in health_map.items()
            }
        }

    @mcp.tool()
    async def configure_provider(
        provider: str,
        api_key: str,
        model: str = "",
        base_url: str = "",
    ) -> dict:
        """Set or change the vision model provider at runtime.

        provider: "anthropic" | "openai" | "google" | "openai-compatible"
        api_key: Your API key for the provider
        model: Model name (optional, uses provider default)
        base_url: API base URL (required for openai-compatible)

        Server-side reasoning is the recommended mode for continuous monitoring.
        Set provider to "" and api_key to "" only when you need fallback
        client-side reasoning (you analyze frames, no external API needed).

        Returns:
            status: "configured"
            provider: configured provider name or "none"
            model: provider model name or "none"
            reasoning_mode: "server" | "client"
            fallback_warning_emitted: true when runtime switched server->fallback
            fallback_warning_reason: "runtime_switch" when emitted, else ""
        """
        return await _apply_provider_configuration(
            state,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

    # ── Memory Tools ──────────────────────────────────────────

    @mcp.tool()
    async def read_memory() -> str:
        """Read the persistent memory file containing event history,
        rule context, and user preferences from previous sessions.

        Call this when starting a new session to understand what
        happened before — which rules exist and why, past alerts,
        and user preferences.
        """
        memory: MemoryStore = state["memory"]
        content = memory.read_all()
        if not content:
            return (
                "No memory stored yet. Events will be recorded as you use the system."
            )
        return content

    @mcp.tool()
    async def save_memory(
        event: str = "",
        rule_id: str = "",
        rule_context: str = "",
        preference_key: str = "",
        preference_value: str = "",
    ) -> dict:
        """Save information to persistent memory for future sessions.

        Use this to record important events, rule context, or user
        preferences. All fields are optional — provide whichever
        are relevant.

        Args:
            event: A timestamped event to log (e.g., "User left for vacation")
            rule_id: Rule ID to associate context with
            rule_context: Why the rule was created (stored with rule_id)
            preference_key: Preference name (e.g., "notification_style")
            preference_value: Preference value (e.g., "brief")
        """
        memory: MemoryStore = state["memory"]
        saved = []

        if event:
            memory.append_event(event)
            saved.append(f"event: {event}")

        if rule_id and rule_context:
            memory.set_rule_context(rule_id, rule_context)
            saved.append(f"rule_context: {rule_id}")

        if preference_key and preference_value:
            memory.set_preference(preference_key, preference_value)
            saved.append(f"preference: {preference_key}={preference_value}")

        if not saved:
            return {
                "status": "nothing_saved",
                "message": "Provide at least one field to save.",
            }

        return {"status": "saved", "saved": saved}

    return mcp
