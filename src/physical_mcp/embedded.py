"""Minimal entry point for embedded server mode (inside Flutter app).

Starts both the Vision API server and the MCP streamable-HTTP server
without any interactive CLI, setup wizard, or click decorators.
Designed to be bundled via PyInstaller into a standalone binary
that the Flutter app spawns as a subprocess.

Usage:
    python -m physical_mcp.embedded [--port 8090] [--mcp-port 8400]
    # or as PyInstaller binary:
    ./physical-mcp-server --port 8090 --mcp-port 8400
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

logger = logging.getLogger("physical-mcp")


def _configure_logging() -> None:
    """Minimal logging setup for embedded mode."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(log_format, datefmt=date_format))

    # File handler (best-effort)
    handlers: list[logging.Handler] = [console]
    log_dir = Path("~/.physical-mcp/logs").expanduser()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            log_dir / "embedded.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=2,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
        handlers.append(file_handler)
    except Exception:
        pass

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    for noisy in ("httpcore", "httpx", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _parse_args() -> tuple[int, int]:
    """Parse --port and --mcp-port from sys.argv. Returns (port, mcp_port)."""
    port = 8090
    mcp_port = 8400
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass
        elif arg == "--mcp-port" and i + 1 < len(args):
            try:
                mcp_port = int(args[i + 1])
            except ValueError:
                pass
    return port, mcp_port


def _ensure_config(port: int) -> Path:
    """Ensure a config file exists. Creates default if missing."""
    config_path = Path("~/.physical-mcp/config.yaml").expanduser()
    if config_path.exists():
        return config_path

    # Auto-create minimal config with USB camera 0
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""\
# Physical MCP — auto-generated config (embedded mode)
cameras:
  - id: "usb:0"
    type: usb
    device_index: 0
    width: 1280
    height: 720
    enabled: true

vision_api:
  enabled: true
  host: "0.0.0.0"
  port: {port}

perception:
  capture_fps: 2
  buffer_size: 300
"""
    )
    logger.info("Created default config at %s", config_path)
    return config_path


async def _run_server(port: int, mcp_port: int = 8400) -> None:
    """Start the Vision API + MCP servers."""
    from aiohttp import web as aio_web

    from physical_mcp.alert_queue import AlertQueue
    from physical_mcp.camera.buffer import FrameBuffer
    from physical_mcp.camera.factory import create_camera
    from physical_mcp.config import load_config
    from physical_mcp.mdns import publish_vision_api_mdns
    from physical_mcp.perception.scene_state import SceneState
    from physical_mcp.platform import get_lan_ip
    from physical_mcp.reasoning.analyzer import FrameAnalyzer
    from physical_mcp.rules.engine import RulesEngine
    from physical_mcp.server import _create_provider
    from physical_mcp.vision_api import create_vision_routes

    config_path = _ensure_config(port)
    config = load_config(config_path)
    config.vision_api.port = port
    config.vision_api.host = "0.0.0.0"

    shutdown_event = asyncio.Event()

    def _signal_handler(signum: int, _frame: object) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down...", sig_name)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            pass

    # Build shared state
    vision_state: dict = {
        "config": config,
        "rules_engine": RulesEngine(),
        "scene_state": SceneState(),
        "alert_queue": AlertQueue(),
        "cameras": {},
        "camera_configs": {},
        "frame_buffers": {},
        "scene_states": {},
        "camera_health": {},
        "alert_events": [],
        "alert_events_max": 200,
    }

    # Open cameras
    opened = 0
    for cam_config in config.cameras:
        if not cam_config.enabled:
            continue
        cid = cam_config.id
        try:
            camera = create_camera(cam_config)
            await camera.open()
            vision_state["cameras"][cid] = camera
            vision_state["camera_configs"][cid] = cam_config
            vision_state["frame_buffers"][cid] = FrameBuffer(
                max_frames=config.perception.buffer_size
            )
            vision_state["scene_states"][cid] = SceneState()
            vision_state["camera_health"][cid] = {
                "camera_id": cid,
                "camera_name": cam_config.name or cid,
                "consecutive_errors": 0,
                "backoff_until": None,
                "last_success_at": None,
                "last_error": "",
                "last_frame_at": None,
                "status": "running",
            }
            opened += 1
            print(f"[embedded] Camera {cid} ({cam_config.name or cid}): opened")
        except Exception as e:
            print(f"[embedded] Camera {cid}: failed to open ({e})", file=sys.stderr)

    if opened == 0:
        print(
            "[embedded] Warning: No cameras opened. Serving empty data.",
            file=sys.stderr,
        )

    # Vision provider (optional — scene analysis)
    # May fail if SDK not bundled (e.g. openai excluded from PyInstaller)
    try:
        provider = _create_provider(config)
    except Exception as e:
        print(
            f"[embedded] Vision provider init failed ({e}) — running without analysis",
            file=sys.stderr,
        )
        provider = None
    analyzer = FrameAnalyzer(provider)
    vision_state["analyzer"] = analyzer

    if analyzer.has_provider:
        info = analyzer.provider_info
        print(f"[embedded] Vision provider: {info['provider']} / {info['model']}")
    else:
        print("[embedded] Vision provider: none (scene analysis disabled)")

    analysis_interval = max(config.perception.sampling.cooldown_seconds, 10.0)

    # Start capture loops
    capture_tasks = []
    for cid, camera in vision_state["cameras"].items():
        buf = vision_state["frame_buffers"][cid]
        scene_st = vision_state["scene_states"][cid]
        fps = config.perception.capture_fps or 2

        async def _capture_loop(
            cam=camera,
            fb=buf,
            cam_id=cid,
            scene=scene_st,
            interval=1.0 / fps,
        ):
            import time as _time
            from datetime import datetime, timezone

            last_analysis = 0.0
            frame_count = 0

            while not shutdown_event.is_set():
                try:
                    frame = await cam.grab_frame()
                    await fb.push(frame)
                    frame_count += 1
                    health = vision_state["camera_health"].get(cam_id)
                    if health:
                        health["last_frame_at"] = datetime.now(timezone.utc).isoformat()
                        health["last_success_at"] = health["last_frame_at"]
                        health["consecutive_errors"] = 0
                except Exception as e:
                    health = vision_state["camera_health"].get(cam_id)
                    if health:
                        health["consecutive_errors"] += 1
                        health["last_error"] = str(e)
                    await asyncio.sleep(interval)
                    continue

                # Periodic server-side scene analysis
                now = _time.monotonic()
                if (
                    analyzer.has_provider
                    and (now - last_analysis) >= analysis_interval
                    and frame_count > 1
                ):
                    try:
                        scene_data = await analyzer.analyze_scene(frame, scene, config)
                        summary = scene_data.get("summary", "")
                        if (
                            summary
                            and not summary.startswith("Analysis error:")
                            and not summary.lstrip().startswith("```")
                        ):
                            scene.update(
                                summary=summary,
                                objects=scene_data.get("objects", []),
                                people_count=scene_data.get("people_count", 0),
                                change_desc="server-side analysis",
                            )
                        last_analysis = now
                    except Exception:
                        last_analysis = now

                await asyncio.sleep(interval)

        task = asyncio.create_task(_capture_loop())
        capture_tasks.append(task)

    # Start Vision API
    vision_runner = None
    mdns_publisher = None
    try:
        vision_app = create_vision_routes(vision_state)
        vision_runner = aio_web.AppRunner(vision_app)
        await vision_runner.setup()
        site = aio_web.TCPSite(
            vision_runner,
            config.vision_api.host,
            config.vision_api.port,
        )
        await site.start()
        print(
            f"[embedded] Vision API: http://{config.vision_api.host}:"
            f"{config.vision_api.port} ({opened} camera{'s' if opened != 1 else ''})"
        )

        # mDNS for LAN discovery
        lan_ip = get_lan_ip()
        mdns_publisher = publish_vision_api_mdns(config.vision_api.port, ip=lan_ip)
        if mdns_publisher:
            print(
                f"[embedded] mDNS: http://physical-mcp.local:{config.vision_api.port}"
            )

        print("[embedded] Ready.", flush=True)

    except Exception as e:
        print(f"[embedded] Vision API failed to start: {e}", file=sys.stderr)
        shutdown_event.set()

    # ── Start MCP Server (for ChatGPT / streamable-HTTP clients) ──
    uvi_server = None
    mcp_task = None
    try:
        import json as _json

        import uvicorn

        from physical_mcp.server import create_server

        # Set server host/port in config so create_server picks them up
        config.server.host = "0.0.0.0"
        config.server.port = mcp_port

        mcp_server = create_server(config)
        mcp_starlette_app = mcp_server.streamable_http_app()

        # Wrap the MCP ASGI app to handle common user mistakes:
        # 1. Entering just the base URL (/) instead of /mcp
        # 2. Entering /mcp/ (trailing slash) which Starlette redirects to
        #    localhost — unreachable through a Cloudflare tunnel
        async def _wrapped_mcp_app(scope, receive, send):
            path = scope.get("path", "")

            # Root path — return helpful JSON pointing to /mcp
            if path == "/" and scope["type"] == "http":
                body = _json.dumps(
                    {
                        "name": "physical-mcp",
                        "mcp_endpoint": "/mcp",
                        "hint": "POST to /mcp with MCP JSON-RPC protocol",
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            [b"content-type", b"application/json"],
                            [b"content-length", str(len(body)).encode()],
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

            # Strip trailing slash on /mcp/ — rewrite to /mcp in-place
            # instead of redirecting (redirects break through tunnels).
            if path == "/mcp/":
                scope = dict(scope, path="/mcp", raw_path=b"/mcp")

            # Delegate everything else to the real MCP app
            await mcp_starlette_app(scope, receive, send)

        uvi_config = uvicorn.Config(
            _wrapped_mcp_app,
            host="0.0.0.0",
            port=mcp_port,
            log_level="warning",
        )
        uvi_server = uvicorn.Server(uvi_config)
        mcp_task = asyncio.create_task(uvi_server.serve())
        print(
            f"[embedded] MCP server: http://0.0.0.0:{mcp_port}/mcp",
            flush=True,
        )
    except Exception as e:
        print(
            f"[embedded] MCP server failed to start ({e}) — MCP unavailable",
            file=sys.stderr,
        )

    # Wait for shutdown signal
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down embedded server...")

        # Stop MCP server
        if uvi_server:
            uvi_server.should_exit = True
        if mcp_task:
            try:
                await asyncio.wait_for(mcp_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                mcp_task.cancel()

        # Cancel capture tasks
        for t in capture_tasks:
            t.cancel()
        if capture_tasks:
            await asyncio.gather(*capture_tasks, return_exceptions=True)

        # Save rules
        rules_engine = vision_state.get("rules_engine")
        if rules_engine and hasattr(rules_engine, "save"):
            try:
                rules_engine.save()
            except Exception:
                pass

        # Close mDNS
        if mdns_publisher:
            mdns_publisher.close()

        # Close Vision API
        if vision_runner:
            await vision_runner.cleanup()

        # Close cameras
        for cam_id, cam in vision_state["cameras"].items():
            if cam:
                try:
                    await cam.close()
                except Exception:
                    pass

        print("[embedded] Shut down cleanly.")


def main() -> None:
    """Entry point for embedded mode."""
    _configure_logging()
    port, mcp_port = _parse_args()
    print(f"[embedded] Physical MCP server starting (API:{port}, MCP:{mcp_port})...")
    asyncio.run(_run_server(port, mcp_port))


if __name__ == "__main__":
    main()
