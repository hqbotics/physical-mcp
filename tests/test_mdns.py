"""Tests for mDNS/Bonjour Vision API advertisement."""

from __future__ import annotations

import types

from physical_mcp.mdns import DEFAULT_HOSTNAME, SERVICE_TYPE, publish_vision_api_mdns


class _FakeServiceInfo:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeZeroconf:
    def __init__(self):
        self.registered = None
        self.unregistered = None
        self.closed = False

    def register_service(self, service_info):
        self.registered = service_info

    def unregister_service(self, service_info):
        self.unregistered = service_info

    def close(self):
        self.closed = True


def test_publish_mdns_returns_none_without_lan_ip(monkeypatch):
    monkeypatch.setattr("physical_mcp.mdns.get_lan_ip", lambda: None)
    publisher = publish_vision_api_mdns(port=8090)
    assert publisher is None


def test_publish_mdns_registers_service(monkeypatch):
    fake_zc = _FakeZeroconf()

    fake_mod = types.SimpleNamespace(
        ServiceInfo=_FakeServiceInfo, Zeroconf=lambda: fake_zc
    )

    monkeypatch.setattr("physical_mcp.mdns.get_lan_ip", lambda: "192.168.1.50")
    monkeypatch.setitem(__import__("sys").modules, "zeroconf", fake_mod)

    publisher = publish_vision_api_mdns(port=8090)
    assert publisher is not None
    assert fake_zc.registered is not None

    kwargs = fake_zc.registered.kwargs
    assert kwargs["type_"] == SERVICE_TYPE
    assert kwargs["name"] == f"physical-mcp.{SERVICE_TYPE}"
    assert kwargs["port"] == 8090
    assert kwargs["server"] == DEFAULT_HOSTNAME
    assert kwargs["properties"][b"path"] == b"/dashboard"

    publisher.close()
    assert fake_zc.unregistered is fake_zc.registered
    assert fake_zc.closed is True


def test_publish_mdns_handles_registration_error(monkeypatch):
    class _BrokenZeroconf(_FakeZeroconf):
        def register_service(self, service_info):
            raise RuntimeError("boom")

    fake_mod = types.SimpleNamespace(
        ServiceInfo=_FakeServiceInfo,
        Zeroconf=lambda: _BrokenZeroconf(),
    )
    monkeypatch.setitem(__import__("sys").modules, "zeroconf", fake_mod)

    publisher = publish_vision_api_mdns(port=8090, ip="192.168.1.33")
    assert publisher is None
