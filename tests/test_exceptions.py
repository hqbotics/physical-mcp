"""Tests for custom exception hierarchy."""

import pytest

from physical_mcp.exceptions import (
    CameraConnectionError,
    CameraError,
    CameraTimeoutError,
    ConfigError,
    PhysicalMCPError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)


class TestExceptionHierarchy:
    def test_base_exception(self):
        with pytest.raises(PhysicalMCPError):
            raise PhysicalMCPError("test")

    def test_camera_error_inherits(self):
        with pytest.raises(PhysicalMCPError):
            raise CameraError("camera fail")

    def test_camera_connection_error_inherits(self):
        with pytest.raises(CameraError):
            raise CameraConnectionError("cannot connect")
        with pytest.raises(PhysicalMCPError):
            raise CameraConnectionError("cannot connect")

    def test_camera_timeout_error_inherits(self):
        with pytest.raises(CameraError):
            raise CameraTimeoutError("no frames")

    def test_provider_error_inherits(self):
        with pytest.raises(PhysicalMCPError):
            raise ProviderError("api fail")

    def test_provider_auth_error_inherits(self):
        with pytest.raises(ProviderError):
            raise ProviderAuthError("bad key")

    def test_provider_rate_limit_inherits(self):
        with pytest.raises(ProviderError):
            raise ProviderRateLimitError("429")

    def test_config_error_inherits(self):
        with pytest.raises(PhysicalMCPError):
            raise ConfigError("bad config")

    def test_import_from_root(self):
        """Exceptions are importable from physical_mcp root."""
        from physical_mcp import CameraError as CE
        from physical_mcp import PhysicalMCPError as PE

        assert issubclass(CE, PE)
