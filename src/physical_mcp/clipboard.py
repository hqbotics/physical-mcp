"""Cross-platform clipboard image operations.

Supports macOS, Linux, and Windows with zero Python package dependencies.
Uses OS-native tools: osascript (macOS), xclip/xsel (Linux), PowerShell (Windows).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("physical-mcp")


# ── Public API ────────────────────────────────────────────────


def copy_image_to_clipboard(png_bytes: bytes) -> None:
    """Copy PNG image bytes to the system clipboard.

    macOS:   osascript JXA — zero Python deps
    Linux:   xclip (falls back to xsel)
    Windows: PowerShell System.Windows.Forms.Clipboard
    """
    if sys.platform == "darwin":
        _copy_macos(png_bytes)
    elif sys.platform == "win32":
        _copy_windows(png_bytes)
    else:
        _copy_linux(png_bytes)


def simulate_paste() -> None:
    """Simulate Cmd+V / Ctrl+V to paste into the focused application.

    macOS:   AppleScript System Events (needs Accessibility permission)
    Linux:   xdotool
    Windows: PowerShell SendKeys
    """
    if sys.platform == "darwin":
        _paste_macos()
    elif sys.platform == "win32":
        _paste_windows()
    else:
        _paste_linux()


# ── macOS ─────────────────────────────────────────────────────


def _copy_macos(png_bytes: bytes) -> None:
    """Copy image to macOS clipboard via osascript JXA (NSPasteboard)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_bytes)
        tmp_path = f.name
    try:
        # JXA script: load image from file, copy to pasteboard
        script = (
            'ObjC.import("AppKit");'
            f'var img = $.NSImage.alloc.initWithContentsOfFile("{tmp_path}");'
            "var pb = $.NSPasteboard.generalPasteboard;"
            "pb.clearContents;"
            "pb.writeObjects($.NSArray.arrayWithObject(img));"
        )
        subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            check=True,
            capture_output=True,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _paste_macos() -> None:
    """Simulate Cmd+V on macOS via AppleScript."""
    subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ],
        check=True,
        capture_output=True,
    )


# ── Linux ─────────────────────────────────────────────────────


def _copy_linux(png_bytes: bytes) -> None:
    """Copy image to Linux clipboard via xclip (fallback: xsel)."""
    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png"],
            input=png_bytes,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        # Fallback to xsel
        subprocess.run(
            ["xsel", "--clipboard", "--input"],
            input=png_bytes,
            check=True,
            capture_output=True,
        )


def _paste_linux() -> None:
    """Simulate Ctrl+V on Linux via xdotool."""
    subprocess.run(
        ["xdotool", "key", "ctrl+v"],
        check=True,
        capture_output=True,
    )


# ── Windows ───────────────────────────────────────────────────


def _copy_windows(png_bytes: bytes) -> None:
    """Copy image to Windows clipboard via PowerShell."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_bytes)
        tmp_path = f.name
    try:
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            f'$img = [System.Drawing.Image]::FromFile("{tmp_path}");'
            "[System.Windows.Forms.Clipboard]::SetImage($img)"
        )
        subprocess.run(
            ["powershell", "-Command", ps_script],
            check=True,
            capture_output=True,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _paste_windows() -> None:
    """Simulate Ctrl+V on Windows via PowerShell SendKeys."""
    subprocess.run(
        [
            "powershell",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms;"
            '[System.Windows.Forms.SendKeys]::SendWait("^v")',
        ],
        check=True,
        capture_output=True,
    )
