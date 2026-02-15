"""Tests for AI app discovery and auto-configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from physical_mcp.ai_apps import (
    AIApp,
    AppStatus,
    KNOWN_APPS,
    _build_mcp_entry,
    _expand_path,
    configure_all,
    configure_app,
    discover_apps,
)


# ── Path helpers ────────────────────────────────────────────


class TestExpandPath:
    def test_expands_tilde(self):
        result = _expand_path("~/test/file.json")
        assert str(result).startswith("/")
        assert "~" not in str(result)

    def test_expands_appdata(self):
        with patch.dict(os.environ, {"APPDATA": "/mock/appdata"}):
            result = _expand_path("%APPDATA%/Claude/config.json")
            assert str(result) == "/mock/appdata/Claude/config.json"


# ── Registry ────────────────────────────────────────────────


class TestKnownApps:
    def test_registry_not_empty(self):
        assert len(KNOWN_APPS) > 0

    def test_all_have_names(self):
        for app in KNOWN_APPS:
            assert app.name, f"App missing name: {app}"

    def test_claude_desktop_in_registry(self):
        names = {app.name for app in KNOWN_APPS}
        assert "Claude Desktop" in names

    def test_http_apps_have_no_config_paths(self):
        for app in KNOWN_APPS:
            if app.transport == "http":
                assert app.config_paths == {}, f"{app.name} is HTTP but has config_paths"

    def test_stdio_apps_have_config_paths(self):
        for app in KNOWN_APPS:
            if app.transport == "stdio":
                assert len(app.config_paths) > 0, f"{app.name} is stdio but has no config_paths"

    def test_trae_in_known_apps(self):
        trae = next((a for a in KNOWN_APPS if a.name == "Trae"), None)
        assert trae is not None
        assert trae.transport == "stdio"
        assert trae.server_key == "mcpServers"
        assert "darwin" in trae.config_paths

    def test_codebuddy_in_known_apps(self):
        cb = next((a for a in KNOWN_APPS if a.name == "CodeBuddy"), None)
        assert cb is not None
        assert cb.transport == "stdio"
        assert cb.server_key == "mcpServers"

    def test_chatgpt_has_setup_hint(self):
        chatgpt = next((a for a in KNOWN_APPS if a.name == "ChatGPT"), None)
        assert chatgpt is not None
        assert chatgpt.setup_hint != ""
        assert "tunnel" in chatgpt.setup_hint.lower()

    def test_setup_hint_empty_for_stdio_apps(self):
        for app in KNOWN_APPS:
            if app.transport == "stdio":
                assert app.setup_hint == "", f"{app.name} is stdio but has setup_hint"


# ── AIApp methods ───────────────────────────────────────────


class TestAIApp:
    def test_get_config_path_returns_none_for_unsupported_platform(self):
        app = AIApp(
            name="Test", transport="stdio",
            config_paths={"darwin": "~/test.json"},
        )
        with patch("physical_mcp.ai_apps.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert app.get_config_path() is None

    def test_get_config_path_returns_path_for_matching_platform(self):
        app = AIApp(
            name="Test", transport="stdio",
            config_paths={"darwin": "~/test.json"},
        )
        with patch("physical_mcp.ai_apps.sys") as mock_sys:
            mock_sys.platform = "darwin"
            path = app.get_config_path()
            assert path is not None
            assert str(path).endswith("test.json")

    def test_http_app_always_installed(self):
        app = AIApp(name="ChatGPT", transport="http")
        assert app.is_installed() is True

    def test_is_configured_returns_false_when_no_config(self):
        app = AIApp(
            name="Test", transport="stdio",
            config_paths={"darwin": "/nonexistent/path/config.json"},
        )
        assert app.is_configured() is False


# ── Build MCP entry ─────────────────────────────────────────


class TestBuildMCPEntry:
    def test_uses_uv_when_available(self):
        with patch("shutil.which", return_value="/usr/bin/uv"):
            entry = _build_mcp_entry()
            assert entry["command"] == "uv"
            assert "physical-mcp" in entry["args"]

    def test_falls_back_to_direct_command(self):
        with patch("shutil.which", return_value=None):
            entry = _build_mcp_entry()
            assert entry["command"] == "physical-mcp"
            assert "args" not in entry


# ── Configure app ───────────────────────────────────────────


class TestConfigureApp:
    def test_writes_json_to_new_file(self, tmp_path: Path):
        config_path = tmp_path / "claude" / "config.json"
        app = AIApp(
            name="Test", transport="stdio",
            config_paths={},
            server_key="mcpServers",
        )
        # Override get_config_path to return our tmp path
        with patch.object(app, "get_config_path", return_value=config_path):
            result = configure_app(app)

        assert result is True
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "physical-mcp" in data["mcpServers"]

    def test_preserves_existing_servers(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        existing = {"mcpServers": {"other-server": {"command": "other"}}}
        config_path.write_text(json.dumps(existing))

        app = AIApp(
            name="Test", transport="stdio",
            config_paths={},
            server_key="mcpServers",
        )
        with patch.object(app, "get_config_path", return_value=config_path):
            configure_app(app)

        data = json.loads(config_path.read_text())
        assert "other-server" in data["mcpServers"]
        assert "physical-mcp" in data["mcpServers"]

    def test_creates_backup(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        config_path.write_text('{"existing": true}')

        app = AIApp(
            name="Test", transport="stdio",
            config_paths={},
            server_key="mcpServers",
        )
        with patch.object(app, "get_config_path", return_value=config_path):
            configure_app(app)

        backup = config_path.with_suffix(".json.bak")
        assert backup.exists()
        assert json.loads(backup.read_text()) == {"existing": True}

    def test_skips_http_apps(self):
        app = AIApp(name="ChatGPT", transport="http")
        assert configure_app(app) is False

    def test_already_configured_returns_true(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        existing = {"mcpServers": {"physical-mcp": {"command": "physical-mcp"}}}
        config_path.write_text(json.dumps(existing))

        app = AIApp(
            name="Test", transport="stdio",
            config_paths={},
            server_key="mcpServers",
        )
        with patch.object(app, "get_config_path", return_value=config_path):
            result = configure_app(app)

        assert result is True
        # Should NOT create a backup (no changes made)
        assert not config_path.with_suffix(".json.bak").exists()

    def test_configure_trae_format(self, tmp_path: Path):
        """Trae uses mcpServers key — verify the written format."""
        config_path = tmp_path / "Trae" / "User" / "mcp.json"
        # Pre-populate with existing Trae servers
        config_path.parent.mkdir(parents=True)
        existing = {"mcpServers": {"GitHub": {"command": "npx", "args": ["-y", "@mcp/server-github"]}}}
        config_path.write_text(json.dumps(existing))

        app = AIApp(
            name="Trae", transport="stdio",
            config_paths={},
            server_key="mcpServers",
        )
        with patch.object(app, "get_config_path", return_value=config_path):
            result = configure_app(app)

        assert result is True
        data = json.loads(config_path.read_text())
        assert "GitHub" in data["mcpServers"]  # Preserved
        assert "physical-mcp" in data["mcpServers"]  # Added

    def test_idempotent_no_duplicate(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        config_path.write_text("{}")

        app = AIApp(
            name="Test", transport="stdio",
            config_paths={},
            server_key="mcpServers",
        )
        with patch.object(app, "get_config_path", return_value=config_path):
            configure_app(app)
            configure_app(app)  # Run twice

        data = json.loads(config_path.read_text())
        assert len(data["mcpServers"]) == 1  # Only one entry


# ── Discover apps ───────────────────────────────────────────


class TestDiscoverApps:
    def test_returns_all_known_apps(self):
        statuses = discover_apps()
        names = {s.app.name for s in statuses}
        assert "Claude Desktop" in names
        assert "ChatGPT" in names

    def test_http_apps_always_need_url(self):
        statuses = discover_apps()
        for s in statuses:
            if s.app.transport == "http":
                assert s.needs_url is True


# ── Configure all ───────────────────────────────────────────


class TestConfigureAll:
    def test_returns_statuses_for_all_apps(self):
        statuses = configure_all()
        assert len(statuses) == len(KNOWN_APPS)

    def test_http_apps_not_configured(self):
        statuses = configure_all()
        for s in statuses:
            if s.app.transport == "http":
                assert s.newly_configured is False
                assert s.needs_url is True
