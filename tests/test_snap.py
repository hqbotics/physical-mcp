"""Tests for snap and clipboard functionality."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── capture_frame_sync ────────────────────────────────────────


class TestCaptureFrameSync:
    def test_raises_on_invalid_camera(self):
        from physical_mcp.snap import capture_frame_sync

        with pytest.raises(RuntimeError, match="Cannot open camera"):
            capture_frame_sync(device_index=99)

    def test_returns_png_bytes(self):
        """Mock cv2 to test the capture flow without a real camera."""
        import numpy as np

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (
            True,
            np.zeros((720, 1280, 3), dtype=np.uint8),
        )

        with patch("physical_mcp.snap.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.imencode.return_value = (
                True,
                np.array([0x89, 0x50, 0x4E, 0x47], dtype=np.uint8),
            )
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

            from physical_mcp.snap import capture_frame_sync

            result = capture_frame_sync()

            assert isinstance(result, bytes)
            assert len(result) > 0
            mock_cap.release.assert_called_once()

    def test_raises_on_failed_read(self):
        """Test error when camera fails to read a frame."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)

        with patch("physical_mcp.snap.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

            from physical_mcp.snap import capture_frame_sync

            with pytest.raises(RuntimeError, match="Failed to capture"):
                capture_frame_sync()

            mock_cap.release.assert_called_once()


# ── snap function ─────────────────────────────────────────────


class TestSnap:
    def test_snap_captures_and_copies(self):
        from physical_mcp.snap import snap

        with (
            patch(
                "physical_mcp.snap.capture_frame_sync",
                return_value=b"fakepng",
            ) as mock_cap,
            patch("physical_mcp.clipboard.copy_image_to_clipboard") as mock_copy,
        ):
            result = snap(device_index=0)

            mock_cap.assert_called_once()
            mock_copy.assert_called_once_with(b"fakepng")
            assert "Captured" in result

    def test_snap_with_paste(self):
        from physical_mcp.snap import snap

        with (
            patch(
                "physical_mcp.snap.capture_frame_sync",
                return_value=b"fakepng",
            ),
            patch("physical_mcp.clipboard.copy_image_to_clipboard"),
            patch("physical_mcp.clipboard.simulate_paste") as mock_paste,
            patch("time.sleep"),
        ):
            result = snap(device_index=0, paste=True)

            mock_paste.assert_called_once()
            assert "pasted" in result

    def test_snap_with_save(self, tmp_path: Path):
        from physical_mcp.snap import snap

        save_file = tmp_path / "test.png"
        with (
            patch(
                "physical_mcp.snap.capture_frame_sync",
                return_value=b"fakepng",
            ),
            patch("physical_mcp.clipboard.copy_image_to_clipboard"),
        ):
            snap(device_index=0, save_path=str(save_file))

        assert save_file.exists()
        assert save_file.read_bytes() == b"fakepng"

    def test_snap_without_paste_no_simulate(self):
        from physical_mcp.snap import snap

        with (
            patch(
                "physical_mcp.snap.capture_frame_sync",
                return_value=b"fakepng",
            ),
            patch("physical_mcp.clipboard.copy_image_to_clipboard"),
            patch("physical_mcp.clipboard.simulate_paste") as mock_paste,
        ):
            snap(device_index=0, paste=False)
            mock_paste.assert_not_called()


# ── copy_image_to_clipboard ──────────────────────────────────


class TestCopyImageToClipboard:
    def test_calls_platform_specific(self):
        """Ensure the right platform function is dispatched."""
        from physical_mcp.clipboard import copy_image_to_clipboard

        png_bytes = b"\x89PNG\r\n\x1a\nfakedata"

        if sys.platform == "darwin":
            with patch("physical_mcp.clipboard._copy_macos") as mock:
                copy_image_to_clipboard(png_bytes)
                mock.assert_called_once_with(png_bytes)
        elif sys.platform == "win32":
            with patch("physical_mcp.clipboard._copy_windows") as mock:
                copy_image_to_clipboard(png_bytes)
                mock.assert_called_once_with(png_bytes)
        else:
            with patch("physical_mcp.clipboard._copy_linux") as mock:
                copy_image_to_clipboard(png_bytes)
                mock.assert_called_once_with(png_bytes)


# ── simulate_paste ────────────────────────────────────────────


class TestSimulatePaste:
    def test_calls_platform_specific(self):
        from physical_mcp.clipboard import simulate_paste

        if sys.platform == "darwin":
            with patch("physical_mcp.clipboard._paste_macos") as mock:
                simulate_paste()
                mock.assert_called_once()
        elif sys.platform == "win32":
            with patch("physical_mcp.clipboard._paste_windows") as mock:
                simulate_paste()
                mock.assert_called_once()
        else:
            with patch("physical_mcp.clipboard._paste_linux") as mock:
                simulate_paste()
                mock.assert_called_once()


# ── macOS-specific ────────────────────────────────────────────


class TestCopyMacOS:
    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_uses_osascript_jxa(self):
        from physical_mcp.clipboard import _copy_macos

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _copy_macos(b"fakepng")

            args = mock_run.call_args[0][0]
            assert args[0] == "osascript"
            assert args[1] == "-l"
            assert args[2] == "JavaScript"

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_paste_uses_applescript(self):
        from physical_mcp.clipboard import _paste_macos

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _paste_macos()

            args = mock_run.call_args[0][0]
            assert args[0] == "osascript"
            assert "System Events" in args[-1]


# ── VisionAPIConfig ──────────────────────────────────────────


class TestVisionAPIConfig:
    def test_default_config(self):
        from physical_mcp.config import VisionAPIConfig

        cfg = VisionAPIConfig()
        assert cfg.enabled is True
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8090

    def test_in_main_config(self):
        from physical_mcp.config import PhysicalMCPConfig

        cfg = PhysicalMCPConfig()
        assert cfg.vision_api.enabled is True
        assert cfg.vision_api.port == 8090

    def test_config_from_dict(self):
        from physical_mcp.config import PhysicalMCPConfig

        cfg = PhysicalMCPConfig(vision_api={"enabled": False, "port": 9000})
        assert cfg.vision_api.enabled is False
        assert cfg.vision_api.port == 9000
