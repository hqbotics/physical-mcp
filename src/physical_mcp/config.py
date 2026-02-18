"""Configuration loading and validation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    id: str = "usb:0"
    name: str = ""  # Optional label for this camera
    type: str = "usb"
    device_index: int = 0
    width: int = 1280
    height: int = 720
    url: Optional[str] = None
    enabled: bool = True


class ChangeDetectionConfig(BaseModel):
    minor_threshold: int = 5
    moderate_threshold: int = 12
    major_threshold: int = 25


class SamplingConfig(BaseModel):
    heartbeat_interval: float = 300.0  # 5 minutes — only runs if watch rules exist
    debounce_seconds: float = 3.0
    cooldown_seconds: float = 10.0  # Min 10s between LLM calls


class PerceptionConfig(BaseModel):
    buffer_size: int = 300
    capture_fps: int = 2
    change_detection: ChangeDetectionConfig = Field(default_factory=ChangeDetectionConfig)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)


class ReasoningConfig(BaseModel):
    provider: str = ""  # "anthropic" | "openai" | "google" | "openai-compatible" | ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""  # For openai-compatible providers
    image_quality: int = 60
    max_thumbnail_dim: int = 640


class CostControlConfig(BaseModel):
    daily_budget_usd: float = 0.0  # 0 = unlimited
    max_analyses_per_hour: int = 120


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


class VisionAPIConfig(BaseModel):
    enabled: bool = True  # ON by default — the whole point
    host: str = "0.0.0.0"  # Listen on all interfaces (LAN + mobile access)
    port: int = 8090


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


def load_config(path: str | Path | None = None) -> PhysicalMCPConfig:
    """Load config from YAML file. Returns defaults if file doesn't exist."""
    if path is None:
        path = Path("~/.physical-mcp/config.yaml").expanduser()
    else:
        path = Path(path).expanduser()

    if not path.exists():
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
