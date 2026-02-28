#!/usr/bin/env python3
"""Physical MCP Relay Agent — RTSP pull → HTTPS POST to cloud.

Runs on a LuckFox Pico Mini (RV1106) or any small Linux board
inside the camera enclosure. Pulls RTSP from the WOSEE camera,
compresses to JPEG, and pushes to the Physical MCP cloud server.

Designed to be minimal (~150 lines), resilient, and low-power.

Usage:
    python relay_agent.py

Config is read from config.json in the same directory.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import cv2
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("relay")

CONFIG_PATH = Path(__file__).parent / "config.json"

# Defaults
DEFAULT_FPS = 1.0
DEFAULT_JPEG_QUALITY = 60
DEFAULT_RTSP_URL = "rtsp://192.168.1.100:554/live/ch0"

# Reconnection
INITIAL_BACKOFF = 2.0
MAX_BACKOFF = 60.0


def load_config() -> dict:
    """Load config from config.json."""
    if not CONFIG_PATH.exists():
        logger.error(f"Config file not found: {CONFIG_PATH}")
        logger.error("Run wifi_provision.py first to generate config.")
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    required = ["cloud_url", "camera_token", "camera_id"]
    for key in required:
        if not config.get(key):
            logger.error(f"Missing required config key: {key}")
            sys.exit(1)

    return config


def open_rtsp(url: str) -> cv2.VideoCapture:
    """Open RTSP stream with optimized settings."""
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        raise ConnectionError(f"Cannot open RTSP stream: {url}")
    logger.info(f"RTSP stream opened: {url}")
    return cap


def push_frame(
    session: requests.Session,
    cloud_url: str,
    camera_id: str,
    camera_token: str,
    jpeg_bytes: bytes,
) -> bool:
    """Push a JPEG frame to the cloud server. Returns True on success."""
    url = f"{cloud_url}/push/frame/{camera_id}"
    try:
        resp = session.post(
            url,
            data=jpeg_bytes,
            headers={
                "X-Camera-Token": camera_token,
                "Content-Type": "image/jpeg",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.warning(f"Push failed ({resp.status_code}): {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        logger.warning(f"Push error: {e}")
        return False


def main() -> None:
    """Main relay loop: RTSP pull → JPEG compress → HTTPS POST."""
    config = load_config()

    cloud_url = config["cloud_url"].rstrip("/")
    camera_id = config["camera_id"]
    camera_token = config["camera_token"]
    rtsp_url = config.get("rtsp_url", DEFAULT_RTSP_URL)
    fps = config.get("fps", DEFAULT_FPS)
    jpeg_quality = config.get("jpeg_quality", DEFAULT_JPEG_QUALITY)

    logger.info("Relay agent starting")
    logger.info(f"  Camera ID: {camera_id}")
    logger.info(f"  RTSP: {rtsp_url}")
    logger.info(f"  Cloud: {cloud_url}")
    logger.info(f"  FPS: {fps}, JPEG quality: {jpeg_quality}")

    session = requests.Session()
    cap: cv2.VideoCapture | None = None
    backoff = INITIAL_BACKOFF
    frame_count = 0
    push_count = 0
    start_time = time.monotonic()

    while True:
        # Open RTSP if needed
        if cap is None or not cap.isOpened():
            try:
                cap = open_rtsp(rtsp_url)
                backoff = INITIAL_BACKOFF
            except Exception as e:
                logger.warning(f"RTSP connect failed: {e} (retry in {backoff:.0f}s)")
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue

        # Grab frame
        ret, img = cap.read()
        if not ret:
            logger.warning("Frame grab failed, reconnecting...")
            cap.release()
            cap = None
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        # Compress to JPEG
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        if not ok:
            logger.warning("JPEG encode failed")
            time.sleep(1.0 / fps)
            continue

        jpeg_bytes = buf.tobytes()
        frame_count += 1

        # Push to cloud
        success = push_frame(session, cloud_url, camera_id, camera_token, jpeg_bytes)
        if success:
            push_count += 1
            backoff = INITIAL_BACKOFF
        else:
            backoff = min(backoff * 1.5, MAX_BACKOFF)

        # Periodic stats
        if frame_count % 60 == 0:
            elapsed = time.monotonic() - start_time
            actual_fps = frame_count / elapsed if elapsed > 0 else 0
            logger.info(
                f"Stats: {frame_count} frames, {push_count} pushed, "
                f"{actual_fps:.1f} fps, {len(jpeg_bytes) / 1024:.0f}KB/frame"
            )

        # Sleep to maintain target FPS
        time.sleep(1.0 / fps)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Relay agent stopped by user")
    except Exception as e:
        logger.error(f"Relay agent crashed: {e}")
        sys.exit(1)
