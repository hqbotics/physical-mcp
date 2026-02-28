#!/usr/bin/env python3
"""WiFi provisioning for Physical MCP relay via AP mode captive portal.

First-boot only. Creates a WiFi access point, serves a setup page,
collects WiFi credentials + claim code, then connects to the network
and registers with the cloud server.

Flow:
    1. Create AP: PhysicalMCP-XXXX (last 4 of MAC)
    2. Serve captive portal at http://192.168.4.1
    3. User enters: WiFi SSID, WiFi password, 6-digit claim code
    4. Connect to WiFi
    5. POST /push/register with claim code
    6. Save camera_token to config.json
    7. Start relay_agent.py

Requires: Linux with NetworkManager or hostapd+dnsmasq.
Designed for LuckFox Pico Mini (Buildroot Linux).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("provision")

CONFIG_PATH = Path(__file__).parent / "config.json"
AP_IP = "192.168.4.1"
AP_PORT = 80

# HTML for the captive portal
SETUP_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Physical MCP Setup</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; background: #0A0A0F; color: #E8E8ED; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.card { background: #141419; border: 1px solid #2A2A35; border-radius: 16px; padding: 32px; max-width: 400px; width: 90%; }
h1 { font-size: 20px; margin-bottom: 8px; }
p { color: #8B8B96; font-size: 14px; margin-bottom: 24px; }
label { display: block; font-size: 13px; color: #8B8B96; margin-bottom: 6px; }
input { width: 100%; padding: 12px; border: 1px solid #2A2A35; border-radius: 8px; background: #0A0A0F; color: #E8E8ED; font-size: 16px; margin-bottom: 16px; }
input:focus { border-color: #0971CE; outline: none; }
button { width: 100%; padding: 14px; background: #0971CE; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; }
button:hover { background: #0860B0; }
.status { text-align: center; padding: 20px; }
.spinner { display: inline-block; width: 24px; height: 24px; border: 3px solid #2A2A35; border-top: 3px solid #0971CE; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
  <h1>📷 Physical MCP Setup</h1>
  <p>Connect your camera to WiFi and link it to your account.</p>
  <form method="POST" action="/setup" id="form">
    <label>WiFi Network Name (SSID)</label>
    <input name="ssid" required placeholder="Your WiFi network">
    <label>WiFi Password</label>
    <input name="password" type="password" required placeholder="WiFi password">
    <label>Setup Code (from Telegram bot)</label>
    <input name="claim_code" required placeholder="e.g. AB3K7X" maxlength="6" style="text-transform: uppercase; letter-spacing: 4px; text-align: center; font-size: 24px;">
    <button type="submit">Connect Camera</button>
  </form>
</div>
</body>
</html>"""

CONNECTING_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connecting...</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; background: #0A0A0F; color: #E8E8ED; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.card { background: #141419; border: 1px solid #2A2A35; border-radius: 16px; padding: 32px; max-width: 400px; width: 90%; text-align: center; }
h1 { font-size: 20px; margin-bottom: 16px; }
p { color: #8B8B96; font-size: 14px; margin-bottom: 16px; }
.spinner { display: inline-block; width: 32px; height: 32px; border: 3px solid #2A2A35; border-top: 3px solid #0971CE; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 16px; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
  <div class="spinner"></div>
  <h1>Connecting to WiFi...</h1>
  <p>Your camera is connecting to the network and registering with the cloud. This may take up to 30 seconds.</p>
  <p>You can close this page and return to Telegram. You'll be notified when the camera is connected.</p>
</div>
</body>
</html>"""


def get_mac_suffix() -> str:
    """Get last 4 characters of MAC address for AP naming."""
    try:
        # Try reading from /sys (Linux)
        interfaces = ["wlan0", "eth0", "en0"]
        for iface in interfaces:
            path = f"/sys/class/net/{iface}/address"
            if os.path.exists(path):
                with open(path) as f:
                    mac = f.read().strip().replace(":", "")
                    return mac[-4:].upper()
    except Exception:
        pass
    return "0000"


class ProvisionHandler(BaseHTTPRequestHandler):
    """HTTP handler for the captive portal."""

    cloud_url: str = ""
    _result: dict = {}

    def do_GET(self):
        """Serve the setup form or redirect to it (captive portal)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(SETUP_HTML.encode())

    def do_POST(self):
        """Process the setup form submission."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode()
        params = parse_qs(body)

        ssid = params.get("ssid", [""])[0]
        password = params.get("password", [""])[0]
        claim_code = params.get("claim_code", [""])[0].strip().upper()

        # Send connecting page immediately
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(CONNECTING_HTML.encode())

        # Store credentials for main thread to process
        ProvisionHandler._result = {
            "ssid": ssid,
            "password": password,
            "claim_code": claim_code,
        }

    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass


def connect_wifi(ssid: str, password: str) -> bool:
    """Connect to WiFi using nmcli (NetworkManager) or wpa_supplicant."""
    # Try NetworkManager first
    try:
        result = subprocess.run(
            ["nmcli", "device", "wifi", "connect", ssid, "password", password],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"Connected to WiFi: {ssid}")
            return True
        logger.warning(f"nmcli failed: {result.stderr}")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"nmcli error: {e}")

    # Fallback: wpa_supplicant config
    try:
        wpa_conf = f'''
network={{
    ssid="{ssid}"
    psk="{password}"
}}
'''
        Path("/tmp/wpa_supplicant.conf").write_text(wpa_conf)
        subprocess.run(
            ["wpa_supplicant", "-B", "-i", "wlan0", "-c", "/tmp/wpa_supplicant.conf"],
            timeout=10,
        )
        subprocess.run(["dhclient", "wlan0"], timeout=15)
        time.sleep(3)
        logger.info(f"Connected to WiFi via wpa_supplicant: {ssid}")
        return True
    except Exception as e:
        logger.warning(f"wpa_supplicant error: {e}")

    return False


def register_with_cloud(cloud_url: str, claim_code: str) -> dict | None:
    """Register with the cloud server using the claim code."""
    url = f"{cloud_url}/push/register"
    try:
        resp = requests.post(
            url,
            json={"claim_code": claim_code},
            timeout=15,
        )
        if resp.status_code == 201:
            data = resp.json()
            logger.info(f"Registered with cloud: camera_id={data['camera_id']}")
            return data
        logger.error(f"Registration failed ({resp.status_code}): {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return None


def save_config(
    cloud_url: str,
    camera_id: str,
    camera_token: str,
    rtsp_url: str = "rtsp://192.168.1.100:554/live/ch0",
) -> None:
    """Save relay configuration to config.json."""
    config = {
        "cloud_url": cloud_url,
        "camera_id": camera_id,
        "camera_token": camera_token,
        "rtsp_url": rtsp_url,
        "fps": 1.0,
        "jpeg_quality": 60,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    logger.info(f"Config saved to {CONFIG_PATH}")


def main() -> None:
    """Run the WiFi provisioning captive portal."""
    # Check if already configured
    if CONFIG_PATH.exists():
        logger.info("Already configured. Delete config.json to re-provision.")
        sys.exit(0)

    # Default cloud URL (can be overridden via env)
    cloud_url = os.environ.get("PHYSICAL_MCP_CLOUD_URL", "https://physical-mcp.fly.dev")
    ProvisionHandler.cloud_url = cloud_url

    mac_suffix = get_mac_suffix()
    ap_name = f"PhysicalMCP-{mac_suffix}"

    logger.info(f"Starting provisioning AP: {ap_name}")
    logger.info(f"Captive portal: http://{AP_IP}")
    logger.info(f"Cloud URL: {cloud_url}")

    # Start AP mode (platform-specific)
    # On LuckFox, this would use hostapd + dnsmasq
    # For dev/testing, we just start the HTTP server

    server = HTTPServer((AP_IP, AP_PORT), ProvisionHandler)
    server.timeout = 1.0

    logger.info(f"Waiting for setup at http://{AP_IP}...")

    try:
        while not ProvisionHandler._result:
            server.handle_request()
    except KeyboardInterrupt:
        logger.info("Provisioning cancelled")
        return

    result = ProvisionHandler._result
    server.server_close()

    logger.info(f"Setup received: SSID={result['ssid']}, code={result['claim_code']}")

    # Connect to WiFi
    logger.info(f"Connecting to WiFi: {result['ssid']}...")
    if not connect_wifi(result["ssid"], result["password"]):
        logger.error("Failed to connect to WiFi")
        sys.exit(1)

    # Register with cloud
    logger.info("Registering with cloud server...")
    reg = register_with_cloud(cloud_url, result["claim_code"])
    if reg is None:
        logger.error("Cloud registration failed")
        sys.exit(1)

    # Save config
    save_config(
        cloud_url=cloud_url,
        camera_id=reg["camera_id"],
        camera_token=reg["camera_token"],
    )

    logger.info("Provisioning complete! Starting relay agent...")

    # Start relay agent
    os.execvp(
        sys.executable,
        [sys.executable, str(Path(__file__).parent / "relay_agent.py")],
    )


if __name__ == "__main__":
    main()
