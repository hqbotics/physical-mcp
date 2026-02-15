"""Cross-platform support — autostart, paths, service management.

Each function handles macOS, Windows, and Linux internally.
Pattern matches notifications/desktop.py which already does this.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

logger = logging.getLogger("physical-mcp")


# ── Platform detection ──────────────────────────────────────


def get_platform() -> str:
    """Return normalized platform name."""
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    return "linux"


def get_data_dir() -> Path:
    """Return the physical-mcp data directory, creating if needed."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "~")).expanduser()
        d = base / "physical-mcp"
    else:
        d = Path("~/.physical-mcp").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Network ─────────────────────────────────────────────────


def get_lan_ip() -> str | None:
    """Get this machine's LAN IP address via UDP socket trick."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def open_url(url: str) -> None:
    """Open a URL in the default browser."""
    webbrowser.open(url)


# ── QR code ─────────────────────────────────────────────────


def print_qr_code(url: str) -> None:
    """Print a QR code to the terminal. Fails silently if qrcode not installed."""
    try:
        import qrcode  # type: ignore[import-untyped]

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(tty=True)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"QR code generation failed: {e}")


# ── Autostart / Background Service ─────────────────────────


_LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.physical-mcp.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>{command}</string>
        <string>--transport</string>
        <string>streamable-http</string>
        <string>--port</string>
        <string>{port}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/physical-mcp.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/physical-mcp.err</string>
</dict>
</plist>
"""

_SYSTEMD_UNIT = """\
[Unit]
Description=Physical MCP Camera Server
After=network.target

[Service]
ExecStart={command} --transport streamable-http --port {port}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def install_autostart(transport: str = "streamable-http", port: int = 8400) -> bool:
    """Register physical-mcp as a background service that starts on login.

    - macOS: launchd plist in ~/Library/LaunchAgents/
    - Linux: systemd user service
    - Windows: schtasks logon trigger
    """
    command = shutil.which("physical-mcp")
    if not command:
        logger.warning("physical-mcp not found on PATH, cannot install autostart")
        return False

    try:
        if sys.platform == "darwin":
            return _install_launchd(command, port)
        elif sys.platform == "linux":
            return _install_systemd(command, port)
        elif sys.platform == "win32":
            return _install_schtasks(command, port)
    except Exception as e:
        logger.warning(f"Failed to install autostart: {e}")
    return False


def _install_launchd(command: str, port: int) -> bool:
    plist_path = Path("~/Library/LaunchAgents/com.physical-mcp.server.plist").expanduser()
    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist_content = _LAUNCHD_PLIST.format(
        command=command, port=port, log_dir=str(log_dir),
    )
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content)

    # Unload first if already loaded (idempotent)
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )
    subprocess.run(
        ["launchctl", "load", str(plist_path)],
        check=True, capture_output=True,
    )
    return True


def _install_systemd(command: str, port: int) -> bool:
    unit_path = Path("~/.config/systemd/user/physical-mcp.service").expanduser()
    unit_path.parent.mkdir(parents=True, exist_ok=True)

    unit_content = _SYSTEMD_UNIT.format(command=command, port=port)
    unit_path.write_text(unit_content)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", "physical-mcp"],
        check=True, capture_output=True,
    )
    return True


def _install_schtasks(command: str, port: int) -> bool:
    subprocess.run(
        [
            "schtasks", "/create",
            "/tn", "PhysicalMCP",
            "/tr", f'"{command}" --transport streamable-http --port {port}',
            "/sc", "onlogon",
            "/rl", "limited",
            "/f",
        ],
        check=True, capture_output=True,
    )
    return True


def uninstall_autostart() -> bool:
    """Remove the physical-mcp background service."""
    try:
        if sys.platform == "darwin":
            plist_path = Path("~/Library/LaunchAgents/com.physical-mcp.server.plist").expanduser()
            if plist_path.exists():
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
                plist_path.unlink()
                return True
        elif sys.platform == "linux":
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "physical-mcp"],
                capture_output=True,
            )
            unit_path = Path("~/.config/systemd/user/physical-mcp.service").expanduser()
            if unit_path.exists():
                unit_path.unlink()
                return True
        elif sys.platform == "win32":
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", "PhysicalMCP", "/f"],
                capture_output=True,
            )
            return result.returncode == 0
    except Exception as e:
        logger.warning(f"Failed to uninstall autostart: {e}")
    return False


def is_autostart_installed() -> bool:
    """Check if the background service is registered."""
    if sys.platform == "darwin":
        return Path("~/Library/LaunchAgents/com.physical-mcp.server.plist").expanduser().exists()
    elif sys.platform == "linux":
        return Path("~/.config/systemd/user/physical-mcp.service").expanduser().exists()
    elif sys.platform == "win32":
        result = subprocess.run(
            ["schtasks", "/query", "/tn", "PhysicalMCP"],
            capture_output=True,
        )
        return result.returncode == 0
    return False
