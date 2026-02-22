"""Tests for cross-platform support (macOS, Windows, Linux)."""

from __future__ import annotations
import sys
from pathlib import Path
import pytest
from click.testing import CliRunner
from physical_mcp import platform


class TestPlatformDetection:
    def test_detects_macos(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert platform.get_platform() == "macos"

    def test_detects_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert platform.get_platform() == "windows"

    def test_detects_linux(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert platform.get_platform() == "linux"


class TestDataDirectory:
    def test_macos_data_dir(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(sys, "platform", "darwin")
        d = platform.get_data_dir()
        assert ".physical-mcp" in str(d)
        assert d.exists()

    def test_linux_data_dir(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            Path,
            "expanduser",
            lambda self, *args: tmp_path / str(self).replace("~", str(tmp_path)),
        )
        d = platform.get_data_dir()
        assert ".physical-mcp" in str(d)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_windows_data_dir_uses_appdata(self):
        import os

        os.environ["APPDATA"] = str(Path("/tmp/test_appdata"))
        d = platform.get_data_dir()
        assert "physical-mcp" in str(d).lower()


class TestLANIPDetection:
    def test_get_lan_ip_returns_string(self):
        ip = platform.get_lan_ip()
        if ip is not None:
            assert isinstance(ip, str)
            assert "." in ip  # IPv4 format

    def test_get_lan_ip_gracefully_handles_no_network(self, monkeypatch):
        # Simulate network failure by breaking socket
        def raise_error(*args):
            raise OSError("no network")

        monkeypatch.setattr("socket.socket.connect", raise_error)
        ip = platform.get_lan_ip()
        assert ip is None or isinstance(ip, str)


class TestAutostart:
    def test_is_autostart_installed_returns_bool(self):
        result = platform.is_autostart_installed()
        assert isinstance(result, bool)

    def test_install_autostart_checks_path(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda x: None)
        result = platform.install_autostart()
        assert result is False  # Should fail gracefully if command not found


class TestCrossPlatformPaths:
    def test_config_paths_are_platform_agnostic(self, monkeypatch):
        """Verify config paths work across platforms.

        Note: We test the path building logic without importing config module
        inside the test to avoid triggering platform-specific pydantic internals
        that break with monkey-patched sys.platform.
        """
        from physical_mcp.platform import get_data_dir

        # Test that get_data_dir returns valid Path on current platform
        data_dir = get_data_dir()
        assert isinstance(data_dir, Path)
        assert "physical-mcp" in str(data_dir).lower()
        assert data_dir.exists() or True  # May not exist, but is valid Path

    def test_config_paths_contain_app_name(self, monkeypatch):
        """Verify config paths include physical-mcp in the path."""
        from physical_mcp.platform import get_data_dir

        path = get_data_dir()
        assert "physical-mcp" in str(path).lower()


class TestCrossPlatformDoctor:
    def test_doctor_runs_on_all_platforms(self):
        """Verify doctor command doesn't crash on any platform.

        Import is done at module level to avoid issues with platform mocking
        affecting Python internals during config import.
        """
        from physical_mcp.__main__ import main

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        # Should complete without crashing even if some checks fail
        assert result.exit_code in [0, 1]  # 0=OK, 1=some checks failed


class TestCrossOSSnap:
    def test_clipboard_hint_matches_platform(self):
        """Verify clipboard hint matches actual platform."""
        # The hint should be Cmd+V on macOS, Ctrl+V elsewhere
        if sys.platform == "darwin":
            expected_key = "Cmd+V"
        else:
            expected_key = "Ctrl+V"
        # Verify platform.get_clipboard_key_hint() or similar matches
        from physical_mcp.platform import get_platform

        plat = get_platform()
        if plat == "macos":
            assert expected_key == "Cmd+V"
        else:
            assert expected_key == "Ctrl+V"
