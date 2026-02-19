"""CLI entry point for Physical MCP."""

from __future__ import annotations

import click
from pathlib import Path

from . import __version__


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
@click.pass_context
def main(
    ctx: click.Context, config_path: str | None, transport: str | None, port: int | None
) -> None:
    """Physical MCP — Give your AI eyes."""
    if ctx.invoked_subcommand is not None:
        return

    # Auto-setup: if no config exists, run the setup wizard first
    config_file = Path(config_path or "~/.physical-mcp/config.yaml").expanduser()
    if not config_file.exists():
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

            # Build shared state with live cameras for the Vision API.
            vision_state = {
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
            from .server import _create_provider

            provider = _create_provider(config)
            analyzer = FrameAnalyzer(provider)
            vision_state["analyzer"] = analyzer

            if analyzer.has_provider:
                info = analyzer.provider_info
                click.echo(f"Vision provider: {info['provider']} / {info['model']}")
            else:
                click.echo("Vision provider: none (scene analysis disabled)")

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

                    while True:
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

                lan_ip = get_lan_ip()
                dash_host = lan_ip or "127.0.0.1"
                dash_port = config.vision_api.port
                auth_tok = config.vision_api.auth_token
                dash_url = f"http://{dash_host}:{dash_port}/dashboard"
                if auth_tok:
                    dash_url += f"?token={auth_tok}"
                click.echo(f"Dashboard: {dash_url}")
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
                for t in capture_tasks:
                    t.cancel()
                if vision_runner:
                    await vision_runner.cleanup()
                for cam in vision_state["cameras"].values():
                    if cam:
                        await cam.close()

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
    from .ai_apps import configure_all
    from .platform import get_lan_ip, print_qr_code

    config_file = Path(config_path or "~/.physical-mcp/config.yaml").expanduser()
    click.echo("Physical MCP Setup")
    click.echo("=" * 40)

    # ── 1. Detect cameras ────────────────────────────────
    click.echo("\nDetecting cameras...")
    detected = USBCamera.enumerate_cameras()
    camera_configs: list[CameraConfig] = []

    if detected:
        click.echo(f"Found {len(detected)} camera(s):")
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
        click.echo("No cameras detected. You can configure one manually later.")
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

    # ── 3. Auto-detect and configure all AI apps ─────────
    click.echo("\nDetecting AI apps...")
    statuses = configure_all()

    configured_apps: list[str] = []
    needs_http = False

    for s in statuses:
        if not s.installed:
            continue  # Silently skip apps not installed
        if s.already_configured:
            click.echo(f"  \u2713 {s.app.name} \u2014 already configured")
            configured_apps.append(s.app.name)
        elif s.newly_configured:
            click.echo(f"  \u2713 {s.app.name} \u2014 auto-configured")
            configured_apps.append(s.app.name)
        elif s.needs_url:
            needs_http = True
        elif s.error:
            click.echo(f"  \u2717 {s.app.name} \u2014 error: {s.error}")

    # Determine transport: stdio if any desktop app configured, http if needed
    any_stdio = len(configured_apps) > 0
    transport_mode = "stdio" if any_stdio else "streamable-http"

    # ── 4. Save config ───────────────────────────────────
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

    # ── 5. Show results ──────────────────────────────────
    click.echo("\n" + "=" * 40)
    if configured_apps:
        apps_str = (
            " and ".join(configured_apps)
            if len(configured_apps) <= 2
            else ", ".join(configured_apps)
        )
        click.echo(f"Restart {apps_str} to start using camera features!")

    if needs_http:
        lan_ip = get_lan_ip()
        port = config.server.port
        local_url = f"http://{lan_ip or '127.0.0.1'}:{port}/mcp"

        click.echo("\nFor phone / LAN apps:")
        click.echo(f"  {local_url}")
        click.echo("  Include auth token when calling Vision API endpoints:")
        click.echo("    Authorization: Bearer <vision_api.auth_token>")
        if lan_ip:
            click.echo("")
            print_qr_code(f"http://{lan_ip}:{port}/mcp")
            click.echo("Scan with your phone to connect.")

        click.echo("\nFor ChatGPT (requires HTTPS):")
        click.echo("  Run: physical-mcp tunnel")
        click.echo(
            "  Then paste the HTTPS URL into ChatGPT \u2192 Settings \u2192 Connectors"
        )

        click.echo("\nTip: Run 'physical-mcp install' to start the server on login.")

    if not configured_apps and not needs_http:
        click.echo(
            "No AI apps detected. Install Claude Desktop, Cursor, or another MCP client."
        )
        click.echo("Then run 'physical-mcp setup' again.")

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
@click.option("--camera", "camera_index", default=0, type=int, help="Camera index")
@click.option(
    "--paste", "-p", is_flag=True, help="Auto-paste into focused app after capture"
)
@click.option("--save", "save_path", default=None, help="Also save frame to file")
def snap(camera_index: int, paste: bool, save_path: str | None) -> None:
    """Snap camera to clipboard. Paste into any AI chat app.

    Works with ChatGPT, Claude, Gemini, Copilot, Perplexity, Qwen, Grok —
    any app that accepts image paste.
    """
    from .snap import snap as do_snap

    try:
        result = do_snap(device_index=camera_index, paste=paste, save_path=save_path)
        click.echo(f"\U0001f4f8 {result}")
        if not paste:
            import sys as _sys

            key = "Cmd+V" if _sys.platform == "darwin" else "Ctrl+V"
            click.echo(f"Paste into any chat app with {key}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--camera", "camera_index", default=0, type=int, help="Camera index")
@click.option("--paste", "-p", is_flag=True, help="Auto-paste after each capture")
@click.option("--interval", default=None, type=float, help="Auto-snap every N seconds")
@click.option(
    "--on-change", "on_change", is_flag=True, help="Auto-snap when scene changes"
)
def watch(
    camera_index: int, paste: bool, interval: float | None, on_change: bool
) -> None:
    """Continuous camera monitoring with auto-snap.

    Three modes:

      Default:     Global hotkey trigger (Cmd+Shift+C / Ctrl+Shift+C)

      --interval:  Auto-snap every N seconds (polling)

      --on-change: Auto-snap when the camera detects scene changes

    Combine with --paste to auto-paste into the focused chat app.

    Works with every AI chat app — ChatGPT, Claude, Gemini, Copilot,
    Perplexity, Qwen, Grok — on any platform.
    """
    import sys as _sys
    import time

    from .snap import snap as do_snap

    snap_count = 0

    def do_capture() -> None:
        nonlocal snap_count
        try:
            result = do_snap(device_index=camera_index, paste=paste)
            snap_count += 1
            click.echo(f"\U0001f4f8 [{snap_count}] {result}")
        except Exception as e:
            click.echo(f"Error: {e}")

    # ── Interval mode ─────────────────────────────────────────
    if interval is not None:
        click.echo(
            f"\u23f1\ufe0f  Auto-snapping every {interval}s | "
            f"Camera: {camera_index} | Paste: {'ON' if paste else 'OFF'}"
        )
        click.echo("   Press Ctrl+C to stop\n")
        try:
            while True:
                do_capture()
                time.sleep(interval)
        except KeyboardInterrupt:
            click.echo(f"\nStopped after {snap_count} snaps.")
        return

    # ── On-change mode ────────────────────────────────────────
    if on_change:
        click.echo(
            f"\U0001f504 Auto-snapping on scene changes | "
            f"Camera: {camera_index} | Paste: {'ON' if paste else 'OFF'}"
        )
        click.echo("   Press Ctrl+C to stop\n")

        import cv2
        from .perception.change_detector import ChangeDetector, ChangeLevel

        detector = ChangeDetector()
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            click.echo("Error: Cannot open camera", err=True)
            raise SystemExit(1)
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.5)
                    continue
                result = detector.detect(frame)
                if result.level != ChangeLevel.NONE:
                    click.echo(f"   Change detected: {result.level.value}")
                    do_capture()
                time.sleep(0.5)  # Check 2x per second
        except KeyboardInterrupt:
            click.echo(f"\nStopped after {snap_count} snaps.")
        finally:
            cap.release()
        return

    # ── Hotkey mode (default) ─────────────────────────────────
    try:
        from pynput import keyboard  # type: ignore[import-untyped]
    except ImportError:
        click.echo("Install hotkey support: pip install 'physical-mcp[hotkey]'")
        click.echo("Or manually: pip install pynput")
        return

    if _sys.platform == "darwin":
        mod_key = keyboard.Key.cmd
        hotkey_display = "Cmd+Shift+C"
    else:
        mod_key = keyboard.Key.ctrl
        hotkey_display = "Ctrl+Shift+C"

    combo = {mod_key, keyboard.Key.shift, keyboard.KeyCode.from_char("c")}
    pressed: set = set()

    click.echo(f"\U0001f441\ufe0f  Press {hotkey_display} to snap | Ctrl+C to stop")
    click.echo(f"   Camera: {camera_index} | Paste: {'ON' if paste else 'OFF'}\n")

    def on_press(key: object) -> None:
        pressed.add(key)
        if combo.issubset(pressed):
            do_capture()

    def on_release(key: object) -> None:
        pressed.discard(key)

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            click.echo(f"\nStopped after {snap_count} snaps.")


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
def doctor(config_path: str | None) -> None:
    """Run diagnostics and check system health."""
    import sys
    import socket
    import importlib

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

    # 4. Optional dependencies
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

    # 5. Port availability
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


if __name__ == "__main__":
    main()
