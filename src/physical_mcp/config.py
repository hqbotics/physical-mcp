"""Configuration loading and validation."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    id: str = "usb:0"
    name: str = ""  # Optional label for this camera
    type: str = "usb"  # "usb" | "rtsp" | "http" | "cloud"
    device_index: int = 0
    width: int = 1280
    height: int = 720
    url: str | None = None
    auth_token: str = ""  # Per-camera auth token (used by cloud cameras)
    enabled: bool = True


class ChangeDetectionConfig(BaseModel):
    minor_threshold: int = 5
    moderate_threshold: int = 12
    major_threshold: int = 25


class SamplingConfig(BaseModel):
    heartbeat_interval: float = (
        0.0  # 0 = disabled (only analyze on change). Set >0 for periodic checks.
    )
    debounce_seconds: float = 1.5  # MODERATE change debounce before LLM call
    cooldown_seconds: float = 5.0  # Min 5s between LLM calls


class PerceptionConfig(BaseModel):
    buffer_size: int = 300
    capture_fps: int = 2
    change_detection: ChangeDetectionConfig = Field(
        default_factory=ChangeDetectionConfig
    )
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)


class ReasoningConfig(BaseModel):
    provider: str = ""  # "anthropic" | "openai" | "google" | "openai-compatible" | ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""  # For openai-compatible providers
    image_quality: int = 80
    max_thumbnail_dim: int = 1024
    llm_timeout_seconds: float = 15.0  # Max time for a single LLM API call


class CostControlConfig(BaseModel):
    daily_budget_usd: float = 0.0  # 0 = unlimited
    max_analyses_per_hour: int = 600  # Enough for 15s heartbeat + 10s cooldown


class ServerConfig(BaseModel):
    transport: str = "streamable-http"
    host: str = "0.0.0.0"
    port: int = 8400


class NotificationsConfig(BaseModel):
    default_type: str = "local"
    webhook_url: str = ""
    desktop_enabled: bool = True
    ntfy_topic: str = ""
    ntfy_server_url: str = "https://ntfy.sh"
    # OpenClaw multi-channel delivery (Telegram, WhatsApp, Discord, Slack, etc.)
    openclaw_channel: str = ""  # "telegram"|"whatsapp"|"discord"|"slack"|"signal"
    openclaw_target: str = ""  # chat_id, phone number, channel_id
    # Direct API notifiers (work on Fly.io without OpenClaw CLI)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""


class VisionAPIConfig(BaseModel):
    enabled: bool = True  # ON by default — the whole point
    host: str = "0.0.0.0"  # Listen on all interfaces (LAN + mobile access)
    port: int = 8090
    auth_token: str = ""  # Bearer token for API access (empty = no auth)


class PhysicalMCPConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    cameras: list[CameraConfig] = Field(default_factory=lambda: [CameraConfig()])
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    cost_control: CostControlConfig = Field(default_factory=CostControlConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    vision_api: VisionAPIConfig = Field(default_factory=VisionAPIConfig)
    rules_file: str = "~/.physical-mcp/rules.yaml"
    memory_file: str = "~/.physical-mcp/memory.md"


def _interpolate_env_vars(text: str) -> str:
    """Replace ${VAR_NAME} with environment variable values."""

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(r"\$\{(\w+)\}", replacer, text)


def _config_from_env() -> PhysicalMCPConfig:
    """Build config from environment variables (for Docker/cloud deployment).

    Falls back to sane defaults when env vars are not set.
    """
    # Camera: CAMERA_URL overrides the default USB camera with an RTSP source
    # CLOUD_MODE=1 means cameras are registered via POST /push/register
    camera_url = os.environ.get("CAMERA_URL", "")
    if camera_url:
        cameras = [
            CameraConfig(
                id=os.environ.get("CAMERA_ID", "cam:0"),
                name=os.environ.get("CAMERA_NAME", "Camera 1"),
                type="rtsp" if camera_url.startswith("rtsp") else "http",
                url=camera_url,
            )
        ]
    else:
        cameras = []  # No camera pre-configured; add via POST /cameras at runtime

    # Cloud-mode defaults: tighter sampling for 1fps push cameras
    is_cloud = os.environ.get("CLOUD_MODE", "") == "1"
    default_heartbeat = "5" if is_cloud else "0"
    default_debounce = "0.5" if is_cloud else "1.5"
    default_cooldown = "3" if is_cloud else "5"
    default_minor = "3" if is_cloud else "5"
    default_moderate = "8" if is_cloud else "12"
    default_major = "20" if is_cloud else "25"

    default_buffer = "30" if is_cloud else "300"

    return PhysicalMCPConfig(
        cameras=cameras,
        perception=PerceptionConfig(
            buffer_size=int(os.environ.get("FRAME_BUFFER_SIZE", default_buffer)),
            capture_fps=int(os.environ.get("PERCEPTION_FPS", "2")),
            change_detection=ChangeDetectionConfig(
                minor_threshold=int(
                    os.environ.get("CHANGE_MINOR_THRESHOLD", default_minor)
                ),
                moderate_threshold=int(
                    os.environ.get("CHANGE_MODERATE_THRESHOLD", default_moderate)
                ),
                major_threshold=int(
                    os.environ.get("CHANGE_MAJOR_THRESHOLD", default_major)
                ),
            ),
            sampling=SamplingConfig(
                heartbeat_interval=float(
                    os.environ.get("SAMPLING_HEARTBEAT_INTERVAL", default_heartbeat)
                ),
                debounce_seconds=float(
                    os.environ.get("SAMPLING_DEBOUNCE_SECONDS", default_debounce)
                ),
                cooldown_seconds=float(
                    os.environ.get("SAMPLING_COOLDOWN_SECONDS", default_cooldown)
                ),
            ),
        ),
        cost_control=CostControlConfig(
            max_analyses_per_hour=int(os.environ.get("MAX_ANALYSES_PER_HOUR", "600")),
        ),
        reasoning=ReasoningConfig(
            provider=os.environ.get("REASONING_PROVIDER", ""),
            api_key=os.environ.get("REASONING_API_KEY", ""),
            model=os.environ.get("REASONING_MODEL", ""),
            base_url=os.environ.get("REASONING_BASE_URL", ""),
            image_quality=int(os.environ.get("REASONING_IMAGE_QUALITY", "80")),
            max_thumbnail_dim=int(
                os.environ.get("REASONING_MAX_THUMBNAIL_DIM", "1024")
            ),
        ),
        vision_api=VisionAPIConfig(
            host=os.environ.get("VISION_API_HOST", "0.0.0.0"),
            port=int(os.environ.get("VISION_API_PORT", "8090")),
            auth_token=os.environ.get("VISION_API_AUTH_TOKEN", ""),
        ),
        server=ServerConfig(
            transport=os.environ.get("PHYSICAL_MCP_TRANSPORT", "streamable-http"),
            host=os.environ.get("PHYSICAL_MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("PHYSICAL_MCP_PORT", "8400")),
        ),
        notifications=NotificationsConfig(
            default_type=os.environ.get("NOTIFICATION_TYPE", "local"),
            webhook_url=os.environ.get("NOTIFICATION_WEBHOOK_URL", ""),
            ntfy_topic=os.environ.get("NTFY_TOPIC", ""),
            openclaw_channel=os.environ.get("OPENCLAW_CHANNEL", ""),
            openclaw_target=os.environ.get("OPENCLAW_TARGET", ""),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", ""),
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
        ),
    )


def load_config(path: str | Path | None = None) -> PhysicalMCPConfig:
    """Load config from YAML file, env vars, or defaults.

    Priority: config.yaml (with ${ENV} interpolation) > env vars > defaults.
    """
    if path is None:
        path = Path("~/.physical-mcp/config.yaml").expanduser()
    else:
        path = Path(path).expanduser()

    if not path.exists():
        # No config file — check if running in headless/container mode
        if os.environ.get("PHYSICAL_MCP_HEADLESS") or os.environ.get(
            "REASONING_PROVIDER"
        ):
            return _config_from_env()
        return PhysicalMCPConfig()

    raw_text = path.read_text()
    interpolated = _interpolate_env_vars(raw_text)
    data = yaml.safe_load(interpolated)
    if data is None:
        return PhysicalMCPConfig()
    return PhysicalMCPConfig(**data)


def save_config(config: PhysicalMCPConfig, path: str | Path | None = None) -> Path:
    """Save config to YAML file."""
    if path is None:
        path = Path("~/.physical-mcp/config.yaml").expanduser()
    else:
        path = Path(path).expanduser()

    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump()
    # Don't persist interpolated API keys — keep the env var reference
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return path
