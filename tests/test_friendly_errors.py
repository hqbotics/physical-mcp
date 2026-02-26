"""Tests for consumer-friendly error messages."""

from physical_mcp.exceptions import (
    CameraConnectionError,
    CameraTimeoutError,
    ConfigError,
    ProviderAuthError,
    ProviderRateLimitError,
)
from physical_mcp.friendly_errors import (
    FriendlyError,
    format_friendly_error,
    friendly_camera_error,
    friendly_config_error,
    friendly_notification_error,
    friendly_provider_error,
)


class TestFriendlyCameraErrors:
    def test_permission_denied(self):
        err = friendly_camera_error(
            CameraConnectionError("Camera not authorized to capture video")
        )
        assert "permission" in err.title.lower()
        # Fix text varies by platform (macOS: "Settings", Linux: "video group")
        assert (
            "Settings" in err.fix
            or "privacy" in err.fix.lower()
            or "video" in err.fix.lower()
        )

    def test_camera_not_found(self):
        err = friendly_camera_error(
            CameraConnectionError("Cannot open camera at index 0")
        )
        assert "not found" in err.title.lower()
        assert "plugged in" in err.fix.lower()

    def test_rtsp_connection_failed(self):
        err = friendly_camera_error(
            CameraConnectionError("Cannot open RTSP stream: rtsp://192.168.1.100")
        )
        assert "stream" in err.title.lower() or "respond" in err.title.lower()
        assert "rtsp" in err.fix.lower()

    def test_timeout(self):
        err = friendly_camera_error(CameraTimeoutError("Camera timed out after 20s"))
        assert "timed out" in err.title.lower()
        assert "restart" in err.fix.lower()

    def test_generic_camera_error(self):
        err = friendly_camera_error(Exception("Unknown weirdness"))
        assert err.title  # Should still produce something
        assert "doctor" in err.fix.lower()


class TestFriendlyProviderErrors:
    def test_auth_error(self):
        err = friendly_provider_error(ProviderAuthError("401 Unauthorized"))
        assert "key" in err.title.lower() or "invalid" in err.title.lower()
        assert "api key" in err.fix.lower() or "config" in err.fix.lower()

    def test_rate_limit(self):
        err = friendly_provider_error(ProviderRateLimitError("429 Too Many Requests"))
        assert "rate" in err.title.lower() or "limit" in err.title.lower()
        assert "retry" in err.fix.lower() or "cooldown" in err.fix.lower()

    def test_no_provider(self):
        err = friendly_provider_error(RuntimeError("No vision provider configured"))
        assert "no" in err.title.lower() and "provider" in err.title.lower()
        assert "setup" in err.fix.lower() or "config" in err.fix.lower()

    def test_generic_provider_error(self):
        err = friendly_provider_error(Exception("Something broke"))
        assert err.title
        assert err.fix


class TestFriendlyConfigErrors:
    def test_yaml_parse_error(self):
        err = friendly_config_error(ConfigError("YAML parse error at line 5"))
        assert "configuration" in err.title.lower()
        assert "syntax" in err.fix.lower() or "spacing" in err.fix.lower()

    def test_generic_config_error(self):
        err = friendly_config_error(ConfigError("missing required field"))
        assert err.title
        assert "config" in err.fix.lower()


class TestFriendlyNotificationErrors:
    def test_telegram_auth(self):
        err = friendly_notification_error(
            Exception("401 Unauthorized"), notification_type="telegram"
        )
        assert "telegram" in err.title.lower()
        assert "BotFather" in err.fix

    def test_telegram_chat_not_found(self):
        err = friendly_notification_error(
            Exception("chat not found"), notification_type="telegram"
        )
        assert "chat" in err.title.lower()
        assert "getUpdates" in err.fix

    def test_discord_error(self):
        err = friendly_notification_error(
            Exception("webhook failed"), notification_type="discord"
        )
        assert "discord" in err.title.lower()

    def test_ntfy_error(self):
        err = friendly_notification_error(
            Exception("failed to push"), notification_type="ntfy"
        )
        assert "push" in err.title.lower() or "ntfy" in err.title.lower()


class TestFormatFriendlyError:
    def test_basic_format(self):
        err = FriendlyError(
            title="Test Error",
            message="Something went wrong.",
            fix="Try restarting.",
        )
        formatted = format_friendly_error(err)
        assert "Test Error" in formatted
        assert "Something went wrong" in formatted
        assert "How to fix" in formatted
        assert "Try restarting" in formatted

    def test_format_with_docs_url(self):
        err = FriendlyError(
            title="Test",
            message="Oops",
            fix="Fix it",
            docs_url="https://docs.example.com/fix",
        )
        formatted = format_friendly_error(err)
        assert "docs.example.com" in formatted

    def test_multiline_fix(self):
        err = FriendlyError(
            title="Test",
            message="Broken",
            fix="Step 1: Do this\nStep 2: Do that\nStep 3: Done",
        )
        formatted = format_friendly_error(err)
        assert "Step 1" in formatted
        assert "Step 2" in formatted
        assert "Step 3" in formatted
