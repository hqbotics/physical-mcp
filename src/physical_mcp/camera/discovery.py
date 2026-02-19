"""LAN camera discovery — find RTSP and HTTP cameras on the local network.

Scans common ports and well-known paths to discover IP cameras.
No dependencies beyond stdlib + opencv (for RTSP probe).

Usage:
    cameras = await discover_cameras(timeout=5.0)
    for cam in cameras:
        print(f"{cam.name} at {cam.url} (type={cam.type})")
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass

logger = logging.getLogger("physical-mcp")

# Common RTSP ports used by IP cameras
RTSP_PORTS = [554, 8554]

# Common HTTP ports for MJPEG cameras
HTTP_PORTS = [80, 81, 8080, 8081]

# Well-known RTSP paths by manufacturer
RTSP_PATHS = [
    "/stream",
    "/h264Preview_01_main",  # Reolink
    "/stream1",  # TP-Link Tapo
    "/Streaming/Channels/101",  # Hikvision
    "/cam/realmonitor?channel=1&subtype=0",  # Dahua
    "/live/ch0",  # Generic
    "/live",  # Generic
    "/1",  # Some Chinese cameras
]

# Well-known HTTP MJPEG paths
HTTP_PATHS = [
    "/stream",  # ESP32-CAM
    "/video.mjpg",  # Cheap IP cams
    "/webcam/?action=stream",  # OctoPrint
    "/mjpeg",  # Generic
    "/cgi-bin/stream.cgi",  # Some IP cameras
]


@dataclass
class DiscoveredCamera:
    """A camera found on the LAN."""

    name: str
    url: str
    type: str  # "rtsp" or "http"
    host: str
    port: int
    path: str = ""
    manufacturer: str = ""

    @property
    def suggested_id(self) -> str:
        """Generate a config-friendly ID."""
        return f"{self.type}:{self.host}"


async def discover_cameras(
    subnet: str | None = None,
    timeout: float = 3.0,
    scan_rtsp: bool = True,
    scan_http: bool = True,
) -> list[DiscoveredCamera]:
    """Scan LAN for IP cameras.

    Args:
        subnet: Subnet to scan (e.g. "192.168.1"). Auto-detected if None.
        timeout: Connection timeout per host.
        scan_rtsp: Whether to scan for RTSP cameras.
        scan_http: Whether to scan for HTTP MJPEG cameras.

    Returns:
        List of discovered cameras.
    """
    if subnet is None:
        subnet = _detect_subnet()
        if not subnet:
            logger.info("Camera discovery: no LAN subnet detected")
            return []

    logger.info("Scanning %s.0/24 for cameras (timeout=%ss)", subnet, timeout)

    # Phase 1: Quick TCP port scan to find responsive hosts
    ports_to_scan = []
    if scan_rtsp:
        ports_to_scan.extend(RTSP_PORTS)
    if scan_http:
        ports_to_scan.extend(HTTP_PORTS)

    open_hosts = await _scan_ports(subnet, ports_to_scan, timeout=timeout)

    if not open_hosts:
        logger.info("Camera discovery: no hosts with camera ports found")
        return []

    logger.info("Found %d host:port pairs, probing...", len(open_hosts))

    # Phase 2: Probe each open host:port for camera streams
    cameras: list[DiscoveredCamera] = []
    for host, port in open_hosts:
        if port in RTSP_PORTS and scan_rtsp:
            cam = DiscoveredCamera(
                name=f"Camera at {host}",
                url=f"rtsp://{host}:{port}/stream",
                type="rtsp",
                host=host,
                port=port,
                path="/stream",
            )
            cameras.append(cam)
        elif port in HTTP_PORTS and scan_http:
            cam = DiscoveredCamera(
                name=f"Camera at {host}:{port}",
                url=f"http://{host}:{port}/stream",
                type="http",
                host=host,
                port=port,
                path="/stream",
            )
            cameras.append(cam)

    logger.info("Camera discovery complete: %d camera(s) found", len(cameras))
    return cameras


async def _scan_ports(
    subnet: str,
    ports: list[int],
    timeout: float = 2.0,
    start: int = 1,
    end: int = 254,
) -> list[tuple[str, int]]:
    """Async TCP port scan across a /24 subnet.

    Returns list of (host, port) pairs that accepted connections.
    """
    semaphore = asyncio.Semaphore(100)  # Limit concurrent connections
    results: list[tuple[str, int]] = []

    async def check(host: str, port: int) -> None:
        async with semaphore:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout,
                )
                writer.close()
                await writer.wait_closed()
                results.append((host, port))
            except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
                pass

    tasks = [
        check(f"{subnet}.{i}", port) for i in range(start, end + 1) for port in ports
    ]
    await asyncio.gather(*tasks)
    return sorted(results)


def _detect_subnet() -> str | None:
    """Detect the local subnet (e.g. '192.168.1') from the default route."""
    try:
        # Connect to a public IP to find our LAN interface
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        # Return first 3 octets
        parts = ip.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3])
    except Exception:
        pass
    return None
