"""AI app registry — auto-detect and configure all MCP-compatible AI apps.

Adding a new AI app = one entry in KNOWN_APPS. No new files or classes needed.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("physical-mcp")


# ── Path helpers ────────────────────────────────────────────


def _expand_path(template: str) -> Path:
    """Expand ~ and %APPDATA% in path templates."""
    if "%APPDATA%" in template:
        appdata = os.environ.get("APPDATA", "")
        template = template.replace("%APPDATA%", appdata)
    if "%USERPROFILE%" in template:
        userprofile = os.environ.get("USERPROFILE", "")
        template = template.replace("%USERPROFILE%", userprofile)
    return Path(template).expanduser()


def _build_mcp_entry() -> dict:
    """Build the MCP server JSON entry for physical-mcp."""
    if shutil.which("uv"):
        return {"command": "uv", "args": ["run", "physical-mcp"]}
    return {"command": "physical-mcp"}


# ── Data models ─────────────────────────────────────────────


@dataclass
class AIApp:
    """Registration entry for a supported AI chat application."""

    name: str
    transport: str  # "stdio" | "http"
    config_paths: dict[str, str] = field(default_factory=dict)
    server_key: str = "mcpServers"  # JSON key for MCP servers dict
    mcp_entry_key: str = "physical-mcp"

    def get_config_path(self) -> Path | None:
        """Return config file path for the current OS, or None."""
        template = self.config_paths.get(sys.platform)
        if not template:
            return None
        return _expand_path(template)

    def is_installed(self) -> bool:
        """Check if this app appears to be installed (config dir exists)."""
        if self.transport == "http":
            return True  # HTTP apps are always "available"
        path = self.get_config_path()
        if path is None:
            return False
        return path.parent.exists()

    def is_configured(self) -> bool:
        """Check if physical-mcp is already in this app's config."""
        path = self.get_config_path()
        if path is None or not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            servers = data.get(self.server_key, {})
            return self.mcp_entry_key in servers
        except (json.JSONDecodeError, OSError):
            return False


@dataclass
class AppStatus:
    """Result of detecting/configuring one AI app."""

    app: AIApp
    installed: bool = False
    already_configured: bool = False
    newly_configured: bool = False
    needs_url: bool = False
    error: str | None = None


# ── Registry ────────────────────────────────────────────────

KNOWN_APPS: list[AIApp] = [
    AIApp(
        name="Claude Desktop",
        transport="stdio",
        config_paths={
            "darwin": "~/Library/Application Support/Claude/claude_desktop_config.json",
            "win32": "%APPDATA%/Claude/claude_desktop_config.json",
            "linux": "~/.config/Claude/claude_desktop_config.json",
        },
        server_key="mcpServers",
    ),
    AIApp(
        name="Cursor",
        transport="stdio",
        config_paths={
            "darwin": "~/.cursor/mcp.json",
            "win32": "~/.cursor/mcp.json",
            "linux": "~/.cursor/mcp.json",
        },
        server_key="mcpServers",
    ),
    AIApp(
        name="Windsurf",
        transport="stdio",
        config_paths={
            "darwin": "~/.codeium/windsurf/mcp_config.json",
            "win32": "~/.codeium/windsurf/mcp_config.json",
            "linux": "~/.codeium/windsurf/mcp_config.json",
        },
        server_key="mcpServers",
    ),
    AIApp(
        name="VS Code",
        transport="stdio",
        config_paths={
            "darwin": "~/Library/Application Support/Code/User/mcp.json",
            "win32": "%APPDATA%/Code/User/mcp.json",
            "linux": "~/.config/Code/User/mcp.json",
        },
        server_key="servers",
    ),
    # HTTP-only apps — user pastes URL or scans QR code
    AIApp(name="ChatGPT", transport="http"),
    AIApp(name="Gemini", transport="http"),
]


# ── Core functions ──────────────────────────────────────────


def configure_app(app: AIApp) -> bool:
    """Inject physical-mcp into an AI app's MCP config.

    Returns True on success. Creates backup before writing.
    """
    if app.transport == "http":
        return False  # Can't auto-configure HTTP-only apps

    path = app.get_config_path()
    if path is None:
        return False

    # Read existing config
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    servers = existing.get(app.server_key, {})
    if app.mcp_entry_key in servers:
        return True  # Already configured

    # Back up before writing
    if path.exists():
        backup = path.with_suffix(".json.bak")
        backup.write_bytes(path.read_bytes())

    # Inject our entry
    servers[app.mcp_entry_key] = _build_mcp_entry()
    existing[app.server_key] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n")
    return True


def discover_apps() -> list[AppStatus]:
    """Detect all known AI apps and their configuration status."""
    results: list[AppStatus] = []
    for app in KNOWN_APPS:
        if app.transport == "http":
            results.append(AppStatus(app=app, installed=True, needs_url=True))
        else:
            installed = app.is_installed()
            configured = app.is_configured() if installed else False
            results.append(AppStatus(
                app=app,
                installed=installed,
                already_configured=configured,
            ))
    return results


def configure_all() -> list[AppStatus]:
    """Discover all apps and silently auto-configure every installed stdio app.

    Returns the list of AppStatus with updated flags.
    Zero prompts — fully automatic.
    """
    statuses = discover_apps()

    for status in statuses:
        if not status.installed:
            continue
        if status.already_configured:
            continue
        if status.needs_url:
            continue  # HTTP apps can't be auto-configured

        try:
            if configure_app(status.app):
                status.newly_configured = True
        except Exception as e:
            status.error = str(e)
            logger.warning(f"Failed to configure {status.app.name}: {e}")

    return statuses
