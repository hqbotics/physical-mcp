"""Consumer-friendly error messages for common issues.

Maps technical errors to human-readable messages with actionable
steps that non-technical users can follow.
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass


@dataclass
class FriendlyError:
    """A consumer-friendly error with a fix suggestion."""

    title: str
    message: str
    fix: str
    docs_url: str = ""


def friendly_camera_error(error: Exception) -> FriendlyError:
    """Convert a camera error to a consumer-friendly message."""
    msg = str(error).lower()

    # macOS camera permission denied
    if "not authorized" in msg or "permission" in msg or "tcc" in msg:
        if platform.system() == "Darwin":
            return FriendlyError(
                title="Camera permission needed",
                message="macOS is blocking camera access for this app.",
                fix=(
                    "Open System Settings > Privacy & Security > Camera, "
                    "then enable access for your terminal app (Terminal, "
                    "iTerm2, VS Code, etc.). You may need to restart the app."
                ),
            )
        elif platform.system() == "Linux":
            return FriendlyError(
                title="Camera permission needed",
                message="Linux is blocking camera access.",
                fix=(
                    "Make sure your user is in the 'video' group: "
                    "sudo usermod -aG video $USER, then log out and back in."
                ),
            )
        return FriendlyError(
            title="Camera permission denied",
            message="The system is blocking camera access.",
            fix="Check your operating system's privacy settings for camera access.",
        )

    # RTSP connection failed (check BEFORE "cannot open" — RTSP errors also contain it)
    if "rtsp" in msg or "stream" in msg:
        return FriendlyError(
            title="Camera stream not responding",
            message="Could not connect to the camera's video stream.",
            fix=(
                "Check that your camera is powered on and connected to WiFi. "
                "Verify the RTSP URL is correct. Common formats:\n"
                "  rtsp://IP:554/ch0_0.h264\n"
                "  rtsp://admin:password@IP:554/stream\n"
                "Try 'physical-mcp discover' to scan for cameras."
            ),
        )

    # Camera not found / can't open
    if "cannot open" in msg or "no camera" in msg or "device not found" in msg:
        return FriendlyError(
            title="Camera not found",
            message="No camera was detected on this device.",
            fix=(
                "Make sure your camera is plugged in and recognized by your "
                "system. Try a different USB port. For IP cameras, check that "
                "the camera is powered on and connected to your WiFi network."
            ),
        )

    # Timeout
    if "timeout" in msg or "timed out" in msg:
        return FriendlyError(
            title="Camera timed out",
            message="The camera took too long to respond.",
            fix=(
                "The camera may be busy or on a slow network. Try:\n"
                "1. Restart the camera (unplug, wait 10 seconds, plug back in)\n"
                "2. Move the camera closer to your WiFi router\n"
                "3. Check if other devices can reach the camera"
            ),
        )

    # Generic camera error
    return FriendlyError(
        title="Camera error",
        message=f"Something went wrong with the camera: {error}",
        fix="Try restarting physical-mcp and your camera. If the issue persists, run 'physical-mcp doctor' for diagnostics.",
    )


def friendly_provider_error(error: Exception) -> FriendlyError:
    """Convert a vision provider error to a consumer-friendly message."""
    msg = str(error).lower()

    # Auth / API key
    if "auth" in msg or "api key" in msg or "401" in msg or "403" in msg:
        return FriendlyError(
            title="Vision provider key invalid",
            message="Your AI vision provider API key was rejected.",
            fix=(
                "Check your API key in ~/.config/physical-mcp/config.yaml "
                "under the 'reasoning' section. Keys may have expired or "
                "been revoked. Get a new key from your provider's dashboard."
            ),
        )

    # Rate limit
    if "rate" in msg or "429" in msg or "quota" in msg or "limit" in msg:
        return FriendlyError(
            title="AI provider rate limit",
            message="Too many requests to the AI vision provider.",
            fix=(
                "The system will automatically retry with backoff. If this "
                "keeps happening:\n"
                "1. Reduce the number of active cameras\n"
                "2. Increase cooldown_seconds on your rules\n"
                "3. Upgrade your API plan or switch to a provider with "
                "higher limits"
            ),
        )

    # No provider configured
    if re.search(r"no\s.*provider", msg) or "not configured" in msg:
        return FriendlyError(
            title="No AI vision provider set up",
            message="physical-mcp needs an AI provider to analyze camera frames.",
            fix=(
                "Run 'physical-mcp setup' to configure a vision provider, or "
                "add one to ~/.config/physical-mcp/config.yaml:\n\n"
                "  reasoning:\n"
                "    provider: google\n"
                "    api_key: YOUR_API_KEY\n\n"
                "Supported providers: google (Gemini), openai (GPT-4), "
                "anthropic (Claude)."
            ),
        )

    # Generic provider error
    return FriendlyError(
        title="AI vision error",
        message=f"The AI vision provider returned an error: {error}",
        fix="This is usually temporary. The system will retry automatically. If it persists, try 'physical-mcp doctor'.",
    )


def friendly_config_error(error: Exception) -> FriendlyError:
    """Convert a configuration error to a consumer-friendly message."""
    msg = str(error).lower()

    if "yaml" in msg or "parse" in msg or "invalid" in msg:
        return FriendlyError(
            title="Configuration file error",
            message="The configuration file has a formatting issue.",
            fix=(
                "Check ~/.config/physical-mcp/config.yaml for syntax errors. "
                "Common issues:\n"
                "- Missing spaces after colons (use 'key: value' not 'key:value')\n"
                "- Incorrect indentation (use 2 spaces, not tabs)\n"
                "- Missing quotes around special characters\n"
                "Run 'physical-mcp doctor' to validate your config."
            ),
        )

    return FriendlyError(
        title="Configuration error",
        message=f"There's a problem with your setup: {error}",
        fix="Run 'physical-mcp setup' to reconfigure, or check ~/.config/physical-mcp/config.yaml",
    )


def friendly_notification_error(
    error: Exception, notification_type: str = ""
) -> FriendlyError:
    """Convert a notification delivery error to a consumer-friendly message."""
    msg = str(error).lower()

    if notification_type == "telegram" or "telegram" in msg:
        if "401" in msg or "unauthorized" in msg:
            return FriendlyError(
                title="Telegram bot token invalid",
                message="Your Telegram bot token was rejected.",
                fix=(
                    "1. Open Telegram and message @BotFather\n"
                    "2. Use /mybots to check your bot\n"
                    "3. If needed, use /revoke to get a new token\n"
                    "4. Update TELEGRAM_BOT_TOKEN in your config"
                ),
            )
        if "chat not found" in msg or "chat_id" in msg:
            return FriendlyError(
                title="Telegram chat not found",
                message="The Telegram chat ID is incorrect.",
                fix=(
                    "1. Message your bot on Telegram first\n"
                    "2. Visit: api.telegram.org/bot<TOKEN>/getUpdates\n"
                    "3. Find your chat.id in the response\n"
                    "4. Update TELEGRAM_CHAT_ID in your config"
                ),
            )

    if notification_type == "discord" or "discord" in msg:
        return FriendlyError(
            title="Discord webhook error",
            message="Could not send alert to Discord.",
            fix=(
                "Check your Discord webhook URL:\n"
                "1. In Discord, go to Channel Settings > Integrations > Webhooks\n"
                "2. Copy the webhook URL\n"
                "3. Update DISCORD_WEBHOOK_URL in your config"
            ),
        )

    if notification_type == "ntfy" or "ntfy" in msg:
        return FriendlyError(
            title="Push notification error",
            message="Could not send push notification via ntfy.",
            fix=(
                "1. Install the ntfy app on your phone (ntfy.sh)\n"
                "2. Subscribe to your topic in the app\n"
                "3. Make sure your topic matches NTFY_TOPIC in config"
            ),
        )

    return FriendlyError(
        title="Notification error",
        message=f"Could not send alert: {error}",
        fix="Check your notification settings in the configuration file.",
    )


def format_friendly_error(err: FriendlyError) -> str:
    """Format a FriendlyError for display in terminal or chat."""
    lines = [
        f"⚠️  {err.title}",
        f"   {err.message}",
        "",
        "💡 How to fix:",
    ]
    for line in err.fix.split("\n"):
        lines.append(f"   {line}")
    if err.docs_url:
        lines.append("")
        lines.append(f"   📖 More info: {err.docs_url}")
    return "\n".join(lines)
