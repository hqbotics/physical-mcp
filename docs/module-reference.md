# Module Reference

Complete API reference for physical-mcp v1.1.0.

---

## Architecture Overview

```
Camera → FrameBuffer → ChangeDetector → FrameSampler → FrameAnalyzer → RulesEngine → NotificationDispatcher
  │                                                          │                │                    │
  USB/RTSP/HTTP           Free, local (<5ms)           LLM API call     Evaluate rules      Telegram/Discord/
                                                                        Generate alerts      Slack/ntfy/webhook
```

**Dual mode:**
- **Server-side** (with AI provider): Perception loop calls LLM directly
- **Client-side** (no provider): Queue alerts for MCP client to evaluate

---

## Camera Layer

### `camera.base.Frame`

Single captured frame with metadata.

| Field | Type | Description |
|-------|------|-------------|
| `image` | `np.ndarray` | BGR image from OpenCV |
| `timestamp` | `datetime` | Capture time |
| `source_id` | `str` | Camera identifier (e.g., "usb:0") |
| `sequence_number` | `int` | Monotonic counter |
| `resolution` | `tuple[int, int]` | (width, height) |

**Methods:**
- `to_jpeg_bytes(quality=85) -> bytes` — JPEG encoding
- `to_base64(quality=85) -> str` — Base64 JPEG string
- `to_thumbnail(max_dim=640, quality=60) -> str` — Downsized base64

### `camera.usb.USBCamera`

USB/built-in camera via OpenCV with background capture thread.

```python
camera = USBCamera(device_index=0, width=1280, height=720)
await camera.open()
frame = await camera.grab_frame()  # -> Frame (non-blocking)
await camera.close()
```

### `camera.rtsp.RTSPCamera`

RTSP/HTTP stream with auto-reconnect and exponential backoff.

```python
camera = RTSPCamera(url="rtsp://admin:pass@192.168.1.100:554/stream")
await camera.open()  # Waits up to 20s for first frame
frame = await camera.grab_frame()  # -> Frame
await camera.close()
```

### `camera.factory.create_camera`

```python
from physical_mcp.camera.factory import create_camera
camera = create_camera(config)  # -> USBCamera | RTSPCamera
```

### `camera.buffer.FrameBuffer`

Fixed-size ring buffer for frame history.

```python
buf = FrameBuffer(max_frames=300)
await buf.push(frame)
latest = await buf.latest()  # -> Optional[Frame]
frames = await buf.get_frames_since(since=datetime)  # -> list[Frame]
sampled = await buf.get_sampled(count=5)  # -> list[Frame] (evenly spaced)
```

---

## Perception Layer

### `perception.change_detector.ChangeDetector`

Free local change detection using perceptual hashing (<5ms per frame).

```python
detector = ChangeDetector(minor_threshold=5, moderate_threshold=12, major_threshold=25)
result = detector.detect(frame_bgr)  # -> ChangeResult
# result.level: ChangeLevel (NONE|MINOR|MODERATE|MAJOR)
# result.hash_distance: int
# result.description: str
```

### `perception.frame_sampler.FrameSampler`

Decides WHEN to call the LLM (cost control).

```python
sampler = FrameSampler(change_detector, debounce_seconds=3.0, cooldown_seconds=10.0)
should_send, change = sampler.should_analyze(frame, has_active_rules=True)
# should_send: bool — True if LLM should be called
```

### `perception.scene_state.SceneState`

Rolling scene summary updated by LLM.

```python
state = SceneState()
state.update(summary="Person at door", objects=["person", "door"], people_count=1, change_desc="Person appeared")
context = state.to_context_string()  # -> str (for LLM prompt)
log = state.get_change_log(minutes=5)  # -> list[dict]
```

---

## Reasoning Layer

### `reasoning.analyzer.FrameAnalyzer`

Orchestrates LLM calls for scene analysis and rule evaluation.

```python
analyzer = FrameAnalyzer(provider=google_provider)

# Analyze scene
result = await analyzer.analyze_scene(frame, previous_state, config)
# Returns: {"summary": str, "objects": list[str], "people_count": int, "changes": str}

# Evaluate rules
evals = await analyzer.evaluate_rules(frame, rules, scene_state, config)
# Returns: list[RuleEvaluation]
```

### Vision Providers

All implement `VisionProvider` interface:

```python
# Google Gemini
provider = GoogleProvider(api_key="AIza...", model="gemini-2.0-flash")

# OpenAI / OpenRouter
provider = OpenAICompatProvider(api_key="sk-...", model="gpt-4o-mini")
provider = OpenAICompatProvider(api_key="sk-or-...", model="google/gemini-2.0-flash-001",
                                 base_url="https://openrouter.ai/api/v1")

# Anthropic
provider = AnthropicProvider(api_key="sk-ant-...", model="claude-haiku-4-20250414")
```

**Interface:**
- `async analyze_image(image_b64, prompt) -> str`
- `async analyze_image_json(image_b64, prompt) -> dict`
- `async analyze_images(images_b64, prompt) -> str` — multi-frame
- `provider_name: str` (property)
- `model_name: str` (property)

---

## Rules Layer

### `rules.models.WatchRule`

A monitoring rule with natural language condition.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | — | Unique ID (e.g., "r_a9505711") |
| `name` | `str` | — | Human name |
| `condition` | `str` | — | Natural language condition |
| `camera_id` | `str` | `""` | Target camera (empty = all) |
| `priority` | `RulePriority` | `MEDIUM` | LOW/MEDIUM/HIGH/CRITICAL |
| `enabled` | `bool` | `True` | Active flag |
| `notification` | `NotificationTarget` | local | Where to send alerts |
| `cooldown_seconds` | `int` | `60` | Min seconds between alerts |
| `custom_message` | `str?` | `None` | Override notification text |
| `owner_id` | `str` | `""` | Multi-user isolation |
| `last_triggered` | `datetime?` | `None` | Last trigger time |

### `rules.engine.RulesEngine`

Evaluates rules against LLM analysis results.

```python
engine = RulesEngine()
engine.add_rule(rule)
engine.load_rules(rules_from_store)

# Get rules ready for evaluation (not in cooldown)
active = engine.get_active_rules()  # -> list[WatchRule]

# Process LLM evaluations → generate alerts
alerts = engine.process_evaluations(evaluations, scene_state, frame_base64)
# Returns: list[AlertEvent] (only triggered rules with confidence >= 0.75)
```

### `rules.store.RulesStore`

YAML persistence for rules.

```python
store = RulesStore(path="~/.config/physical-mcp/rules.yaml")
rules = store.load()  # -> list[WatchRule]
store.save(engine.list_rules())
```

### `rules.templates`

Pre-built rule templates.

```python
from physical_mcp.rules.templates import list_templates, get_template

templates = list_templates("security")  # -> list[RuleTemplate]
t = get_template("person-at-door")  # -> RuleTemplate
# t.condition = "A person is standing at, approaching, or knocking on a door"
```

**Categories:** security, pets, family, automation, business

---

## Notifications Layer

### `notifications.NotificationDispatcher`

Routes alerts to the appropriate channel.

```python
dispatcher = NotificationDispatcher(config.notifications)
await dispatcher.dispatch(alert_event)  # Auto-routes based on rule's notification target
await dispatcher.close()
```

### Individual Notifiers

| Notifier | Channel | Sends Photo? |
|----------|---------|-------------|
| `TelegramNotifier` | Telegram Bot API | Yes (sendPhoto) |
| `DiscordWebhookNotifier` | Discord webhook | Yes (embed image) |
| `SlackWebhookNotifier` | Slack webhook | No (Block Kit text) |
| `NtfyNotifier` | ntfy.sh push | Yes (attachment) |
| `DesktopNotifier` | OS notification | No |
| `WebhookNotifier` | HTTP POST | Base64 in JSON |
| `OpenClawNotifier` | OpenClaw CLI | Varies by channel |

All notifiers follow the same pattern:
```python
notifier = TelegramNotifier(bot_token="...", default_chat_id="...")
success = await notifier.notify(alert_event, chat_id="...")
await notifier.close()
```

---

## Configuration

### `config.PhysicalMCPConfig`

Root configuration loaded from `~/.config/physical-mcp/config.yaml`.

```python
from physical_mcp.config import load_config, save_config
config = load_config()  # -> PhysicalMCPConfig
# config.cameras, config.reasoning, config.notifications, etc.
```

**Key sections:**
- `cameras: list[CameraConfig]` — USB/RTSP/HTTP cameras
- `reasoning: ReasoningConfig` — AI provider settings
- `notifications: NotificationsConfig` — Alert channels
- `perception: PerceptionConfig` — Frame sampling thresholds
- `cost_control: CostControlConfig` — Budget limits

---

## REST API (Vision API)

HTTP endpoints served on port 8090.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API overview |
| GET | `/frame` | Latest camera frame (JPEG) |
| GET | `/scene` | Scene summaries (JSON) |
| GET | `/changes` | Recent changes (long-poll: `?wait=true`) |
| GET | `/health` | Camera health |
| GET | `/cameras` | List cameras |
| POST | `/cameras` | Add camera dynamically |
| GET | `/rules` | List watch rules |
| POST | `/rules` | Create rule |
| DELETE | `/rules/{id}` | Delete rule |
| PUT | `/rules/{id}/toggle` | Toggle rule on/off |
| GET | `/templates` | List rule templates |
| POST | `/templates/{id}/create` | Create rule from template |
| GET | `/alerts` | Recent alert events |
| GET | `/discover` | Scan network for cameras |

**Auth:** Bearer token via `Authorization: Bearer <token>` header.

---

## MCP Tools

20+ tools available to MCP clients (Claude Desktop, Cursor, etc.):

| Tool | Description |
|------|-------------|
| `capture_frame` | Capture and view current camera frame |
| `analyze_now` | On-demand scene analysis |
| `add_watch_rule` | Create monitoring rule |
| `create_rule_from_template` | Create rule from pre-built template |
| `list_rule_templates` | List available templates |
| `list_watch_rules` | List all rules |
| `remove_watch_rule` | Delete a rule |
| `check_camera_alerts` | Poll for pending alerts (client-side mode) |
| `report_rule_evaluation` | Submit client-side evaluations |
| `list_cameras` | List connected cameras |
| `get_scene_state` | Get cached scene summary |
| `get_recent_changes` | Timeline of scene changes |
| `configure_provider` | Set AI provider at runtime |
| `get_system_stats` | Usage stats and cost |
| `get_camera_health` | Per-camera health data |
| `read_memory` | Read persistent memory |
| `save_memory` | Write to persistent memory |

---

## Error Handling

All errors inherit from `PhysicalMCPError`:

```
PhysicalMCPError
├── CameraError
│   ├── CameraConnectionError
│   └── CameraTimeoutError
├── ProviderError
│   ├── ProviderAuthError
│   └── ProviderRateLimitError
└── ConfigError
```

Consumer-friendly messages via `friendly_errors.py`:
```python
from physical_mcp.friendly_errors import friendly_camera_error, format_friendly_error
err = friendly_camera_error(exception)
print(format_friendly_error(err))
# ⚠️  Camera permission needed
#    macOS is blocking camera access for this app.
# 💡 How to fix:
#    Open System Settings > Privacy & Security > Camera...
```
