"""Canonical perception loop — one per camera.

Dual-mode behavior:
  - Always captures frames and runs local change detection (free, <5ms)
  - Server-side mode (has provider): calls external LLM API for analysis
  - Client-side mode (no provider): queues PendingAlert for client to poll
  - No watch rules = zero API calls / zero alerts (just local monitoring)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.types import ImageContent, TextContent

from ..alert_queue import AlertQueue
from ..camera.base import Frame
from ..camera.buffer import FrameBuffer
from ..camera.usb import USBCamera
from ..config import PhysicalMCPConfig
from ..mcp_logging import (
    alert_event_timestamp,
    record_alert_event,
    send_mcp_log,
)
from ..notifications import NotificationDispatcher
from ..memory import MemoryStore
from ..perception.frame_sampler import FrameSampler
from ..perception.scene_state import SceneState
from ..reasoning.analyzer import FrameAnalyzer
from ..rules.engine import RulesEngine
from ..rules.models import PendingAlert
from ..stats import StatsTracker

logger = logging.getLogger("physical-mcp")

_FRAME_PATH = Path("/tmp/physical-mcp-frame.jpg")


def _save_alert_frame(frame: "Frame", quality: int = 85) -> None:
    """Write the current frame to disk so OpenClaw can attach it to notifications."""
    try:
        b64 = frame.to_base64(quality=quality)
        _FRAME_PATH.write_bytes(base64.b64decode(b64))
    except Exception as e:
        logger.debug(f"Failed to save alert frame: {e}")


def _cam_label(camera_name: str, camera_id: str) -> str:
    """Human-readable camera label: 'Kitchen (usb:0)' or just 'usb:0'."""
    if camera_name:
        return f"{camera_name} ({camera_id})"
    return camera_id or "unknown"


async def _evaluate_via_sampling(
    session,
    frame: Frame,
    change,
    active_rules: list,
    scene_state: SceneState,
    rules_engine: RulesEngine,
    stats: StatsTracker,
    config: PhysicalMCPConfig,
    notifier: NotificationDispatcher | None,
    memory: MemoryStore | None,
    shared_state: dict[str, Any] | None = None,
    camera_id: str = "",
    camera_name: str = "",
) -> None:
    """Use MCP sampling to ask the client's LLM to evaluate watch rules."""
    from mcp.types import ModelPreferences, SamplingMessage

    frame_b64 = frame.to_base64(quality=config.reasoning.image_quality)
    cam_label = _cam_label(camera_name, camera_id)

    rules_text = "\n".join(
        f'- Rule "{r.name}" (id={r.id}): {r.condition}' for r in active_rules
    )

    try:
        result = await session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=[
                        ImageContent(
                            type="image", data=frame_b64, mimeType="image/jpeg"
                        ),
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
            evaluations,
            scene_state,
            frame_base64=frame_b64,
        )
        # Re-validate: drop alerts for rules deleted during LLM sampling call
        # Note: use list_rules() not get_active_rules() — just-triggered
        # rules are in cooldown and would be filtered out incorrectly
        live_ids = {r.id for r in rules_engine.list_rules() if r.enabled}
        alerts = [a for a in alerts if a.rule.id in live_ids]
        for alert in alerts:
            stats.record_alert()
            logger.info(
                f"SAMPLING ALERT [{cam_label}]: {alert.rule.name} — {alert.evaluation.reasoning}"
            )
            if notifier:
                _save_alert_frame(frame, quality=config.reasoning.image_quality)
                await notifier.dispatch(alert)
            if shared_state and "event_bus" in shared_state:
                await shared_state["event_bus"].publish(
                    "alert",
                    {
                        "type": "watch_rule_triggered",
                        "rule_id": alert.rule.id,
                        "rule_name": alert.rule.name,
                        "camera_id": camera_id,
                        "confidence": alert.evaluation.confidence,
                        "reasoning": alert.evaluation.reasoning,
                    },
                )
            if memory:
                memory.append_event(
                    f"ALERT: {alert.rule.name} triggered — {alert.evaluation.reasoning}"
                )
            event_id = record_alert_event(
                shared_state,
                event_type="watch_rule_triggered",
                camera_id=camera_id,
                camera_name=camera_name,
                rule_id=alert.rule.id,
                rule_name=alert.rule.name,
                message=alert.evaluation.reasoning,
            )
            await send_mcp_log(
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
                timestamp=alert_event_timestamp(shared_state, event_id),
            )
    except Exception as e:
        logger.error(f"Sampling evaluation parse error: {e}")


async def perception_loop(
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

    # Periodic scene-only analysis interval (even without rules).
    # This keeps scene descriptions fresh for /scene, /snap, and
    # "what do you see?" queries.  Cloud mode uses a shorter interval
    # (10s) to catch brief actions that slip past change detection.
    scene_only_interval = float(os.environ.get("SCENE_ONLY_INTERVAL", "30"))
    if os.environ.get("CLOUD_MODE") == "1" and scene_only_interval >= 30:
        scene_only_interval = 10.0
    last_scene_only_time = time.monotonic()  # Don't fire immediately at startup

    cam_label = _cam_label(camera_name, camera_id)

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

    # Cloud cameras may not have frames yet at startup.
    # Wait for the first frame before entering the main loop.
    from ..camera.cloud import CloudCamera

    is_cloud_cam = isinstance(camera, CloudCamera)
    if is_cloud_cam:
        logger.info(f"[{cam_label}] Waiting for first frame from cloud camera...")
        first_frame = await camera.wait_for_frame(timeout=60.0)
        if first_frame is None:
            logger.warning(
                f"[{cam_label}] No frame received after 60s, entering loop anyway"
            )
        else:
            await frame_buffer.push(first_frame)
            logger.info(f"[{cam_label}] First frame received, starting perception")

    last_cloud_seq = -1  # Track cloud frame sequence to skip duplicates

    while True:
        try:
            # Cloud cameras: poll for new frames (simple, reliable).
            # Frames arrive via HTTP POST → CloudCamera._latest_frame.
            # USB cameras: actively grab at configured FPS.
            if is_cloud_cam:
                try:
                    frame = await camera.grab_frame()
                except Exception:
                    # No frame yet — wait and retry
                    await asyncio.sleep(2.0)
                    continue
                # Skip if same frame we already processed
                if frame.sequence_number == last_cloud_seq:
                    await asyncio.sleep(1.0)
                    continue
                last_cloud_seq = frame.sequence_number
                # Push into buffer so change detection has frame history
                await frame_buffer.push(frame)
                logger.debug(
                    f"[{cam_label}] Cloud frame #{frame.sequence_number} "
                    f"({frame.resolution[0]}x{frame.resolution[1]})"
                )
            else:
                frame = await camera.grab_frame()
                await frame_buffer.push(frame)
            if health is not None:
                health["last_frame_at"] = datetime.now().isoformat()
                if health.get("status") == "starting":
                    health["status"] = "running"

            has_active_rules = len(rules_engine.get_active_rules()) > 0
            should_analyze, change = sampler.should_analyze(frame, has_active_rules)

            # Log cloud camera frames (debug-level to reduce log noise)
            if is_cloud_cam:
                logger.debug(
                    f"[{cam_label}] Frame #{frame.sequence_number}: "
                    f"change={change.level.value} analyze={should_analyze} "
                    f"rules={has_active_rules}"
                )

            if change.level.value != "none":
                scene_state.record_change(change.description)
                logger.debug(
                    f"[{cam_label}] Change: {change.level.value} "
                    f"(hash={change.hash_distance}, px={change.pixel_diff_pct:.2%}) "
                    f"analyze={should_analyze}"
                )

            # ── Server-side reasoning mode (COMBINED single call) ──
            if should_analyze and analyzer.has_provider and not stats.budget_exceeded():
                now = time.monotonic()
                if now < backoff_until:
                    remaining = backoff_until - now
                    if health is not None:
                        health["status"] = "backoff"
                    if consecutive_errors <= 3:
                        logger.info(
                            f"[{cam_label}] In backoff, retry in {remaining:.0f}s"
                        )
                    await asyncio.sleep(interval)
                    continue

                active_rules = rules_engine.get_active_rules()

                # Gather per-rule hints + few-shot examples from eval_log
                _rule_hints: dict[str, str] = {}
                _few_shot: list[dict] = []
                _eval_log = shared_state.get("eval_log") if shared_state else None
                if _eval_log and active_rules:
                    _seen_b64: set[str] = set()
                    for _r in active_rules:
                        try:
                            _rs = _eval_log.get_rule_stats(_r.id)
                            if _rs and _rs.get("prompt_hint"):
                                _rule_hints[_r.id] = _rs["prompt_hint"]
                        except Exception:
                            pass
                        # Gather few-shot visual examples (max 2 per rule)
                        try:
                            _examples = _eval_log.get_few_shot_examples(
                                _r.id, max_per_label=1
                            )
                            for _ex in _examples:
                                # Deduplicate across rules
                                _key = _ex["thumbnail_b64"][:32]
                                if _key not in _seen_b64 and len(_few_shot) < 4:
                                    _seen_b64.add(_key)
                                    _few_shot.append(_ex)
                        except Exception:
                            pass

                # Grab recent frames for temporal context (~3s window)
                # Wider window catches brief actions that triggered debounce
                recent = await frame_buffer.get_frames_since(
                    frame.timestamp - timedelta(seconds=3.0)
                )
                if len(recent) >= 3:
                    step = len(recent) / 3
                    analysis_frames = [recent[int(i * step)] for i in range(3)]
                elif recent:
                    analysis_frames = recent
                else:
                    analysis_frames = [frame]

                try:
                    # ONE combined call: scene analysis + rule evaluation
                    result = await analyzer.analyze_and_evaluate(
                        analysis_frames,
                        scene_state,
                        active_rules,
                        config,
                        rule_hints=_rule_hints or None,
                        few_shot_examples=_few_shot or None,
                    )
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
                        f"[{cam_label}] Analysis error #{consecutive_errors}, "
                        f"backing off {wait:.0f}s: {str(e)[:150]}"
                    )
                    event_id = record_alert_event(
                        shared_state,
                        event_type="provider_error",
                        camera_id=camera_id,
                        camera_name=camera_name,
                        message=(
                            f"[{cam_label}] Vision provider error (retry in {wait:.0f}s): "
                            f"{str(e)[:120]}"
                        ),
                    )
                    await send_mcp_log(
                        shared_state,
                        "error",
                        (
                            f"[{cam_label}] Vision provider error (retry in {wait:.0f}s): "
                            f"{str(e)[:120]}"
                        ),
                        event_type="provider_error",
                        camera_id=camera_id,
                        event_id=event_id,
                        timestamp=alert_event_timestamp(shared_state, event_id),
                    )
                    await asyncio.sleep(interval)
                    continue

                scene_data = result.get("scene", {})
                evaluations = result.get("evaluations", [])

                # Only update scene if we got a real summary
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
                else:
                    logger.info(
                        "[%s] Analysis returned no data, keeping previous scene",
                        cam_label,
                    )
                stats.record_analysis()
                consecutive_errors = 0
                if health is not None:
                    health["consecutive_errors"] = 0
                    health["backoff_until"] = None
                    health["last_success_at"] = datetime.now().isoformat()
                    health["last_error"] = ""
                    health["status"] = "running"
                logger.info(
                    f"[{cam_label}] Scene: {scene_data.get('summary', '')[:100]}"
                )

                # ── Process rule evaluations from combined call ──
                if evaluations and active_rules:
                    frame_b64 = frame.to_base64(quality=config.reasoning.image_quality)
                    # Small thumbnail for eval log storage (~15-20 KB)
                    # Uses 320px max dim to keep DB compact
                    try:
                        _thumb_b64 = frame.to_thumbnail(max_dim=320, quality=70)
                        _storage_thumb: bytes | None = base64.b64decode(_thumb_b64)
                    except Exception:
                        _storage_thumb = None
                    alerts = rules_engine.process_evaluations(
                        evaluations,
                        scene_state,
                        frame_base64=frame_b64,
                        camera_id=camera_id,
                        frame_thumbnail_bytes=_storage_thumb,
                    )
                    # Re-validate: drop alerts for rules deleted during LLM call
                    # Note: use list_rules() not get_active_rules() — just-triggered
                    # rules are in cooldown and would be filtered out incorrectly
                    live_ids = {r.id for r in rules_engine.list_rules() if r.enabled}
                    alerts = [a for a in alerts if a.rule.id in live_ids]
                    for alert in alerts:
                        stats.record_alert()
                        logger.info(
                            f"ALERT [{cam_label}]: {alert.rule.name} — {alert.evaluation.reasoning}"
                        )
                        if notifier:
                            _save_alert_frame(
                                frame, quality=config.reasoning.image_quality
                            )
                            await notifier.dispatch(alert)
                        if shared_state and "event_bus" in shared_state:
                            await shared_state["event_bus"].publish(
                                "alert",
                                {
                                    "type": "watch_rule_triggered",
                                    "rule_id": alert.rule.id,
                                    "rule_name": alert.rule.name,
                                    "camera_id": camera_id,
                                    "confidence": alert.evaluation.confidence,
                                    "reasoning": alert.evaluation.reasoning,
                                },
                            )
                        if memory:
                            memory.append_event(
                                f"ALERT [{cam_label}]: {alert.rule.name} triggered — "
                                f"{alert.evaluation.reasoning}"
                            )
                        event_id = record_alert_event(
                            shared_state,
                            event_type="watch_rule_triggered",
                            camera_id=camera_id,
                            camera_name=camera_name,
                            rule_id=alert.rule.id,
                            rule_name=alert.rule.name,
                            message=alert.evaluation.reasoning,
                        )
                        await send_mcp_log(
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
                            timestamp=alert_event_timestamp(shared_state, event_id),
                        )

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
                            session,
                            frame,
                            change,
                            active_rules,
                            scene_state,
                            rules_engine,
                            stats,
                            config,
                            notifier,
                            memory,
                            shared_state=shared_state,
                            camera_id=camera_id,
                            camera_name=camera_name,
                        )
                    else:
                        frame_b64 = frame.to_base64(quality=75)
                        pending_alert = PendingAlert(
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
                                    "custom_message": r.custom_message,
                                }
                                for r in active_rules
                            ],
                            expires_at=datetime.now() + timedelta(seconds=300),
                        )
                        await alert_queue.push(pending_alert)
                        logger.info(
                            f"[{cam_label}] Queued alert {pending_alert.id}: {change.level.value} change, "
                            f"{len(active_rules)} active rules"
                        )

                        event_id = record_alert_event(
                            shared_state,
                            event_type="camera_alert_pending_eval",
                            camera_id=camera_id,
                            camera_name=camera_name,
                            message=(
                                f"{change.level.value} scene change detected "
                                f"(hash_distance={change.hash_distance}, "
                                f"pixel_diff={change.pixel_diff_pct:.1f}%). "
                                f"Active rules: {', '.join(r.name for r in active_rules)}."
                            ),
                        )
                        if session:
                            await send_mcp_log(
                                shared_state,
                                "warning",
                                (
                                    f"CAMERA ALERT [{cam_label}]: {change.level.value} scene change detected "
                                    f"(hash_distance={change.hash_distance}, "
                                    f"pixel_diff={change.pixel_diff_pct:.1f}%). "
                                    f"Active rules: {', '.join(r.name for r in active_rules)}. "
                                    f"Please call check_camera_alerts() NOW to see the frame and evaluate."
                                ),
                                event_type="camera_alert_pending_eval",
                                camera_id=camera_id,
                                event_id=event_id,
                                timestamp=alert_event_timestamp(shared_state, event_id),
                            )

                        # Publish scene change to EventBus
                        if shared_state and "event_bus" in shared_state:
                            await shared_state["event_bus"].publish(
                                "scene_change",
                                {
                                    "type": "scene_change",
                                    "camera_id": camera_id,
                                    "change_level": change.level.value,
                                    "active_rules": [r.name for r in active_rules],
                                },
                            )

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

            # ── Periodic scene analysis (also evaluates rules if any exist) ──
            # Keeps scene descriptions fresh for /scene, /snap captions,
            # and "what do you see?" queries.  When rules exist, evaluates
            # them too — catches slow changes that don't trip the sampler.
            if (
                not should_analyze
                and analyzer.has_provider
                and not stats.budget_exceeded()
            ):
                now_mono = time.monotonic()
                if (now_mono - last_scene_only_time) >= scene_only_interval:
                    try:
                        periodic_rules = rules_engine.get_active_rules()
                        if periodic_rules:
                            # Gather per-rule hints + few-shot examples for periodic eval
                            _periodic_hints: dict[str, str] = {}
                            _periodic_few_shot: list[dict] = []
                            _p_eval_log = (
                                shared_state.get("eval_log") if shared_state else None
                            )
                            if _p_eval_log:
                                _p_seen: set[str] = set()
                                for _pr in periodic_rules:
                                    try:
                                        _prs = _p_eval_log.get_rule_stats(_pr.id)
                                        if _prs and _prs.get("prompt_hint"):
                                            _periodic_hints[_pr.id] = _prs[
                                                "prompt_hint"
                                            ]
                                    except Exception:
                                        pass
                                    try:
                                        _p_ex = _p_eval_log.get_few_shot_examples(
                                            _pr.id, max_per_label=1
                                        )
                                        for _pe in _p_ex:
                                            _pk = _pe["thumbnail_b64"][:32]
                                            if (
                                                _pk not in _p_seen
                                                and len(_periodic_few_shot) < 4
                                            ):
                                                _p_seen.add(_pk)
                                                _periodic_few_shot.append(_pe)
                                    except Exception:
                                        pass
                            # Rules exist: combined scene + rule evaluation
                            result = await analyzer.analyze_and_evaluate(
                                [frame],
                                scene_state,
                                periodic_rules,
                                config,
                                rule_hints=_periodic_hints or None,
                                few_shot_examples=_periodic_few_shot or None,
                            )
                            scene_data = result.get("scene", {})
                            evaluations = result.get("evaluations", [])
                        else:
                            # No rules: scene-only analysis
                            scene_data = await analyzer.analyze_scene(
                                frame, scene_state, config
                            )
                            evaluations = []

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
                                change_desc="periodic scene update",
                            )
                            logger.info(f"[{cam_label}] Scene: {summary[:100]}")

                        # Process rule evaluations from periodic analysis
                        if evaluations and periodic_rules:
                            frame_b64 = frame.to_base64(
                                quality=config.reasoning.image_quality
                            )
                            try:
                                _p_thumb_b64 = frame.to_thumbnail(
                                    max_dim=320, quality=70
                                )
                                _p_storage_thumb: bytes | None = base64.b64decode(
                                    _p_thumb_b64
                                )
                            except Exception:
                                _p_storage_thumb = None
                            alerts = rules_engine.process_evaluations(
                                evaluations,
                                scene_state,
                                frame_base64=frame_b64,
                                camera_id=camera_id,
                                frame_thumbnail_bytes=_p_storage_thumb,
                            )
                            live_ids = {
                                r.id for r in rules_engine.list_rules() if r.enabled
                            }
                            alerts = [a for a in alerts if a.rule.id in live_ids]
                            for alert in alerts:
                                stats.record_alert()
                                logger.info(
                                    f"ALERT [{cam_label}]: {alert.rule.name} — {alert.evaluation.reasoning}"
                                )
                                if notifier:
                                    _save_alert_frame(
                                        frame, quality=config.reasoning.image_quality
                                    )
                                    await notifier.dispatch(alert)
                                if shared_state and "event_bus" in shared_state:
                                    await shared_state["event_bus"].publish(
                                        "alert",
                                        {
                                            "type": "watch_rule_triggered",
                                            "rule_id": alert.rule.id,
                                            "rule_name": alert.rule.name,
                                            "camera_id": camera_id,
                                            "confidence": alert.evaluation.confidence,
                                            "reasoning": alert.evaluation.reasoning,
                                        },
                                    )
                                if memory:
                                    memory.append_event(
                                        f"ALERT [{cam_label}]: {alert.rule.name} triggered — "
                                        f"{alert.evaluation.reasoning}"
                                    )

                        stats.record_analysis()
                        last_scene_only_time = now_mono
                    except Exception as e:
                        logger.error(f"[{cam_label}] Periodic analysis error: {e}")
                        last_scene_only_time = now_mono  # Back off

        except Exception as e:
            logger.error(f"[{cam_label}] Perception loop error: {e}")

        # Cloud cameras already wait for frames above (event-driven),
        # so skip the FPS sleep. USB cameras need the sleep to cap frame rate.
        if not is_cloud_cam:
            await asyncio.sleep(interval)
