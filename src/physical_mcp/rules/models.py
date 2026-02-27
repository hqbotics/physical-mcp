"""Pydantic models for watch rules, evaluations, and alerts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RulePriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationTarget(BaseModel):
    type: str = "local"  # "local"|"desktop"|"ntfy"|"telegram"|"discord"|"slack"|"webhook"|"openclaw"
    url: str | None = None  # webhook URL
    channel: str | None = None  # ntfy topic OR openclaw channel type
    target: str | None = None  # openclaw destination (chat_id, phone, channel_id)


class WatchRule(BaseModel):
    id: str
    name: str
    condition: str  # Natural language
    camera_id: str = ""  # Empty = LLM picks the right camera
    priority: RulePriority = RulePriority.MEDIUM
    enabled: bool = True
    notification: NotificationTarget = Field(default_factory=NotificationTarget)
    cooldown_seconds: int = 60
    custom_message: str | None = None  # User-defined notification text
    owner_id: str = ""  # "slack:U12345", "discord:987654321" — empty = visible to all
    owner_name: str = ""  # "Mom", "Alice" — human-readable owner label
    created_at: datetime = Field(default_factory=datetime.now)
    last_triggered: datetime | None = None


class RuleEvaluation(BaseModel):
    rule_id: str
    triggered: bool
    confidence: float
    reasoning: str
    timestamp: datetime = Field(default_factory=datetime.now)


class AlertEvent(BaseModel):
    rule: WatchRule
    evaluation: RuleEvaluation
    scene_summary: str
    frame_base64: str | None = None


class PendingAlert(BaseModel):
    """A scene change event queued for client-side evaluation.

    When no server-side vision provider is configured, the perception loop
    queues these alerts for the MCP client to poll via check_camera_alerts().
    The client (Claude Desktop, ChatGPT, etc.) visually analyzes the frame
    and evaluates the watch rules using its own built-in intelligence.
    """

    id: str
    camera_id: str = ""
    camera_name: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    change_level: str  # "minor" | "moderate" | "major"
    change_description: str
    frame_base64: str  # Raw base64 JPEG (no data: prefix)
    scene_context: str  # SceneState.to_context_string() snapshot
    active_rules: list[dict]  # [{id, name, condition, priority}]
    expires_at: datetime
