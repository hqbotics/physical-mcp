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
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ImageContent, TextContent

from .alert_queue import AlertQueue
from .camera.base import Frame
from .camera.buffer import FrameBuffer
from .camera.factory import create_camera
from .camera.usb import USBCamera
from .config import CameraConfig, PhysicalMCPConfig
from .memory import MemoryStore
from .notifications import NotificationDispatcher
from .perception.change_detector import ChangeDetector
from .perception.frame_sampler import FrameSampler
from .perception.scene_state import SceneState
from .reasoning.analyzer import FrameAnalyzer
from .reasoning.providers.base import VisionProvider
from .rules.engine import RulesEngine
from .rules.models import PendingAlert
from .rules.store import RulesStore
from .stats import StatsTracker

logger = logging.getLogger("physical-mcp")


def _cam_label(cam_config: CameraConfig | None, camera_id: str = "") -> str:
    """Human-readable camera label: 'Kitchen (usb:0)' or just 'usb:0'."""
    if cam_config and cam_config.name:
        return f"{cam_config.name} ({cam_config.id})"
    return camera_id or "unknown"


def _new_event_id() -> str:
    """Generate a short event id for MCP notifications."""
    return f"evt_{uuid.uuid4().hex[:10]}"


async def _send_mcp_log(
    shared_state: dict[str, Any] | None,
    level: str,
    message: str,
    event_type: str = "system",
    camera_id: str = "",
    rule_id: str = "",
    event_id: str = "",
) -> None:
    """Best-effort MCP log emission to surface background alerts in chat clients."""
    if not shared_state:
        return
    session = shared_state.get("_session")
    if not session:
        return

    eid = event_id or _new_event_id()
    parts = [f"PMCP[{event_type.upper()}]", f"event_id={eid}"]
    if camera_id:
        parts.append(f"camera_id={camera_id}")
    if rule_id:
        parts.append(f"rule_id={rule_id}")
    prefix = " | ".join(parts)

    try:
        await session.send_log_message(
            level=level,
            data=f"{prefix} | {message}",
            logger="physical-mcp",
        )
    except Exception:
        pass


def _record_alert_event(
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
    event_id = _new_event_id()
    if not shared_state:
        return event_id

    events = shared_state.setdefault("alert_events", [])
    events.append({
        "event_id": event_id,
        "event_type": event_type,
        "camera_id": camera_id,
        "camera_name": camera_name,
        "rule_id": rule_id,
        "rule_name": rule_name,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    })
    max_events = int(shared_state.get("alert_events_max", 200))
    if len(events) > max_events:
        del events[: len(events) - max_events]
    return event_id


def _create_provider(config: PhysicalMCPConfig) -> VisionProvider | None:
    """Create the configured vision provider, or None if not configured."""
    r = config.reasoning
    if not r.provider or not r.api_key:
        return None

    if r.provider == "anthropic":
        from .reasoning.providers.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=r.api_key, model=r.model)
    elif r.provider == "openai":
        from .reasoning.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(api_key=r.api_key, model=r.model)
    elif r.provider == "openai-compatible":
        from .reasoning.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(api_key=r.api_key, model=r.model, base_url=r.base_url)
    elif r.provider == "google":
        from .reasoning.providers.google import GoogleProvider
        return GoogleProvider(api_key=r.api_key, model=r.model)
    else:
        logger.warning(f"Unknown provider: {r.provider}")
        return None


async def _evaluate_via_sampling(
    session,
    frame: "Frame",
    change,
    active_rules: list,
    scene_state: "SceneState",
    rules_engine: "RulesEngine",
    stats: "StatsTracker",
    config: "PhysicalMCPConfig",
    notifier: "NotificationDispatcher | None",
    memory: "MemoryStore | None",
    shared_state: dict[str, Any] | None = None,
    camera_id: str = "",
    camera_name: str = "",
) -> None:
    """Use MCP sampling to ask the client's LLM to evaluate watch rules."""
    from mcp.types import ModelPreferences, SamplingMessage

    frame_b64 = frame.to_base64(quality=config.reasoning.image_quality)
    cam_label = f"{camera_name} ({camera_id})" if camera_name else camera_id

    rules_text = "\n".join(
        f'- Rule "{r.name}" (id={r.id}): {r.condition}'
        for r in active_rules
    )

    try:
        result = await session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=[
                        ImageContent(type="image", data=frame_b64, mimeType="image/jpeg"),
                        TextContent(
                            type="text",
                            text=(
                                f"Camera: {cam_label}\n"
                                f"Scene change: {change.level.value} — {change.description}\n\n"
                                f"Active watch rules:\n{rules_text}\n\n"
                                "For each rule, respond with a JSON array:\n"
                                '[{"rule_id": "...", "triggered": true/false, '
                                '"confidence": 0.0-1.0, "reasoning": "..."}]\n'
                                "Only mark triggered=true if you are confident (>= 0.7)."
                            ),
                        ),
                    ],
                )
            ],
            max_tokens=500,
            system_prompt=(
                "You are a camera monitoring system. Analyze the camera frame "
                "and evaluate each watch rule. Respond ONLY with a JSON array. "
                "Be conservative — only trigger if clearly visible."
            ),
            model_preferences=ModelPreferences(
                costPriority=1.0,
                speedPriority=1.0,
                intelligencePriority=0.3,
            ),
        )
    except Exception as e:
        logger.error(f"Sampling create_message failed: {e}")
        return

    # Parse the LLM's response
    try:
        response_text = (
            result.content.text
            if hasattr(result.content, "text")
            else str(result.content)
        )
        json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
        if not json_match:
            logger.debug(f"No JSON array in sampling response: {response_text[:200]}")
            return

        evaluations = json.loads(json_match.group())
        alerts = rules_engine.process_client_evaluations(
            evaluations, scene_state, frame_base64=frame_b64,
        )
        for alert in alerts:
            stats.record_alert()
            logger.info(
                f"SAMPLING ALERT [{cam_label}]: {alert.rule.name} — {alert.evaluation.reasoning}"
            )
            if notifier:
                await notifier.dispatch(alert)
            if memory:
                memory.append_event(
                    f"ALERT: {alert.rule.name} triggered — "
                    f"{alert.evaluation.reasoning}"
                )
            event_id = _record_alert_event(
                shared_state,
                event_type="watch_rule_triggered",
                camera_id=camera_id,
                camera_name=camera_name,
                rule_id=alert.rule.id,
                rule_name=alert.rule.name,
                message=alert.evaluation.reasoning,
            )
            await _send_mcp_log(
                shared_state,
                "warning",
                (
                    f"WATCH RULE TRIGGERED [{cam_label}]: {alert.rule.name} — "
                    f"{alert.evaluation.reasoning}"
                ),
                event_type="watch_rule_triggered",
                camera_id=camera_id,
                rule_id=alert.rule.id,
                event_id=event_id,
            )
    except Exception as e:
        logger.error(f"Sampling evaluation parse error: {e}")


async def _perception_loop(
    camera: USBCamera,
    frame_buffer: FrameBuffer,
    sampler: FrameSampler,
    analyzer: FrameAnalyzer,
    scene_state: SceneState,
    rules_engine: RulesEngine,
    stats: StatsTracker,
    config: PhysicalMCPConfig,
    alert_queue: AlertQueue,
    notifier: NotificationDispatcher | None = None,
    memory: MemoryStore | None = None,
    shared_state: dict[str, Any] | None = None,
    camera_id: str = "",
    camera_name: str = "",
) -> None:
    """Background perception loop — one per camera.

    Dual-mode behavior:
    - Always captures frames and runs local change detection (free, <5ms)
    - Server-side mode (has provider): calls external LLM API for analysis
    - Client-side mode (no provider): queues PendingAlert for client to poll
    - No watch rules = zero API calls / zero alerts (just local monitoring)
    """
    interval = 1.0 / config.perception.capture_fps
    max_backoff = 45.0
    consecutive_errors = 0
    backoff_until = 0.0
    import time

    cam_label = f"{camera_name} ({camera_id})" if camera_name else camera_id

    health = None
    if shared_state is not None:
        health = shared_state.setdefault("camera_health", {}).setdefault(
            camera_id,
            {
                "camera_id": camera_id,
                "camera_name": camera_name,
                "consecutive_errors": 0,
                "backoff_until": None,
                "last_success_at": None,
                "last_error": "",
                "last_frame_at": None,
                "status": "starting",
            },
        )

    while True:
        try:
            frame = await camera.grab_frame()
            await frame_buffer.push(frame)
            if health is not None:
                health["last_frame_at"] = datetime.now().isoformat()
                if health.get("status") == "starting":
                    health["status"] = "running"

            has_active_rules = len(rules_engine.get_active_rules()) > 0
            should_analyze, change = sampler.should_analyze(frame, has_active_rules)

            if change.level.value != "none":
                scene_state.record_change(change.description)

            # ── Server-side reasoning mode ───────────────────────
            if should_analyze and analyzer.has_provider and not stats.budget_exceeded():
                now = time.monotonic()
                if now < backoff_until:
                    remaining = backoff_until - now
                    if health is not None:
                        health["status"] = "backoff"
                    if consecutive_errors <= 3:
                        logger.info(f"[{cam_label}] In backoff, retry in {remaining:.0f}s")
                    await asyncio.sleep(interval)
                    continue

                try:
                    scene_data = await analyzer.analyze_scene(frame, scene_state, config)
                except Exception as e:
                    consecutive_errors += 1
                    wait = min(5.0 * (2 ** (consecutive_errors - 1)), max_backoff)
                    backoff_until = time.monotonic() + wait
                    if health is not None:
                        health["consecutive_errors"] = consecutive_errors
                        health["backoff_until"] = (
                            datetime.now() + timedelta(seconds=wait)
                        ).isoformat()
                        health["last_error"] = str(e)[:300]
                        health["status"] = "degraded"
                    logger.error(
                        f"[{cam_label}] Scene analysis error #{consecutive_errors}, "
                        f"backing off {wait:.0f}s: {str(e)[:150]}"
                    )
                    await _send_mcp_log(
                        shared_state,
                        "error",
                        (
                            f"[{cam_label}] Vision provider error (retry in {wait:.0f}s): "
                            f"{str(e)[:120]}"
                        ),
                        event_type="provider_error",
                        camera_id=camera_id,
                    )
                    await asyncio.sleep(interval)
                    continue

                scene_state.update(
                    summary=scene_data.get("summary", ""),
                    objects=scene_data.get("objects", []),
                    people_count=scene_data.get("people_count", 0),
                    change_desc=change.description,
                )
                stats.record_analysis()
                consecutive_errors = 0
                if health is not None:
                    health["consecutive_errors"] = 0
                    health["backoff_until"] = None
                    health["last_success_at"] = datetime.now().isoformat()
                    health["last_error"] = ""
                    health["status"] = "running"
                logger.info(f"[{cam_label}] Scene: {scene_data.get('summary', '')[:100]}")

                active_rules = rules_engine.get_active_rules()
                if active_rules:
                    try:
                        evaluations = await analyzer.evaluate_rules(
                            frame, scene_state, active_rules, config
                        )
                    except Exception as e:
                        logger.error(f"[{cam_label}] Rule evaluation error: {str(e)[:150]}")
                        await _send_mcp_log(
                            shared_state,
                            "warning",
                            f"[{cam_label}] Rule evaluation failed: {str(e)[:120]}",
                            event_type="rule_eval_error",
                            camera_id=camera_id,
                        )
                        await asyncio.sleep(interval)
                        continue

                    frame_b64 = frame.to_base64(quality=config.reasoning.image_quality)
                    alerts = rules_engine.process_evaluations(
                        evaluations, scene_state, frame_base64=frame_b64,
                    )
                    for alert in alerts:
                        stats.record_alert()
                        logger.info(
                            f"ALERT [{cam_label}]: {alert.rule.name} — {alert.evaluation.reasoning}"
                        )
                        if notifier:
                            await notifier.dispatch(alert)
                        if memory:
                            memory.append_event(
                                f"ALERT [{cam_label}]: {alert.rule.name} triggered — "
                                f"{alert.evaluation.reasoning}"
                            )
                        event_id = _record_alert_event(
                            shared_state,
                            event_type="watch_rule_triggered",
                            camera_id=camera_id,
                            camera_name=camera_name,
                            rule_id=alert.rule.id,
                            rule_name=alert.rule.name,
                            message=alert.evaluation.reasoning,
                        )
                        await _send_mcp_log(
                            shared_state,
                            "warning",
                            (
                                f"WATCH RULE TRIGGERED [{cam_label}]: {alert.rule.name} — "
                                f"{alert.evaluation.reasoning}"
                            ),
                            event_type="watch_rule_triggered",
                            camera_id=camera_id,
                            rule_id=alert.rule.id,
                            event_id=event_id,
                        )
                    stats.record_analysis()

            # ── Client-side reasoning mode ───────────────────────
            elif should_analyze and not analyzer.has_provider:
                active_rules = rules_engine.get_active_rules()
                if active_rules:
                    session = shared_state.get("_session") if shared_state else None

                    sampling_supported = False
                    if session:
                        try:
                            from mcp.types import ClientCapabilities, SamplingCapability
                            sampling_supported = session.check_client_capability(
                                ClientCapabilities(sampling=SamplingCapability())
                            )
                        except Exception:
                            pass

                    if session and sampling_supported:
                        await _evaluate_via_sampling(
                            session, frame, change, active_rules,
                            scene_state, rules_engine, stats, config,
                            notifier, memory, shared_state=shared_state,
                            camera_id=camera_id, camera_name=camera_name,
                        )
                    else:
                        frame_b64 = frame.to_base64(quality=75)
                        alert = PendingAlert(
                            id=f"pa_{uuid.uuid4().hex[:8]}",
                            camera_id=camera_id,
                            camera_name=camera_name,
                            change_level=change.level.value,
                            change_description=change.description,
                            frame_base64=frame_b64,
                            scene_context=scene_state.to_context_string(),
                            active_rules=[
                                {
                                    "id": r.id,
                                    "name": r.name,
                                    "condition": r.condition,
                                    "priority": r.priority.value,
                                }
                                for r in active_rules
                            ],
                            expires_at=datetime.now() + timedelta(seconds=300),
                        )
                        await alert_queue.push(alert)
                        logger.info(
                            f"[{cam_label}] Queued alert {alert.id}: {change.level.value} change, "
                            f"{len(active_rules)} active rules"
                        )

                        if session:
                            try:
                                await session.send_log_message(
                                    level="warning",
                                    data=(
                                        f"CAMERA ALERT [{cam_label}]: {change.level.value} scene change detected "
                                        f"(hash_distance={change.hash_distance}, "
                                        f"pixel_diff={change.pixel_diff_pct:.1f}%). "
                                        f"Active rules: {', '.join(r.name for r in active_rules)}. "
                                        f"Please call check_camera_alerts() NOW to see the frame and evaluate."
                                    ),
                                    logger="physical-mcp",
                                )
                            except Exception:
                                pass

                        # Push + desktop notifications
                        if notifier:
                            frame_b64 = frame.to_base64(quality=75)
                            await notifier.notify_scene_change(
                                change_level=change.level.value,
                                rule_names=[r.name for r in active_rules],
                                frame_base64=frame_b64,
                            )
                            notifier.notify_desktop(
                                title=f"Camera [{camera_name or camera_id}]: {change.level.value} change",
                                body=(
                                    f"Rules: {', '.join(r.name for r in active_rules)}. "
                                    f"Check Claude."
                                ),
                            )

        except Exception as e:
            logger.error(f"[{cam_label}] Perception loop error: {e}")

        await asyncio.sleep(interval)


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

            if state.get("_fallback_warning_pending"):
                state["_fallback_warning_pending"] = False
                event_id = _record_alert_event(
                    state,
                    event_type="startup_warning",
                    message=(
                        "Server is running in fallback client-side reasoning mode. "
                        "Recommended: configure provider for server-side monitoring."
                    ),
                )
                asyncio.create_task(
                    _send_mcp_log(
                        state,
                        "warning",
                        (
                            "Server is running in fallback client-side reasoning mode. "
                            "Recommended: call configure_provider(provider, api_key, model) "
                            "to enable non-blocking server-side monitoring."
                        ),
                        event_type="startup_warning",
                        event_id=event_id,
                    )
                )

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

        provider = _create_provider(config)
        analyzer = FrameAnalyzer(provider)
        stats = StatsTracker(
            daily_budget=config.cost_control.daily_budget_usd,
            max_per_hour=config.cost_control.max_analyses_per_hour,
        )
        alert_queue = AlertQueue(max_size=50, ttl_seconds=300)
        memory = MemoryStore(config.memory_file)
        notifier = NotificationDispatcher(config.notifications)

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
                "\n\nAVAILABLE CAMERAS: " + ", ".join(cam_ids)
                + "\n\nCall list_cameras() to see what each camera currently "
                "shows, then use camera_id to target the right one(s). "
                "You can use multiple cameras if needed."
            )

        state.update({
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
            "_session": None,
            "_fallback_warning_pending": not bool(provider),
            "camera_health": {},
            "alert_events": [],
            "alert_events_max": 200,
        })

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
            return [TextContent(
                type="text",
                text="Error: No camera available. Run 'physical-mcp setup' to configure.",
            )]

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
            active_cameras.append({
                "id": cid,
                "name": cfg.name if cfg else "",
                "status": "active" if cam.is_open() else "disconnected",
                "scene_summary": scene.summary,
                "objects_present": scene.objects_present,
            })
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
            result["reasoning_mode"] = "server" if analyzer_inst.has_provider else "client"
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
            return [TextContent(
                type="text",
                text="Error: No camera available. Run 'physical-mcp setup' to configure.",
            )]

        frame = await camera.grab_frame()
        label = _cam_label(cam_cfg, cid)

        # ── Server-side mode: use configured provider ────────
        if analyzer_inst.has_provider:
            if stats_tracker.budget_exceeded():
                return [TextContent(type="text", text="Error: Daily budget exceeded.")]
            cfg = state["config"]
            result = await analyzer_inst.analyze_scene(frame, scene, cfg, question=question)
            stats_tracker.record_analysis()

            scene.update(
                summary=result.get("summary", ""),
                objects=result.get("objects", []),
                people_count=result.get("people_count", 0),
                change_desc="Manual analysis",
            )
            return [TextContent(
                type="text",
                text=str(result),
            )]

        # ── Client-side mode: return frame for client AI ─────
        result = []
        result.append(ImageContent(
            type="image",
            data=frame.to_base64(quality=85),
            mimeType="image/jpeg",
        ))

        prompt = f"Analyze this camera frame from {label}."
        if scene.summary:
            prompt += f"\nPrevious scene state: {scene.to_context_string()}"
        if question:
            prompt += f"\nSpecific question to answer: {question}"
        prompt += (
            "\nDescribe what you see: objects present, people count, "
            "activity, and anything notable. If a question was asked, answer it."
        )

        result.append(TextContent(type="text", text=prompt))
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
            if active_count > 0:
                msg += (
                    " IMPORTANT: You MUST call check_camera_alerts() again in "
                    "10-15 seconds to continue monitoring. Do not stop polling."
                )
            return [TextContent(type="text", text=msg)]

        latest = alerts[-1]

        # Cache frame so report_rule_evaluation can attach it to notifications
        state["_last_alert_frame"] = latest.frame_base64

        result = []

        result.append(ImageContent(
            type="image",
            data=latest.frame_base64,
            mimeType="image/jpeg",
        ))

        cam_label_str = latest.camera_name or latest.camera_id or "unknown"
        rules_text = "\n".join(
            f'  - Rule "{r["name"]}" (id={r["id"]}): {r["condition"]}'
            for r in latest.active_rules
        )

        result.append(TextContent(
            type="text",
            text=(
                f"CAMERA ALERT from {cam_label_str}: "
                f"{latest.change_level.upper()} scene change detected\n"
                f"Time: {latest.timestamp.isoformat()}\n"
                f"Change: {latest.change_description}\n"
                f"Scene context: {latest.scene_context}\n\n"
                f"ACTIVE WATCH RULES TO EVALUATE:\n{rules_text}\n\n"
                f"INSTRUCTIONS: Look at the camera frame image above. "
                f"For EACH rule listed, determine if the condition is currently "
                f"met based on what you see. Then call report_rule_evaluation() "
                f"with your findings. Be conservative — only mark triggered=true "
                f"if you are confident (>= 0.7).\n"
                f"Alert count in this batch: {len(alerts)}\n\n"
                f"After calling report_rule_evaluation(), IMMEDIATELY call "
                f"check_camera_alerts() again to continue monitoring."
            ),
        ))

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
        import json

        engine: RulesEngine = state["rules_engine"]
        # Use first available scene state for context
        scene_states = state.get("scene_states", {})
        scene = next(iter(scene_states.values()), SceneState()) if scene_states else SceneState()
        stats_tracker: StatsTracker = state["stats"]

        try:
            eval_list = json.loads(evaluations) if isinstance(evaluations, str) else evaluations
        except json.JSONDecodeError:
            return {"error": "Invalid JSON in evaluations parameter"}

        if not isinstance(eval_list, list):
            return {"error": "evaluations must be a JSON array"}

        frame_b64 = state.get("_last_alert_frame")
        triggered_alerts = engine.process_client_evaluations(
            eval_list, scene, frame_base64=frame_b64,
        )
        notifier_inst: NotificationDispatcher = state["notifier"]
        memory_inst: MemoryStore = state["memory"]

        triggered_rules = []
        for alert in triggered_alerts:
            stats_tracker.record_alert()
            triggered_rules.append({
                "rule_id": alert.rule.id,
                "rule_name": alert.rule.name,
                "reasoning": alert.evaluation.reasoning,
            })
            logger.info(
                f"CLIENT ALERT: {alert.rule.name} — {alert.evaluation.reasoning}"
            )
            await notifier_inst.dispatch(alert)
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

        Args:
            name: Human-readable name for this rule (e.g., "Front door watch")
            condition: Natural language description of what to watch for
            camera_id: Which camera to monitor (e.g. "usb:0"). Leave empty
                to monitor all cameras. Use list_cameras() to see available
                cameras and pick the right one based on room name.
            priority: "low", "medium", "high", or "critical"
            notification_type: "local" (in-chat only, default), "desktop"
                (OS notification), "ntfy" (push to phone via ntfy.sh),
                "webhook" (HTTP POST)
            notification_url: URL for webhook notifications (leave empty otherwise)
            notification_channel: ntfy topic override for this rule (uses
                server default if empty)
            cooldown_seconds: Min seconds between repeated alerts (default 60)
        """
        engine: RulesEngine = state["rules_engine"]
        store: RulesStore = state["rules_store"]

        if ctx:
            _capture_session(ctx)

        from .rules.models import WatchRule, NotificationTarget, RulePriority

        # Auto-use ntfy when topic is configured and user didn't override
        if notification_type == "local" and config.notifications.ntfy_topic:
            notification_type = "ntfy"

        rule = WatchRule(
            id=f"r_{uuid.uuid4().hex[:8]}",
            name=name,
            condition=condition,
            camera_id=camera_id,
            priority=RulePriority(priority),
            notification=NotificationTarget(
                type=notification_type,
                url=notification_url if notification_url else None,
                channel=notification_channel if notification_channel else None,
            ),
            cooldown_seconds=cooldown_seconds,
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
            memory: MemoryStore = state["memory"]
            memory.append_event(f"Rule '{rule_id}' removed")
            memory.remove_rule_context(rule_id)
        return {"removed": removed, "rule_id": rule_id}

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
                "health": health_map.get(camera_id, {
                    "status": "unknown",
                    "message": "No health data yet. Start monitoring first.",
                }),
            }
        return {"cameras": health_map}

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
        """
        cfg: PhysicalMCPConfig = state["config"]
        cfg.reasoning.provider = provider
        cfg.reasoning.api_key = api_key
        if model:
            cfg.reasoning.model = model
        if base_url:
            cfg.reasoning.base_url = base_url

        new_provider = _create_provider(cfg)
        analyzer_inst: FrameAnalyzer = state["analyzer"]
        analyzer_inst.set_provider(new_provider)

        mode = "server" if new_provider else "client"
        return {
            "status": "configured",
            "provider": provider or "none",
            "model": new_provider.model_name if new_provider else "none",
            "reasoning_mode": mode,
        }

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
            return "No memory stored yet. Events will be recorded as you use the system."
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
            return {"status": "nothing_saved", "message": "Provide at least one field to save."}

        return {"status": "saved", "saved": saved}

    return mcp
