"""RTSP camera auto-discovery via port scanning and ONVIF.

Finds IP cameras on the local network by:
1. Scanning common RTSP ports (554, 8554) on the local subnet
2. Trying common RTSP URL patterns on responding hosts
3. Attempting ONVIF WS-Discovery (UDP multicast on port 3702)
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse
from xml.etree import ElementTree

logger = logging.getLogger("physical-mcp")

# Common RTSP ports
RTSP_PORTS = [554, 8554]

# Common RTSP URL patterns grouped by vendor likelihood
RTSP_URL_PATTERNS = [
    # Generic (most cameras)
    "/stream1",
    "/",
    "/live",
    "/ch0_0.h264",
    "/0/av0",
    "/0",
    # Hikvision
    "/h264Preview_01_main",
    "/Streaming/Channels/101",
    # Dahua / Amcrest
    "/cam/realmonitor?channel=1&subtype=0",
    # TP-Link Tapo
    "/stream1",
    "/stream2",
    # Reolink
    "/h264Preview_01_sub",
    # Samsung
    "/profile1/media.smp",
    # Axis
    "/axis-media/media.amp",
    # CamHi / HiSilicon
    "/11",
    "/12",
]

# Common default credentials for cheap cameras
DEFAULT_CREDENTIALS = [
    ("", ""),  # no auth
    ("admin", "admin"),
    ("admin", ""),
    ("admin", "123456"),
]

# ONVIF WS-Discovery multicast address
WS_DISCOVERY_MULTICAST = "239.255.255.250"
WS_DISCOVERY_PORT = 3702


@dataclass
class DiscoveredCamera:
    """A camera found on the network."""

    ip: str
    port: int
    url: str
    brand: str = "unknown"
    model: str = ""
    name: str = ""
    method: str = "port_scan"  # "port_scan" | "onvif"


@dataclass
class DiscoveryResult:
    """Results from a camera discovery scan."""

    cameras: list[DiscoveredCamera] = field(default_factory=list)
    scanned_hosts: int = 0
    scan_time_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


def _get_local_subnet() -> str:
    """Auto-detect the local /24 subnet."""
    try:
        # Connect to a public DNS to find our LAN IP (no actual traffic sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        return str(network)
    except Exception:
        return ""


async def _scan_port(
    ip: str, port: int, timeout: float, sem: asyncio.Semaphore
) -> bool:
    """Check if a TCP port is open on a host."""
    async with sem:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
            return False


async def _probe_rtsp_url(url: str, timeout: float = 3.0) -> bool:
    """Quick test: can we TCP-connect and get an RTSP response?

    This is lighter than OpenCV — just checks if the port responds
    with something that looks like RTSP.
    """
    try:
        # Parse host:port from URL
        # rtsp://user:pass@host:port/path
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or 554

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )

        # Send RTSP OPTIONS request
        request = f"OPTIONS {url} RTSP/1.0\r\nCSeq: 1\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        # Read response (just first line)
        response = await asyncio.wait_for(reader.readline(), timeout=timeout)
        writer.close()
        await writer.wait_closed()

        # Check if it's an RTSP response
        return b"RTSP" in response

    except (asyncio.TimeoutError, OSError, ConnectionRefusedError, Exception):
        return False


async def _find_working_url(
    ip: str, port: int, timeout: float
) -> DiscoveredCamera | None:
    """Try common RTSP URL patterns on a host and return the first that works."""
    for cred_user, cred_pass in DEFAULT_CREDENTIALS:
        for pattern in RTSP_URL_PATTERNS:
            if cred_user:
                url = f"rtsp://{cred_user}:{cred_pass}@{ip}:{port}{pattern}"
            else:
                url = f"rtsp://{ip}:{port}{pattern}"

            if await _probe_rtsp_url(url, timeout=timeout):
                # Guess brand from URL pattern
                brand = "unknown"
                if "h264Preview" in pattern:
                    brand = "hikvision"
                elif "realmonitor" in pattern:
                    brand = "dahua"
                elif "ch0_0" in pattern:
                    brand = "cloudcam"
                elif "/0/av0" in pattern:
                    brand = "goke"
                elif "/profile1" in pattern:
                    brand = "samsung"
                elif "/axis-media" in pattern:
                    brand = "axis"

                return DiscoveredCamera(
                    ip=ip,
                    port=port,
                    url=url,
                    brand=brand,
                    method="port_scan",
                    name=f"Camera at {ip}",
                )

    return None


async def _onvif_discover(timeout: float = 3.0) -> list[DiscoveredCamera]:
    """ONVIF WS-Discovery via UDP multicast.

    Sends a Probe message and parses ProbeMatch responses to extract
    device XAddrs (URLs).
    """
    probe_uuid = str(uuid.uuid4())
    probe_msg = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"'
        ' xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
        ' xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
        ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        "<soap:Header>"
        "<wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>"
        f"<wsa:MessageID>uuid:{probe_uuid}</wsa:MessageID>"
        "<wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>"
        "</soap:Header>"
        "<soap:Body>"
        "<wsd:Probe>"
        "<wsd:Types>dn:NetworkVideoTransmitter</wsd:Types>"
        "</wsd:Probe>"
        "</soap:Body>"
        "</soap:Envelope>"
    )

    cameras: list[DiscoveredCamera] = []

    try:
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)

        # Send multicast probe
        sock.sendto(probe_msg.encode(), (WS_DISCOVERY_MULTICAST, WS_DISCOVERY_PORT))

        # Collect responses
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]

                # Parse XML response for XAddrs
                try:
                    root = ElementTree.fromstring(data.decode())
                    # Search for XAddrs in any namespace
                    for elem in root.iter():
                        if "XAddrs" in (
                            elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        ):
                            if elem.text:
                                # XAddrs contains space-separated URLs
                                for xaddr in elem.text.split():
                                    cameras.append(
                                        DiscoveredCamera(
                                            ip=ip,
                                            port=554,
                                            url=xaddr,
                                            brand="onvif",
                                            method="onvif",
                                            name=f"ONVIF Camera at {ip}",
                                        )
                                    )
                except ElementTree.ParseError:
                    pass

            except socket.timeout:
                break
            except OSError:
                break

        sock.close()

    except Exception as e:
        logger.debug(f"ONVIF discovery error: {e}")

    return cameras


async def discover_cameras(
    subnet: str = "",
    timeout: float = 2.0,
    try_onvif: bool = True,
    max_concurrent: int = 50,
) -> DiscoveryResult:
    """Scan local network for RTSP cameras.

    Args:
        subnet: CIDR subnet to scan (e.g. "192.168.1.0/24").
                Auto-detected from local IP if empty.
        timeout: TCP connect timeout per host/port in seconds.
        try_onvif: Also try ONVIF WS-Discovery multicast.
        max_concurrent: Max concurrent connection attempts.

    Returns:
        DiscoveryResult with found cameras, timing, and errors.
    """
    start = time.monotonic()
    result = DiscoveryResult()

    # Resolve subnet
    if not subnet:
        subnet = _get_local_subnet()
        if not subnet:
            result.errors.append("Could not auto-detect local subnet")
            return result

    try:
        network = ipaddress.IPv4Network(subnet, strict=False)
    except ValueError as e:
        result.errors.append(f"Invalid subnet: {e}")
        return result

    # Get list of host IPs (skip network and broadcast)
    hosts = [str(ip) for ip in network.hosts()]
    result.scanned_hosts = len(hosts)
    sem = asyncio.Semaphore(max_concurrent)

    logger.info(f"Scanning {len(hosts)} hosts on {subnet} for RTSP cameras...")

    # Phase 1: Port scan — find hosts with open RTSP ports
    open_hosts: list[tuple[str, int]] = []

    async def check_host_port(ip: str, port: int) -> None:
        if await _scan_port(ip, port, timeout, sem):
            open_hosts.append((ip, port))

    tasks = []
    for ip in hosts:
        for port in RTSP_PORTS:
            tasks.append(check_host_port(ip, port))

    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"Found {len(open_hosts)} open RTSP ports")

    # Phase 2: RTSP URL probing on open hosts
    probe_tasks = []
    for ip, port in open_hosts:
        probe_tasks.append(_find_working_url(ip, port, timeout))

    probe_results = await asyncio.gather(*probe_tasks, return_exceptions=True)

    for r in probe_results:
        if isinstance(r, DiscoveredCamera):
            result.cameras.append(r)

    # Phase 3: ONVIF discovery (best-effort)
    if try_onvif:
        try:
            onvif_cameras = await asyncio.to_thread(_sync_onvif_discover, timeout)
            # Deduplicate by IP
            existing_ips = {c.ip for c in result.cameras}
            for cam in onvif_cameras:
                if cam.ip not in existing_ips:
                    result.cameras.append(cam)
        except Exception as e:
            result.errors.append(f"ONVIF discovery error: {e}")

    result.scan_time_seconds = time.monotonic() - start
    logger.info(
        f"Discovery complete: {len(result.cameras)} cameras found "
        f"in {result.scan_time_seconds:.1f}s"
    )

    return result


def _sync_onvif_discover(timeout: float) -> list[DiscoveredCamera]:
    """Synchronous wrapper for ONVIF discovery (run in thread)."""
    return asyncio.run(_onvif_discover(timeout))
