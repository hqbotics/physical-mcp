"""CLI entry point for Physical MCP."""

from __future__ import annotations

import click
from pathlib import Path


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
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option("--transport", default=None, help="Override transport: stdio | streamable-http")
@click.option("--port", default=None, type=int, help="Override HTTP port")
@click.pass_context
def main(ctx: click.Context, config_path: str | None, transport: str | None, port: int | None) -> None:
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
    if config.server.transport == "streamable-http" and config.server.host == "127.0.0.1":
        config.server.host = "0.0.0.0"

    mcp_server = create_server(config)
    mcp_server.run(transport=config.server.transport)


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option("--advanced", is_flag=True, default=False, help="Show advanced options (provider, notifications)")
def setup(config_path: str | None, advanced: bool) -> None:
    """Interactive setup wizard."""
    from .camera.usb import USBCamera
    from .config import (
        PhysicalMCPConfig, CameraConfig, ServerConfig, ReasoningConfig,
        NotificationsConfig, save_config,
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
            camera_configs.append(CameraConfig(
                id=f"usb:{cam['index']}",
                device_index=cam["index"],
                width=cam.get("width", 1280),
                height=cam.get("height", 720),
            ))
    else:
        click.echo("No cameras detected. You can configure one manually later.")
        camera_configs.append(CameraConfig(id="usb:0", device_index=0))

    # ── 2. Auto-detect AI apps (simple) or provider (advanced) ─
    provider = ""
    api_key = ""
    model = ""
    base_url = ""
    ntfy_topic = ""

    if advanced:
        # Full provider selection
        click.echo("\nSelect your vision model provider:")
        click.echo("  1. None — let Claude Desktop / ChatGPT do the reasoning (RECOMMENDED)")
        click.echo("     No API key needed! Your MCP client's built-in AI analyzes frames.")
        click.echo("  2. Google Gemini  (FREE tier: 15 req/min, 1M tokens/day)")
        click.echo("  3. Anthropic Claude")
        click.echo("  4. OpenAI")
        click.echo("  5. OpenAI-compatible (Kimi, DeepSeek, Groq, etc.)")

        provider_choice = click.prompt("Choice", type=int, default=1)

        if provider_choice == 2:
            provider = "google"
            click.echo("\n  Get a free API key at: https://aistudio.google.com/apikey")
            api_key = click.prompt("Google API key", hide_input=True)
            model = _pick_model("Google Gemini", [
                ("gemini-2.0-flash", "Fast, free tier, recommended"),
                ("gemini-2.5-pro-preview-06-05", "Most capable, free tier limited"),
                ("gemini-2.0-flash-lite", "Cheapest, fastest"),
            ])
        elif provider_choice == 3:
            provider = "anthropic"
            api_key = click.prompt("Anthropic API key", hide_input=True)
            model = _pick_model("Anthropic Claude", [
                ("claude-haiku-4-20250414", "Cheapest, recommended for monitoring"),
                ("claude-sonnet-4-20250514", "More capable, higher cost"),
                ("claude-opus-4-20250514", "Most capable, highest cost"),
            ])
        elif provider_choice == 4:
            provider = "openai"
            api_key = click.prompt("OpenAI API key", hide_input=True)
            model = _pick_model("OpenAI", [
                ("gpt-4o-mini", "Cheapest, recommended"),
                ("gpt-4o", "More capable, higher cost"),
                ("o4-mini", "Reasoning model, highest cost"),
            ])
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
            "Set up phone push notifications via ntfy.sh? (free, no signup)", default=False
        )
        if setup_ntfy:
            import secrets
            suggested_topic = f"physical-mcp-{secrets.token_hex(4)}"
            click.echo("\n  ntfy.sh sends push notifications to your phone.")
            click.echo("  1. Install the ntfy app (Android: Play Store, iOS: App Store)")
            click.echo("  2. Open it and subscribe to your topic")
            ntfy_topic = click.prompt("  Topic name", default=suggested_topic)
            click.echo(f"\n  Subscribe to '{ntfy_topic}' in the ntfy app to receive alerts.")

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
    )

    saved_path = save_config(config, config_file)
    click.echo(f"\nConfig saved to {saved_path}")

    if not advanced:
        click.echo("Run 'physical-mcp setup --advanced' for provider & notification options.")

    # ── 5. Show results ──────────────────────────────────
    click.echo("\n" + "=" * 40)
    if configured_apps:
        apps_str = " and ".join(configured_apps) if len(configured_apps) <= 2 else ", ".join(configured_apps)
        click.echo(f"Restart {apps_str} to start using camera features!")

    if needs_http:
        lan_ip = get_lan_ip()
        port = config.server.port
        url = f"http://{lan_ip or '127.0.0.1'}:{port}/mcp"
        click.echo(f"\nFor ChatGPT / Gemini / phone apps:")
        click.echo(f"  {url}")
        if lan_ip:
            click.echo("")
            print_qr_code(f"http://{lan_ip}:{port}/mcp")
            click.echo("Scan with your phone to connect.")
        click.echo("\nTip: Run 'physical-mcp install' to start the server on login.")

    if not configured_apps and not needs_http:
        click.echo("No AI apps detected. Install Claude Desktop, Cursor, or another MCP client.")
        click.echo("Then run 'physical-mcp setup' again.")

    click.echo("")


@main.command()
@click.option("--port", default=8400, type=int, help="HTTP port for the background server")
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
@click.option("--config", "config_path", default=None, help="Config file path")
def status(config_path: str | None) -> None:
    """Check if Physical MCP is running and show connection info."""
    from .platform import is_autostart_installed, get_lan_ip, get_platform, print_qr_code

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


if __name__ == "__main__":
    main()
