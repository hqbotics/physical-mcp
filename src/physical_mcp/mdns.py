"""mDNS / Bonjour advertisement for Vision API discovery on LAN."""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from typing import Any

from .platform import get_lan_ip

logger = logging.getLogger("physical-mcp")

SERVICE_TYPE = "_physical-mcp._tcp.local."
DEFAULT_INSTANCE = "physical-mcp"
DEFAULT_HOSTNAME = "physical-mcp.local."


@dataclass
class MDNSPublisher:
    """Lifecycle wrapper around a zeroconf service registration."""

    zeroconf: Any
    service_info: Any

    def close(self) -> None:
        """Unregister service and close underlying zeroconf socket."""
        try:
            self.zeroconf.unregister_service(self.service_info)
        except Exception as e:  # pragma: no cover - defensive cleanup
            logger.debug(f"mDNS unregister failed: {e}")
        try:
            self.zeroconf.close()
        except Exception as e:  # pragma: no cover - defensive cleanup
            logger.debug(f"mDNS close failed: {e}")


def publish_vision_api_mdns(port: int, ip: str | None = None) -> MDNSPublisher | None:
    """Advertise Vision API on LAN via Bonjour/mDNS.

    Returns an MDNSPublisher on success, otherwise None.
    """
    ip_addr = ip or get_lan_ip()
    if not ip_addr:
        logger.info("mDNS: skipped (no LAN IP detected)")
        return None

    try:
        from zeroconf import ServiceInfo, Zeroconf  # type: ignore[import-untyped]

        service_name = f"{DEFAULT_INSTANCE}.{SERVICE_TYPE}"
        service_info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=service_name,
            addresses=[socket.inet_aton(ip_addr)],
            port=port,
            properties={
                b"path": b"/dashboard",
                b"name": b"physical-mcp",
            },
            server=DEFAULT_HOSTNAME,
        )

        zeroconf = Zeroconf()
        zeroconf.register_service(service_info)
        logger.info(
            "mDNS: advertised %s at http://%s:%s",
            service_name,
            DEFAULT_HOSTNAME.rstrip("."),
            port,
        )
        return MDNSPublisher(zeroconf=zeroconf, service_info=service_info)
    except Exception as e:
        logger.warning(f"mDNS: advertisement failed: {e}")
        return None
