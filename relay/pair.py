#!/usr/bin/env python3
"""Standalone claim-code pairing for Physical MCP relay.

Use this to pair a relay board with the cloud server when the
WiFi provisioning captive portal isn't available (e.g., during
development or when WiFi is already configured).

Usage:
    python pair.py --cloud-url https://physical-mcp.fly.dev --code AB3K7X

Or interactively:
    python pair.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).parent / "config.json"


def register(cloud_url: str, claim_code: str) -> dict | None:
    """Register with the cloud server."""
    url = f"{cloud_url.rstrip('/')}/push/register"
    try:
        resp = requests.post(url, json={"claim_code": claim_code}, timeout=15)
        if resp.status_code == 201:
            return resp.json()
        print(f"Error ({resp.status_code}): {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"Connection error: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Pair relay with Physical MCP cloud")
    parser.add_argument(
        "--cloud-url",
        default="https://physical-mcp.fly.dev",
        help="Cloud server URL",
    )
    parser.add_argument("--code", default="", help="6-digit claim code from Telegram")
    parser.add_argument(
        "--rtsp-url",
        default="rtsp://192.168.1.100:554/live/ch0",
        help="Local RTSP URL of the camera",
    )
    args = parser.parse_args()

    cloud_url = args.cloud_url
    code = args.code

    if not code:
        print("Physical MCP Relay Pairing")
        print("=" * 40)
        print(f"Cloud: {cloud_url}")
        print()
        code = input("Enter your 6-digit setup code: ").strip().upper()

    if not code:
        print("No code provided.")
        sys.exit(1)

    print(f"Registering with {cloud_url}...")
    result = register(cloud_url, code)

    if result is None:
        print("Registration failed.")
        sys.exit(1)

    # Save config
    config = {
        "cloud_url": cloud_url,
        "camera_id": result["camera_id"],
        "camera_token": result["camera_token"],
        "rtsp_url": args.rtsp_url,
        "fps": 1.0,
        "jpeg_quality": 60,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print("\nPaired successfully!")
    print(f"  Camera ID: {result['camera_id']}")
    print(f"  Push URL: {result['push_url']}")
    print(f"  Config saved to: {CONFIG_PATH}")
    print("\nRun: python relay_agent.py")


if __name__ == "__main__":
    main()
