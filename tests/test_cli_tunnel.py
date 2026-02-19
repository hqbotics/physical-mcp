"""Tests for tunnel command provider selection and fallback behavior."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

from click.testing import CliRunner

from physical_mcp.__main__ import main


class _FakeCloudflaredProc:
    def __init__(self):
        self.stdout = iter(
            [
                "INF Initializing tunnel\n",
                "INF +--------------------------------------------------------------------------------------------+\n",
                "INF |  https://demo-123.trycloudflare.com                                                     |\n",
            ]
        )
        self._poll_calls = 0

    def poll(self):
        # one loop tick, then process exits
        self._poll_calls += 1
        return None if self._poll_calls == 1 else 0

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


class TestTunnelCommand:
    def test_auto_prefers_cloudflare_when_available(self, monkeypatch):
        runner = CliRunner()

        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/bin/cloudflared" if name == "cloudflared" else None,
        )
        monkeypatch.setattr(
            "subprocess.Popen", lambda *args, **kwargs: _FakeCloudflaredProc()
        )

        qr = MagicMock()
        monkeypatch.setattr("physical_mcp.platform.print_qr_code", qr)

        result = runner.invoke(main, ["tunnel", "--provider", "auto", "--port", "8090"])

        assert result.exit_code == 0
        assert "Starting Cloudflare tunnel" in result.output
        assert "https://demo-123.trycloudflare.com" in result.output
        assert "Starting ngrok" not in result.output
        qr.assert_called_once_with("https://demo-123.trycloudflare.com")

    def test_auto_falls_back_to_ngrok_when_cloudflare_missing(self, monkeypatch):
        runner = CliRunner()

        monkeypatch.setattr("shutil.which", lambda name: None)

        fake_ngrok = types.SimpleNamespace()
        fake_ngrok.connect = lambda port, proto: types.SimpleNamespace(
            public_url="http://ngrok.test"
        )
        fake_ngrok.kill = MagicMock()
        monkeypatch.setitem(
            __import__("sys").modules,
            "pyngrok",
            types.SimpleNamespace(ngrok=fake_ngrok),
        )

        qr = MagicMock()
        monkeypatch.setattr("physical_mcp.platform.print_qr_code", qr)

        # stop ngrok keepalive loop immediately
        monkeypatch.setattr(
            "time.sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
        )

        result = runner.invoke(main, ["tunnel", "--provider", "auto", "--port", "8090"])

        assert result.exit_code == 0
        assert "Starting ngrok HTTPS tunnel" in result.output
        assert "https://ngrok.test" in result.output
        fake_ngrok.kill.assert_called_once()
        qr.assert_called_once_with("https://ngrok.test")
