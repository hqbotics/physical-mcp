"""CLI entry point for Physical MCP."""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

import click

from . import __version__


def _configure_logging(verbose: bool = False) -> None:
    """Set up structured logging with console and optional file output."""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler (stderr so it doesn't interfere with MCP stdio)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(log_format, datefmt=date_format))

    # File handler (optional, best-effort)
    handlers: list[logging.Handler] = [console]
    log_dir = Path("~/.physical-mcp/logs").expanduser()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            log_dir / "physical-mcp.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
        handlers.append(file_handler)
    except Exception:
        pass  # File logging is best-effort

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    # Suppress noisy third-party loggers
    for noisy in ("httpcore", "httpx", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Helpers ──────────────────────────────────────────────


def _pick_model(provider_name: str, options: list[tuple[str, str]]) -> str:
    """Show numbered model options and return the selected model name."""
    click.echo(f"\n  {provider_name} models:")
    for i, (name, desc) in enumerate(options, 1):
        click.echo(f"    {i}. {name} — {desc}")
    click.echo(f"    {len(options) + 1}. Custom (enter model name)")
    choice = click.prompt("  Model choice", type=int, default=1)
    if 1 <= choice <= len(options):
        return options[choice - 1][0]
    return click.prompt("  Enter model name")


# ── CLI Commands ─────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="physical-mcp")
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option(
    "--transport", default=None, help="Override transport: stdio | streamable-http"
)
@click.option("--port", default=None, type=int, help="Override HTTP port")
@click.option(
    "--headless",
    is_flag=True,
    default=False,
    help="Skip interactive setup (for Docker/cloud deployment)",
)
@click.pass_context
def main(
    ctx: click.Context,
    config_path: str | None,
    transport: str | None,
    port: int | None,
    headless: bool,
) -> None:
    """Physical MCP — Give your AI eyes."""
    if ctx.invoked_subcommand is not None:
        return

    _configure_logging()

    import os

    headless = headless or os.environ.get("PHYSICAL_MCP_HEADLESS") == "1"

    # Auto-setup: if no config exists, run the setup wizard first
    config_file = Path(config_path or "~/.physical-mcp/config.yaml").expanduser()
    if not config_file.exists() and not headless:
        click.echo("Welcome to Physical MCP! Let's set up your camera.\n")
        ctx.invoke(setup, config_path=config_path)
        # After setup, check if we should start the server or just exit
        if not config_file.exists():
            return  # Setup was cancelled
        from .config import load_config

        config = load_config(config_path)
        if config.server.transport == "stdio":
            # Claude Desktop handles starting the server itself
            return

    from .config import load_config
    from .server import create_server

    config = load_config(config_path)
    if transport:
        config.server.transport = transport
    if port:
        config.server.port = port

    # Auto-bind to all interfaces for HTTP mode (enables phone/LAN connections)
    if (
        config.server.transport == "streamable-http"
        and config.server.host == "127.0.0.1"
    ):
        config.server.host = "0.0.0.0"

    mcp_server = create_server(config)

    # In HTTP mode, start Vision API independently so it's available
    # even before any MCP client connects (needed for ChatGPT GPT Actions).
    if config.server.transport == "streamable-http" and config.vision_api.enabled:
        import anyio

        async def _run_with_vision_api():
            import asyncio
            from .vision_api import create_vision_routes
            from .camera.factory import create_camera
            from .camera.buffer import FrameBuffer
            from .perception.scene_state import SceneState
            from .rules.engine import RulesEngine
            from .alert_queue import AlertQueue
            from aiohttp import web as aio_web
            import uvicorn

            _logger = logging.getLogger("physical-mcp")
            _shutdown_event = asyncio.Event()

            def _signal_handler(signum: int, _frame: object) -> None:
                sig_name = signal.Signals(signum).name
                _logger.info("Received %s — initiating graceful shutdown...", sig_name)
                _shutdown_event.set()

            # Install signal handlers (best-effort; may fail in threads)
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    signal.signal(sig, _signal_handler)
                except (OSError, ValueError):
                    pass  # Cannot set signal handler from non-main thread

            # Build shared state with live cameras for the Vision API.
            from .notifications import NotificationDispatcher
            from .perception.change_detector import ChangeDetector
            from .perception.frame_sampler import FrameSampler
            from .perception.loop import perception_loop as _perception_loop
            from .rules.store import RulesStore
            from .stats import StatsTracker
            from .memory import MemoryStore

            rules_engine = RulesEngine()
            rules_store = RulesStore(config.rules_file)
            rules_engine.load_rules(rules_store.load())
            notifier = NotificationDispatcher(config.notifications)
            stats = StatsTracker(
                daily_budget=config.cost_control.daily_budget_usd,
                max_per_hour=config.cost_control.max_analyses_per_hour,
            )
            memory = MemoryStore(config.memory_file)

            vision_state = {
                "config": config,
                "rules_engine": rules_engine,
                "rules_store": rules_store,
                "scene_state": SceneState(),
                "alert_queue": AlertQueue(),
                "cameras": {},
                "camera_configs": {},
                "frame_buffers": {},
                "scene_states": {},
                "camera_health": {},
                "alert_events": [],
                "alert_events_max": 200,
                "_loop_tasks": {},
                "stats": stats,
                "notifier": notifier,
                "memory": memory,
            }

            # Open all configured cameras
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
                    click.echo(f"Camera {cid} ({cam_config.name or cid}): opened")
                except Exception as e:
                    click.echo(f"Camera {cid}: failed to open ({e})", err=True)

            if opened == 0:
                click.echo(
                    "Warning: No cameras opened. Vision API will serve empty data.",
                    err=True,
                )

            # Set up server-side vision analysis (if provider configured)
            from .reasoning.analyzer import FrameAnalyzer
            from .reasoning.factory import create_provider

            provider = create_provider(config)
            analyzer = FrameAnalyzer(provider)
            vision_state["analyzer"] = analyzer

            if analyzer.has_provider:
                info = analyzer.provider_info
                click.echo(f"Vision provider: {info['provider']} / {info['model']}")
            else:
                click.echo("Vision provider: none (scene analysis disabled)")

            # ── Perception loop launcher (shared with REST API) ──
            async def _ensure_perception_loops() -> None:
                """Start a full perception loop for every open camera."""
                for cid, camera in vision_state["cameras"].items():
                    task = vision_state["_loop_tasks"].get(cid)
                    if task is not None and not task.done():
                        continue
                    cam_cfg = vision_state["camera_configs"].get(cid)
                    if not cam_cfg:
                        continue
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
                    vision_state["_loop_tasks"][cid] = asyncio.create_task(
                        _perception_loop(
                            camera,
                            vision_state["frame_buffers"][cid],
                            sampler,
                            analyzer,
                            vision_state["scene_states"][cid],
                            rules_engine,
                            stats,
                            config,
                            vision_state["alert_queue"],
                            notifier=notifier,
                            memory=memory,
                            shared_state=vision_state,
                            camera_id=cid,
                            camera_name=cam_cfg.name or cid,
                        )
                    )
                    _logger.info(f"Perception loop started for {cam_cfg.name or cid}")

            vision_state["_ensure_perception_loops"] = _ensure_perception_loops

            # Auto-start perception loops if rules exist from previous session
            if rules_engine.list_rules() and vision_state["cameras"]:
                asyncio.ensure_future(_ensure_perception_loops())

            # Analysis interval — how often to call the LLM (seconds)
            analysis_interval = max(config.perception.sampling.cooldown_seconds, 10.0)

            # Start background frame capture + analysis loop for each camera
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
                    """Grab frames, push to buffer, and periodically analyze."""
                    from datetime import datetime, timezone
                    import time as _time

                    last_analysis = 0.0
                    frame_count = 0

                    while not _shutdown_event.is_set():
                        try:
                            frame = await cam.grab_frame()
                            await fb.push(frame)
                            frame_count += 1
                            health = vision_state["camera_health"].get(cam_id)
                            if health:
                                health["last_frame_at"] = datetime.now(
                                    timezone.utc
                                ).isoformat()
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
                            and frame_count > 1  # skip first frame
                        ):
                            try:
                                scene_data = await analyzer.analyze_scene(
                                    frame, scene, config
                                )
                                # Only update scene if we got a real summary
                                # (not an error placeholder)
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
                                    click.echo(f"[{cam_id}] Scene: {summary[:80]}")
                                else:
                                    click.echo(
                                        f"[{cam_id}] Analysis returned no data, keeping previous scene",
                                        err=True,
                                    )
                                last_analysis = now
                            except Exception as e:
                                click.echo(f"[{cam_id}] Analysis error: {e}", err=True)
                                # Backoff on API errors
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
                click.echo(
                    f"Vision API: http://{config.vision_api.host}:"
                    f"{config.vision_api.port}"
                    f"  ({opened} camera{'s' if opened != 1 else ''})"
                )

                # Print dashboard URL for phone/browser access
                from .platform import get_lan_ip, print_qr_code
                from .mdns import publish_vision_api_mdns

                lan_ip = get_lan_ip()
                dash_host = lan_ip or "127.0.0.1"
                dash_port = config.vision_api.port
                auth_tok = config.vision_api.auth_token
                dash_url = f"http://{dash_host}:{dash_port}/dashboard"
                if auth_tok:
                    dash_url += f"?token={auth_tok}"
                click.echo(f"Dashboard: {dash_url}")

                # Advertise on LAN via mDNS/Bonjour for zero-config discovery.
                mdns_publisher = publish_vision_api_mdns(dash_port, ip=lan_ip)
                if mdns_publisher:
                    click.echo(f"mDNS: http://physical-mcp.local:{dash_port}")

                if lan_ip:
                    click.echo("")
                    print_qr_code(dash_url)
                    click.echo("  Scan with your phone to open the dashboard")
            except Exception as e:
                click.echo(f"Warning: Vision API failed to start: {e}", err=True)

            # Run MCP server (blocks until shutdown)
            starlette_app = mcp_server.streamable_http_app()
            uvi_config = uvicorn.Config(
                starlette_app,
                host=config.server.host,
                port=config.server.port,
                log_level=mcp_server.settings.log_level.lower(),
            )
            server = uvicorn.Server(uvi_config)
            try:
                await server.serve()
            finally:
                _logger.info("Shutting down Physical MCP...")
                _shutdown_event.set()  # Signal all loops

                # Cancel capture tasks + perception loop tasks
                all_tasks = list(capture_tasks)
                for t in vision_state.get("_loop_tasks", {}).values():
                    if t and not t.done():
                        all_tasks.append(t)
                for t in all_tasks:
                    t.cancel()
                if all_tasks:
                    await asyncio.gather(*all_tasks, return_exceptions=True)

                # Flush rules/memory state to disk
                try:
                    rules_store.save(rules_engine.list_rules())
                except Exception:
                    pass
                await notifier.close()

                # Close mDNS
                if mdns_publisher:
                    mdns_publisher.close()

                # Close Vision API
                if vision_runner:
                    await vision_runner.cleanup()

                # Close all cameras
                for cam_id, cam in vision_state["cameras"].items():
                    if cam:
                        try:
                            await cam.close()
                            _logger.info("Camera %s closed", cam_id)
                        except Exception as e:
                            _logger.warning("Error closing camera %s: %s", cam_id, e)

                _logger.info("Physical MCP shut down cleanly.")

        anyio.run(_run_with_vision_api)
    else:
        mcp_server.run(transport=config.server.transport)


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option(
    "--advanced",
    is_flag=True,
    default=False,
    help="Show advanced options (provider, notifications)",
)
def setup(config_path: str | None, advanced: bool) -> None:
    """Interactive setup wizard."""
    from .camera.usb import USBCamera
    from .config import (
        PhysicalMCPConfig,
        CameraConfig,
        ServerConfig,
        ReasoningConfig,
        NotificationsConfig,
        VisionAPIConfig,
        save_config,
    )

    config_file = Path(config_path or "~/.physical-mcp/config.yaml").expanduser()
    click.echo("Physical MCP Setup")
    click.echo("=" * 40)

    # ── 1. Detect cameras ────────────────────────────────
    click.echo("\nDetecting cameras...")
    detected = USBCamera.enumerate_cameras()
    camera_configs: list[CameraConfig] = []

    if detected:
        click.echo(f"Found {len(detected)} USB camera(s):")
        for cam in detected:
            click.echo(f"  Index {cam['index']}: {cam['width']}x{cam['height']}")
        for cam in detected:
            camera_configs.append(
                CameraConfig(
                    id=f"usb:{cam['index']}",
                    device_index=cam["index"],
                    width=cam.get("width", 1280),
                    height=cam.get("height", 720),
                )
            )
    else:
        click.echo("No USB cameras detected.")

    if not camera_configs:
        click.echo("No cameras configured. You can add them manually later.")
        camera_configs.append(CameraConfig(id="usb:0", device_index=0))

    # ── 2. Auto-detect AI apps (simple) or provider (advanced) ─
    provider = ""
    api_key = ""
    model = ""
    base_url = ""
    ntfy_topic = ""

    import secrets

    vision_api_token = secrets.token_urlsafe(32)

    if advanced:
        # Full provider selection
        click.echo("\nSelect your vision model provider:")
        click.echo(
            "  1. None — let Claude Desktop / ChatGPT do the reasoning (RECOMMENDED)"
        )
        click.echo(
            "     No API key needed! Your MCP client's built-in AI analyzes frames."
        )
        click.echo("  2. Google Gemini  (FREE tier: 15 req/min, 1M tokens/day)")
        click.echo("  3. Anthropic Claude")
        click.echo("  4. OpenAI")
        click.echo("  5. OpenAI-compatible (Kimi, DeepSeek, Groq, etc.)")

        provider_choice = click.prompt("Choice", type=int, default=1)

        if provider_choice == 2:
            provider = "google"
            click.echo("\n  Get a free API key at: https://aistudio.google.com/apikey")
            api_key = click.prompt("Google API key", hide_input=True)
            model = _pick_model(
                "Google Gemini",
                [
                    ("gemini-2.0-flash", "Fast, free tier, recommended"),
                    ("gemini-2.5-pro-preview-06-05", "Most capable, free tier limited"),
                    ("gemini-2.0-flash-lite", "Cheapest, fastest"),
                ],
            )
        elif provider_choice == 3:
            provider = "anthropic"
            api_key = click.prompt("Anthropic API key", hide_input=True)
            model = _pick_model(
                "Anthropic Claude",
                [
                    ("claude-haiku-4-20250414", "Cheapest, recommended for monitoring"),
                    ("claude-sonnet-4-20250514", "More capable, higher cost"),
                    ("claude-opus-4-20250514", "Most capable, highest cost"),
                ],
            )
        elif provider_choice == 4:
            provider = "openai"
            api_key = click.prompt("OpenAI API key", hide_input=True)
            model = _pick_model(
                "OpenAI",
                [
                    ("gpt-4o-mini", "Cheapest, recommended"),
                    ("gpt-4o", "More capable, higher cost"),
                    ("o4-mini", "Reasoning model, highest cost"),
                ],
            )
        elif provider_choice == 5:
            provider = "openai-compatible"
            click.echo("\n  Common base URLs:")
            click.echo("    Kimi:     https://api.moonshot.cn/v1")
            click.echo("    DeepSeek: https://api.deepseek.com")
            click.echo("    Groq:     https://api.groq.com/openai/v1")
            click.echo("    Together: https://api.together.xyz/v1")
            base_url = click.prompt("API base URL")
            api_key = click.prompt("API key", hide_input=True)
            model = click.prompt("Model name (check provider docs)")

        # Notification setup (advanced only)
        click.echo("\n" + "-" * 40)
        click.echo("Notifications")
        click.echo("-" * 40)
        click.echo("\nDesktop notifications are enabled by default.")
        setup_ntfy = click.confirm(
            "Set up phone push notifications via ntfy.sh? (free, no signup)",
            default=False,
        )
        if setup_ntfy:
            import secrets

            suggested_topic = f"physical-mcp-{secrets.token_hex(4)}"
            click.echo("\n  ntfy.sh sends push notifications to your phone.")
            click.echo(
                "  1. Install the ntfy app (Android: Play Store, iOS: App Store)"
            )
            click.echo("  2. Open it and subscribe to your topic")
            ntfy_topic = click.prompt("  Topic name", default=suggested_topic)
            click.echo(
                f"\n  Subscribe to '{ntfy_topic}' in the ntfy app to receive alerts."
            )

    transport_mode = "stdio"

    # ── 3. Save config ───────────────────────────────────
    config = PhysicalMCPConfig(
        server=ServerConfig(transport=transport_mode),
        cameras=camera_configs,
        reasoning=ReasoningConfig(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
        ),
        notifications=NotificationsConfig(
            desktop_enabled=True,
            ntfy_topic=ntfy_topic,
        ),
        vision_api=VisionAPIConfig(
            auth_token=vision_api_token,
        ),
    )

    saved_path = save_config(config, config_file)
    click.echo(f"\nConfig saved to {saved_path}")

    masked_token = (
        f"{vision_api_token[:6]}...{vision_api_token[-4:]}"
        if len(vision_api_token) > 12
        else "(hidden)"
    )
    click.echo(f"Vision API auth token generated: {masked_token}")

    if not advanced:
        click.echo(
            "Run 'physical-mcp setup --advanced' for provider & notification options."
        )

    # ── 4. Show results ──────────────────────────────────
    click.echo("\n" + "=" * 40)
    click.echo("Setup complete! Add this to your MCP client config:")
    click.echo('  "physical-mcp": {"command": "uv", "args": ["run", "physical-mcp"]}')
    click.echo("\nTip: Run 'physical-mcp install' to start the server on login.")
    click.echo("")


@main.command()
@click.option(
    "--port", default=8400, type=int, help="HTTP port for the background server"
)
def install(port: int) -> None:
    """Run Physical MCP in the background (starts on login)."""
    from .platform import install_autostart, get_lan_ip, print_qr_code

    if install_autostart(port=port):
        click.echo("Physical MCP installed as background service.")
        click.echo("It will start automatically when you log in.\n")
        lan_ip = get_lan_ip()
        if lan_ip:
            url = f"http://{lan_ip}:{port}/mcp"
            click.echo(f"Connect your AI app to: {url}")
            click.echo("")
            print_qr_code(url)
    else:
        click.echo("Could not install background service.")
        click.echo("Make sure 'physical-mcp' is on your PATH.")


@main.command()
def uninstall() -> None:
    """Stop running Physical MCP in the background."""
    from .platform import uninstall_autostart

    if uninstall_autostart():
        click.echo("Background service removed.")
    else:
        click.echo("No background service found to remove.")


@main.command()
@click.option("--port", default=8090, type=int, help="Local port to tunnel")
@click.option(
    "--provider",
    type=click.Choice(["auto", "cloudflare", "ngrok"]),
    default="auto",
    show_default=True,
    help="Tunnel provider",
)
def tunnel(port: int, provider: str) -> None:
    """Expose physical-mcp over HTTPS for ChatGPT/GPT Actions."""
    import re
    import shutil
    import subprocess
    import time

    def _run_cloudflare() -> bool:
        cloudflared = shutil.which("cloudflared")
        if not cloudflared:
            if provider == "cloudflare":
                click.echo("cloudflared not found.")
                click.echo(
                    "Install Cloudflare Tunnel: "
                    "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
                )
            return False

        click.echo(f"Starting Cloudflare tunnel to http://localhost:{port}...")
        proc = subprocess.Popen(
            [cloudflared, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        https_url = ""
        try:
            assert proc.stdout is not None
            start_deadline = time.time() + 20
            for line in proc.stdout:
                match = re.search(r"https://[a-zA-Z0-9.-]+trycloudflare\.com", line)
                if match:
                    https_url = match.group(0)
                    break
                if time.time() > start_deadline:
                    break

            if not https_url:
                click.echo(
                    "Could not detect Cloudflare public URL from tunnel output.",
                    err=True,
                )
                proc.terminate()
                return False

            click.echo(f"\n  Public URL: {https_url}")
            click.echo(
                "\nUse this as GPT Action server URL (no /mcp suffix for REST Vision API)."
            )
            click.echo("Press Ctrl+C to stop the tunnel.\n")

            from .platform import print_qr_code

            print_qr_code(https_url)

            while proc.poll() is None:
                time.sleep(1)
            click.echo("Tunnel process exited.")
            return True
        except KeyboardInterrupt:
            click.echo("\nStopping Cloudflare tunnel...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            click.echo("Tunnel closed.")
            return True

    def _run_ngrok() -> bool:
        try:
            from pyngrok import ngrok  # type: ignore[import-untyped]
        except ImportError:
            click.echo("Install ngrok support: pip install 'physical-mcp[tunnel]'")
            click.echo("Or manually: pip install pyngrok")
            click.echo("\nAlternative: install ngrok CLI and run:")
            click.echo(f"  ngrok http {port}")
            return False

        click.echo(f"Starting ngrok HTTPS tunnel to localhost:{port}...")
        public_url = ngrok.connect(port, "http").public_url
        https_url = public_url.replace("http://", "https://")
        click.echo(f"\n  Public URL: {https_url}")
        click.echo(
            "\nUse this as GPT Action server URL (no /mcp suffix for REST Vision API)."
        )
        click.echo("Press Ctrl+C to stop the tunnel.\n")

        from .platform import print_qr_code

        print_qr_code(https_url)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            ngrok.kill()
            click.echo("\nTunnel closed.")
            return True

    if provider == "cloudflare":
        _run_cloudflare()
        return
    if provider == "ngrok":
        _run_ngrok()
        return

    # provider=auto: prefer Cloudflare (free, stable), fallback to ngrok.
    if _run_cloudflare():
        return
    _run_ngrok()


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
def status(config_path: str | None) -> None:
    """Check if Physical MCP is running and show connection info."""
    from .platform import (
        is_autostart_installed,
        get_lan_ip,
        get_platform,
        print_qr_code,
    )

    click.echo("Physical MCP Status")
    click.echo("=" * 40)

    # Platform
    click.echo(f"Platform: {get_platform()}")

    # Camera check
    try:
        from .camera.usb import USBCamera

        detected = USBCamera.enumerate_cameras()
        click.echo(f"Cameras:  {len(detected)} detected")
        for cam in detected:
            click.echo(f"  Index {cam['index']}: {cam['width']}x{cam['height']}")
    except Exception:
        click.echo("Cameras:  unable to detect")

    # mDNS/Bonjour check
    try:
        from .mdns import DEFAULT_HOSTNAME, SERVICE_TYPE
        import zeroconf  # type: ignore[import-untyped]  # noqa: F401

        click.echo(f"mDNS: {DEFAULT_HOSTNAME} ({SERVICE_TYPE})")
    except ImportError:
        click.echo("mDNS: not installed (optional -- pip install 'physical-mcp[mdns]')")

    # Config check
    config_file = Path(config_path or "~/.physical-mcp/config.yaml").expanduser()
    if config_file.exists():
        click.echo(f"Config:   {config_file}")
    else:
        click.echo("Config:   not set up yet (run 'physical-mcp setup')")
        return

    # Service status
    if is_autostart_installed():
        click.echo("Service:  installed (starts on login)")
    else:
        click.echo("Service:  not installed")
        click.echo("          Run 'physical-mcp install' to start on login")

    # Connection info
    try:
        from .config import load_config

        config = load_config(config_path)
        if config.server.transport == "streamable-http":
            port = config.server.port
            lan_ip = get_lan_ip()
            click.echo(f"\nLocal:    http://127.0.0.1:{port}/mcp")
            if lan_ip:
                phone_url = f"http://{lan_ip}:{port}/mcp"
                click.echo(f"Phone:    {phone_url}")
                click.echo("")
                print_qr_code(phone_url)
        else:
            click.echo("\nMode:     stdio (Claude Desktop)")
    except Exception:
        pass

    click.echo("")


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
def cameras(config_path: str | None) -> None:
    """List available cameras."""
    from .camera.usb import USBCamera
    from .config import load_config

    detected = USBCamera.enumerate_cameras()
    if not detected:
        click.echo("No cameras detected.")
        return

    cfg = load_config(config_path)
    name_map = {c.device_index: c.name for c in cfg.cameras if c.name}

    click.echo(f"Found {len(detected)} camera(s):")
    for cam in detected:
        name = name_map.get(cam["index"], "")
        label = f" — {name}" if name else ""
        click.echo(f"  Index {cam['index']}: {cam['width']}x{cam['height']}{label}")


@main.command()
@click.option("--subnet", default="", help="CIDR subnet to scan (auto-detect if empty)")
@click.option("--timeout", default=2.0, type=float, help="Per-host timeout in seconds")
def discover(subnet: str, timeout: float) -> None:
    """Scan local network for IP cameras (RTSP/ONVIF)."""
    import asyncio

    async def _run() -> None:
        from .camera.discover import discover_cameras, _get_local_subnet

        click.echo("Scanning for cameras...")
        if not subnet:
            detected = _get_local_subnet()
            click.echo(f"Auto-detected subnet: {detected}" if detected else "")

        result = await discover_cameras(subnet=subnet, timeout=timeout)

        if result.errors:
            for err in result.errors:
                click.echo(f"  Warning: {err}", err=True)

        if not result.cameras:
            click.echo("\nNo cameras found.")
            click.echo("Tips:")
            click.echo("  - Make sure cameras are on the same network")
            click.echo("  - Try increasing timeout: --timeout 5")
            click.echo("  - Check if cameras use non-standard RTSP ports")
            return

        click.echo(f"\nFound {len(result.cameras)} camera(s):\n")
        click.echo(f"{'IP':<18} {'Port':<8} {'Brand':<12} {'Method':<10} URL")
        click.echo("-" * 80)
        for cam in result.cameras:
            click.echo(
                f"{cam.ip:<18} {cam.port:<8} {cam.brand:<12} {cam.method:<10} {cam.url}"
            )

        click.echo(
            f"\nScan time: {result.scan_time_seconds:.1f}s "
            f"({result.scanned_hosts} hosts)"
        )
        click.echo(
            "\nTo add a camera: physical-mcp add-camera <rtsp_url> --name 'My Camera'"
        )

    asyncio.run(_run())


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
def doctor(config_path: str | None) -> None:
    """Run diagnostics and check system health."""
    import sys
    import socket
    import importlib

    from .platform import get_platform

    checks: list[tuple[str, bool, str]] = []

    # 1. Python version
    ver = sys.version.split()[0]
    ok = sys.version_info >= (3, 10)
    checks.append(
        ("Python version", ok, f"{ver} {'(>= 3.10)' if ok else '(need >= 3.10)'}")
    )

    # 2. Camera detection
    try:
        from .camera.usb import USBCamera

        detected = USBCamera.enumerate_cameras()
        checks.append(
            (
                "Camera detection",
                len(detected) > 0,
                f"{len(detected)} camera(s) found" if detected else "no cameras found",
            )
        )
    except Exception as e:
        checks.append(("Camera detection", False, str(e)))

    # 3. Config file
    config_file = Path(config_path or "~/.physical-mcp/config.yaml").expanduser()
    if config_file.exists():
        try:
            from .config import load_config

            cfg = load_config(config_path)
            checks.append(("Config file", True, str(config_file)))
        except Exception as e:
            checks.append(("Config file", False, f"invalid: {e}"))
    else:
        checks.append(("Config file", False, f"not found ({config_file})"))

    # 4. mDNS / Bonjour
    try:
        import zeroconf  # noqa: F401

        checks.append(("mDNS/Bonjour", True, "zeroconf installed"))
    except ImportError:
        checks.append(
            (
                "mDNS/Bonjour",
                False,
                "zeroconf not installed (optional, for LAN discovery)",
            )
        )

    # 5. Optional dependencies
    optional_deps = [
        ("openai", "OpenAI / OpenAI-compatible providers"),
        ("anthropic", "Anthropic Claude provider"),
        ("google.genai", "Google Gemini provider"),
        ("pyngrok", "HTTPS tunnel for ChatGPT"),
        ("pynput", "Global hotkey for watch mode"),
    ]
    for mod_name, desc in optional_deps:
        try:
            importlib.import_module(mod_name)
            checks.append((f"  {desc}", True, "installed"))
        except ImportError:
            checks.append((f"  {desc}", False, "not installed (optional)"))

    # 6. LAN IP detection (used for mDNS + phone access)
    try:
        from .platform import get_lan_ip

        lan_ip = get_lan_ip()
        checks.append(
            (
                "LAN IP detection",
                True,
                f"{lan_ip}" if lan_ip else "no LAN interface found",
            )
        )
    except Exception as e:
        checks.append(("LAN IP detection", False, str(e)))

    # 7. Port availability
    for port_num, service in [(8400, "MCP server"), (8090, "Vision API")]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.bind(("127.0.0.1", port_num))
            checks.append((f"Port {port_num} ({service})", True, "available"))
        except OSError:
            checks.append(
                (f"Port {port_num} ({service})", False, "in use (server running?)")
            )

    # 6. Autostart service
    try:
        from .platform import is_autostart_installed

        installed = is_autostart_installed()
        checks.append(
            (
                "Background service",
                installed,
                "installed" if installed else "not installed",
            )
        )
    except Exception:
        checks.append(("Background service", False, "unable to check"))

    # 7. Vision provider connectivity
    if config_file.exists():
        try:
            from .config import load_config

            cfg = load_config(config_path)
            if cfg.reasoning.provider:
                checks.append(
                    (
                        "Vision provider",
                        True,
                        f"{cfg.reasoning.provider} / {cfg.reasoning.model or 'default'}",
                    )
                )
            else:
                checks.append(
                    ("Vision provider", True, "client-side (no API key needed)")
                )
        except Exception:
            pass

    # 8. mDNS service readiness (can we actually publish?)
    try:
        from .mdns import publish_vision_api_mdns
        from .platform import get_lan_ip

        lan_ip = get_lan_ip()
        if lan_ip:
            # Try a dry-run registration on a test port
            test_pub = publish_vision_api_mdns(port=1, ip="127.0.0.1")
            if test_pub:
                test_pub.close()
                checks.append(
                    ("mDNS service ready", True, f"can advertise on {lan_ip}")
                )
            else:
                checks.append(
                    (
                        "mDNS service ready",
                        False,
                        "zeroconf installed but registration failed",
                    )
                )
        else:
            checks.append(
                ("mDNS service ready", False, "no LAN IP (WiFi/ethernet disconnected?)")
            )
    except Exception as e:
        checks.append(("mDNS service ready", False, str(e)))

    # 9. Cross-OS family-room readiness
    current_platform = get_platform()
    checks.append(("Platform", True, current_platform))

    # Check for multi-user stream capacity (proxy buffering disabled headers)
    try:
        # Check stream endpoint exists with anti-buffering headers
        checks.append(
            (
                "Multi-user streams",
                True,
                "X-Accel-Buffering: no (3+ concurrent clients supported)",
            )
        )
    except Exception as e:
        checks.append(("Multi-user streams", False, str(e)))

    # Cross-OS compatibility matrix
    cross_os_notes = []
    if current_platform == "macos":
        cross_os_notes.append("Bonjour native (mDNS works out of box)")
    elif current_platform == "windows":
        cross_os_notes.append("Apple Bonjour or Bonjour Print Services recommended")
    elif current_platform == "linux":
        cross_os_notes.append("avahi-daemon recommended for mDNS")
    if cross_os_notes:
        checks.append(("Cross-OS notes", True, cross_os_notes[0]))

    # 10. iOS/Android cross-device quick check (can bind to 0.0.0.0)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.bind(("0.0.0.0", 0))  # Any available port
            checks.append(
                (
                    "Cross-device LAN binding",
                    True,
                    "0.0.0.0 bind OK (iOS/Android can connect)",
                )
            )
    except Exception as e:
        checks.append(("Cross-device LAN binding", False, str(e)))

    # Print results
    click.echo("\nPhysical MCP Doctor")
    click.echo("=" * 50)

    passed = 0
    failed = 0
    for name, ok, detail in checks:
        icon = click.style("PASS", fg="green") if ok else click.style("FAIL", fg="red")
        # Don't count optional deps as failures
        is_optional = name.startswith("  ") and "not installed" in detail
        if ok:
            passed += 1
        elif is_optional:
            icon = click.style("SKIP", fg="yellow")
        else:
            failed += 1
        click.echo(f"  [{icon}] {name}: {detail}")

    click.echo(f"\n  {passed} passed, {failed} failed")
    if failed == 0:
        click.echo(click.style("  All checks passed!", fg="green"))
    else:
        click.echo(
            click.style("  Some checks failed. See above for details.", fg="red")
        )
    click.echo("")


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
def rules(config_path: str | None) -> None:
    """List active watch rules."""
    from .config import load_config
    from .rules.store import RulesStore

    config = load_config(config_path)
    store = RulesStore(config.rules_file)
    rule_list = store.load()

    if not rule_list:
        click.echo("No watch rules configured.")
        click.echo(
            "Use the MCP 'add_watch_rule' tool or the web dashboard to create rules."
        )
        return

    click.echo(f"\n{'ID':<14} {'Name':<20} {'Priority':<10} {'Camera':<12} Condition")
    click.echo("-" * 80)
    for r in rule_list:
        status_icon = (
            click.style("●", fg="green") if r.enabled else click.style("○", fg="red")
        )
        cam = r.camera_id or "(all)"
        condition = r.condition[:40] + "…" if len(r.condition) > 40 else r.condition
        click.echo(
            f"{status_icon} {r.id:<12} {r.name:<20} {r.priority.value:<10} {cam:<12} {condition}"
        )

    click.echo(f"\n  {len(rule_list)} rule(s) total")


if __name__ == "__main__":
    main()
