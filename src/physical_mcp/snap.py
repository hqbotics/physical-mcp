"""Synchronous camera capture for the snap command.

Designed for one-shot use: opens camera, captures a frame, closes camera.
Works independently from the async MCP server — no event loop needed.
"""

from __future__ import annotations

import cv2
from pathlib import Path


def capture_frame_sync(
    device_index: int = 0,
    width: int = 1280,
    height: int = 720,
    warmup_frames: int = 5,
) -> bytes:
    """Open camera, grab frames for auto-exposure, return PNG bytes.

    Opens and closes the camera each time. Warmup frames let the
    camera's auto-exposure settle before the real capture.

    Returns PNG bytes (lossless, ideal for clipboard).
    """
    cap = cv2.VideoCapture(device_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera at index {device_index}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    # Warmup: grab frames to let auto-exposure settle
    for _ in range(warmup_frames):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Failed to capture frame")

    success, png_data = cv2.imencode(".png", frame)
    if not success:
        raise RuntimeError("Failed to encode frame as PNG")

    return png_data.tobytes()


def snap(
    device_index: int = 0,
    paste: bool = False,
    save_path: str | None = None,
) -> str:
    """Capture camera frame → clipboard → optional paste.

    Returns a human-readable status message.
    """
    from .clipboard import copy_image_to_clipboard, simulate_paste

    # Try to load config for camera resolution
    width, height = 1280, 720
    try:
        from .config import load_config

        config = load_config()
        for cam in config.cameras:
            if cam.device_index == device_index:
                width, height = cam.width, cam.height
                break
    except Exception:
        pass

    png_bytes = capture_frame_sync(device_index, width, height)

    # Save to file if requested
    if save_path:
        Path(save_path).write_bytes(png_bytes)

    # Copy to clipboard
    copy_image_to_clipboard(png_bytes)

    # Auto-paste if requested
    if paste:
        import time

        time.sleep(0.15)  # Brief delay for clipboard to settle
        simulate_paste()

    size_kb = len(png_bytes) // 1024
    return f"Captured {'and pasted ' if paste else ''}({size_kb}KB)"
