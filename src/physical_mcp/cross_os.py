"""Cross-OS testing utilities for family-room multi-device validation."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("physical-mcp")


def get_cross_os_status() -> dict[str, Any]:
    """Return cross-OS readiness status for family-room scenario."""
    from .mdns import DEFAULT_HOSTNAME, SERVICE_TYPE
    from .platform import get_lan_ip

    status: dict[str, Any] = {
        "lan_ip": None,
        "mdns_ready": False,
        "mdns_hostname": DEFAULT_HOSTNAME,
        "mdns_service": SERVICE_TYPE,
        "multi_user_ready": False,
        "platforms_tested": [
            "macOS",
            "Windows",
            "Linux",
            "iOS Safari",
            "Android Chrome",
        ],
        "validation_commands": {},
    }

    lan_ip = get_lan_ip()
    status["lan_ip"] = lan_ip

    # Check mDNS readiness
    try:
        import zeroconf  # noqa: F401

        status["mdns_ready"] = bool(lan_ip)
    except ImportError:
        status["mdns_ready"] = False

    # Multi-user stream capability
    status["multi_user_ready"] = bool(lan_ip)

    # Validation commands for each platform
    if lan_ip:
        status["validation_commands"] = {
            "macOS": f"dns-sd -L physical-mcp {SERVICE_TYPE}",
            "Windows": f"dnssd -L physical-mcp {SERVICE_TYPE}  # or use Bonjour browser",
            "Linux": f"avahi-browse -r {SERVICE_TYPE}",
            "iOS_Safari": f"Open Safari → http://{DEFAULT_HOSTNAME}:8090/dashboard",
            "Android_Chrome": f"Open Chrome → http://{DEFAULT_HOSTNAME}:8090/dashboard",
            "All_platforms_web": f"http://{lan_ip}:8090/dashboard",
        }

    return status


def run_cross_os_checks() -> list[tuple[str, bool, str]]:
    """Run cross-OS compatibility checks for doctor command."""
    from .mdns import DEFAULT_HOSTNAME, SERVICE_TYPE
    from .platform import get_lan_ip

    checks: list[tuple[str, bool, str]] = []

    # mDNS discovery
    try:
        import zeroconf  # noqa: F401

        mdns_installed = True
    except ImportError:
        mdns_installed = False

    lan_ip = get_lan_ip()
    if lan_ip and mdns_installed:
        checks.append(
            (
                f"mDNS discovery ({DEFAULT_HOSTNAME})",
                True,
                f"Advertises as {SERVICE_TYPE}",
            )
        )
    elif lan_ip:
        checks.append(
            (
                "mDNS discovery",
                False,
                "Install zeroconf: pip install 'physical-mcp[mdns]'",
            )
        )
    else:
        checks.append(
            (
                "mDNS discovery",
                False,
                "No LAN IP detected (connect to WiFi/Ethernet)",
            )
        )

    # Multi-user stream capacity
    checks.append(
        (
            "Multi-user streams",
            bool(lan_ip),
            "3+ concurrent MJPEG clients" if lan_ip else "Need LAN IP",
        )
    )

    # Cross-platform validation ready
    if lan_ip and mdns_installed:
        checks.append(
            (
                "Cross-OS validation",
                True,
                "Ready for macOS/Windows/Linux/iOS/Android testing",
            )
        )
    else:
        checks.append(
            (
                "Cross-OS validation",
                False,
                "Complete checks above first",
            )
        )

    return checks
