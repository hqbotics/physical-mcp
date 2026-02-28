"""Tests for setup command configuration behavior."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from physical_mcp.__main__ import main
from physical_mcp.config import load_config


class TestSetupCommand:
    def test_setup_auto_generates_vision_api_auth_token(
        self, monkeypatch, tmp_path: Path
    ):
        runner = CliRunner()
        config_path = tmp_path / "config.yaml"

        monkeypatch.setattr(
            "physical_mcp.camera.usb.USBCamera.enumerate_cameras",
            lambda: [],
        )

        # Choose developer mode (2) to skip consumer questions
        result = runner.invoke(
            main, ["setup", "--config", str(config_path)], input="2\n"
        )

        assert result.exit_code == 0
        assert config_path.exists()

        cfg = load_config(config_path)
        token = cfg.vision_api.auth_token
        assert isinstance(token, str)
        assert token != ""
        # token_urlsafe(32) usually yields >= 43 chars
        assert len(token) >= 43

    def test_setup_prints_masked_auth_token_preview(self, monkeypatch, tmp_path: Path):
        runner = CliRunner()
        config_path = tmp_path / "config.yaml"

        monkeypatch.setattr(
            "physical_mcp.camera.usb.USBCamera.enumerate_cameras",
            lambda: [],
        )
        monkeypatch.setattr(
            "secrets.token_urlsafe",
            lambda _: "tok_abcdefghijklmnopqrstuvwxyz_0123456789",
        )

        # Choose developer mode (2) to skip consumer questions
        result = runner.invoke(
            main, ["setup", "--config", str(config_path)], input="2\n"
        )

        assert result.exit_code == 0
        assert "Vision API auth token generated: tok_ab...6789" in result.output
        assert "tok_abcdefghijklmnopqrstuvwxyz_0123456789" not in result.output

    def test_setup_consumer_mode_sets_http_transport(self, monkeypatch, tmp_path: Path):
        runner = CliRunner()
        config_path = tmp_path / "config.yaml"

        monkeypatch.setattr(
            "physical_mcp.camera.usb.USBCamera.enumerate_cameras",
            lambda: [],
        )

        # Consumer mode (1), skip provider (3), skip telegram (n)
        result = runner.invoke(
            main, ["setup", "--config", str(config_path)], input="1\n3\nn\n"
        )

        assert result.exit_code == 0
        cfg = load_config(config_path)
        assert cfg.server.transport == "streamable-http"
        assert cfg.server.host == "0.0.0.0"
