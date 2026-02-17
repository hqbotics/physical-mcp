# Physical MCP

Give your AI eyes. Connect cameras to Claude, ChatGPT, Gemini, or any AI app through the [Model Context Protocol](https://modelcontextprotocol.io).

Physical MCP turns any USB camera into an ambient perception system for your AI. Set up natural language watch rules like "alert me when someone comes to the door" — the system monitors continuously using perceptual hashing for change detection, calling the AI only when something actually changes. Zero API costs in default mode.

**Kickstarter:** [Coming Soon]
**GitHub:** [github.com/idnaaa/physical-mcp](https://github.com/idnaaa/physical-mcp)

---

## Table of Contents

- [30-Second Setup](#30-second-setup)
- [What Can It Do?](#what-can-it-do)
- [How It Works](#how-it-works)
- [Setup Guide](#setup-guide)
- [Works with Every AI Chat App](#works-with-every-ai-chat-app)
- [HTTP Vision API](#http-vision-api)
- [Watch Rules & Monitoring](#watch-rules--monitoring)
- [Multi-Camera](#multi-camera)
- [Configuration Reference](#configuration-reference)
- [Architecture Deep Dive](#architecture-deep-dive)
- [MCP Tools Reference](#mcp-tools-reference)
- [Data Models](#data-models)
- [Vision Providers](#vision-providers)
- [Source Tree](#source-tree)
- [Development Guide](#development-guide)
- [Test Coverage](#test-coverage)
- [Troubleshooting](#troubleshooting)
- [v1.0 Hardening Notes](#v10-hardening-notes)

---

## 30-Second Setup

```bash
pip install physical-mcp
physical-mcp
```

That's it. On first run, the setup wizard auto-detects your camera and configures your AI app.

## What Can It Do?

- **"What's in my room right now?"** — Capture a live frame and describe it
- **"Watch my front door"** — Continuous monitoring with alerts on change
- **"Alert me when the baby wakes up"** — Natural language watch rules
- **"Is anyone in the office?"** — On-demand scene analysis
- **"Let me know when the package arrives"** — Persistent rules with memory across sessions

## How It Works

```
Camera -> Frame Buffer -> Change Detection (perceptual hash, <5ms, free)
                               |
                     Significant change?
                       |            |
                      No            Yes
                    (skip)     -> Evaluate watch rules
                                    |
                            Client-side: return frame to your AI
                            Server-side: call vision API (BYOK)
                                    |
                               Rule triggered?
                                    |
                            Alert -> Desktop / phone / webhook notification
                                  -> Memory log (persists across sessions)
```

**Two reasoning modes:**

1. **Server-side (recommended default)** — Bring your own API key. The server monitors in the background and pushes alerts/logs without blocking chat.
2. **Client-side (fallback, free)** — Your AI app analyzes camera frames directly. Useful when no API key is available, but requires polling in MCP clients.

---

## Setup Guide

Run one command. Physical MCP auto-detects your cameras AND every installed AI app, then configures each one automatically:

```
$ physical-mcp

Welcome to Physical MCP! Let's set up your camera.

Physical MCP Setup
========================================

Detecting cameras...
Found 1 camera(s):
  Index 0: 1280x720

Detecting AI apps...
  + Claude Desktop — auto-configured
  + Cursor — auto-configured
  + VS Code — auto-configured
  + Trae — auto-configured

Config saved to ~/.physical-mcp/config.yaml

Restart Claude Desktop, Cursor, VS Code and Trae to start using camera features!

For phone / LAN apps:
  http://192.168.1.42:8400/mcp
  [QR CODE]

For ChatGPT (requires HTTPS):
  Run: physical-mcp tunnel
  Then paste the HTTPS URL into ChatGPT -> Settings -> Connectors
```

**Supported apps (auto-configured):** Claude Desktop, Cursor, Windsurf, VS Code, Trae, CodeBuddy

**HTTP apps (paste URL or scan QR):** Gemini, Qwen, any MCP-compatible app

### ChatGPT

ChatGPT requires an HTTPS connection (can't connect to localhost directly).

```bash
# Option A: Built-in tunnel
pip install 'physical-mcp[tunnel]'
physical-mcp tunnel
# Paste the HTTPS URL into ChatGPT -> Settings -> Connectors -> Developer Mode -> Create

# Option B: ngrok CLI
ngrok http 8400
```

### Run in Background

Don't want to keep a terminal open? Install as a background service:

```bash
physical-mcp install      # Start on login, runs automatically
physical-mcp uninstall    # Remove background service
physical-mcp status       # Check if running, show QR code
physical-mcp tunnel       # HTTPS tunnel for ChatGPT
```

Works on macOS (launchd), Linux (systemd), and Windows (Task Scheduler).

---

## Works with Every AI Chat App

Physical MCP works with **every** AI chat app — not just MCP-enabled ones.

### Snap to Clipboard

Capture a camera frame to your clipboard, then paste into any chat app:

```bash
physical-mcp snap              # Camera -> clipboard. Cmd+V to paste.
physical-mcp snap --paste      # Camera -> clipboard -> auto-paste into focused app
physical-mcp snap --save /tmp/frame.png  # Also save to file
```

### Continuous Monitoring

Auto-snap when the scene changes or at regular intervals:

```bash
# Auto-paste into chat app when camera detects changes
physical-mcp watch --on-change --paste

# Auto-paste every 30 seconds for polling
physical-mcp watch --interval 30 --paste

# Global hotkey mode (Cmd+Shift+C / Ctrl+Shift+C)
pip install 'physical-mcp[hotkey]'
physical-mcp watch --paste
```

### Compatibility

| App | MCP | Snap/Paste | HTTP API |
|-----|-----|------------|----------|
| Claude Desktop | Full | Yes | Yes |
| Claude Web/Mobile | Remote MCP | Yes | Yes |
| ChatGPT | Paid only | Yes | Yes |
| Gemini | No | Yes | Yes |
| Copilot | No | Yes | Yes |
| Perplexity | No | Yes | Yes |
| Qwen / Grok | No | Yes | Yes |
| OpenClaw / custom | No | No | Yes |
| Cursor / VS Code | Full | Yes | Yes |

---

## HTTP Vision API

Any system can access camera data via simple HTTP endpoints. The Vision API starts automatically on port 8090 alongside the MCP server.

### Endpoints

| Endpoint | Description | Query Params |
|----------|-------------|-------------|
| `GET /` | API overview | - |
| `GET /frame` | Latest camera frame (JPEG) | `quality` (1-100, default 80) |
| `GET /frame/{camera_id}` | Specific camera frame | `quality` |
| `GET /stream` | **MJPEG video stream** | `fps` (default 5, max 30), `quality` (default 60) |
| `GET /stream/{camera_id}` | MJPEG stream from specific camera | `fps`, `quality` |
| `GET /events` | **SSE real-time event stream** | `camera_id` |
| `GET /scene` | All camera scene summaries (JSON) | - |
| `GET /scene/{camera_id}` | Specific camera scene (JSON) | - |
| `GET /changes` | Recent scene changes | `minutes`, `camera_id`, `wait`, `timeout`, `since` |

### Quick Examples

```bash
# Get a single frame
curl localhost:8090/frame -o latest.jpg

# Get scene summary
curl localhost:8090/scene | jq .

# Get recent changes
curl localhost:8090/changes?minutes=5

# Long-poll: block until next change
curl "localhost:8090/changes?wait=true&timeout=60"

# Only changes since last check (cursor-based pagination)
curl "localhost:8090/changes?since=2026-02-17T12:00:00"
```

### MJPEG Video Stream

Continuous video feed that works in any browser, `<img>` tag, VLC, ffmpeg, or OpenCV:

```html
<!-- Embed live camera in any web page -->
<img src="http://localhost:8090/stream" />

<!-- Specific camera at 10fps, 70% quality -->
<img src="http://localhost:8090/stream/usb:0?fps=10&quality=70" />
```

### Server-Sent Events (SSE)

Real-time push notifications of scene changes:

```javascript
const es = new EventSource('http://localhost:8090/events');

// Full scene updates (summary, objects, people count)
es.addEventListener('scene', (e) => {
  const scene = JSON.parse(e.data);
  console.log(scene.summary, scene.people_count);
});

// Individual change events (motion detected, etc.)
es.addEventListener('change', (e) => {
  const change = JSON.parse(e.data);
  console.log(change.camera_id, change.description);
});
```

**Events emitted:**
- `scene` — full scene update when LLM analysis runs
- `change` — scene change detected by perception loop
- `ping` — keepalive comment every 1s

### Long-Poll Changes

Block until something happens instead of polling:

```bash
# Blocks until a new change occurs, then returns immediately
curl "localhost:8090/changes?wait=true&timeout=60"

# Returns {"changes": {...}, "minutes": 5, "timeout": true} if nothing happened
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `wait` | bool | false | Enable long-poll mode |
| `timeout` | int | 30 | Max wait seconds (max 120) |
| `since` | ISO string | - | Only return changes after this timestamp |
| `minutes` | int | 5 | How far back to look |
| `camera_id` | string | - | Filter to specific camera |

---

## Watch Rules & Monitoring

The killer feature. Set up monitoring rules in natural language:

- "Watch my kids and alert me if they leave the room"
- "Let me know when the oven timer goes off"
- "Alert me if someone comes to the front door"
- "Monitor the driveway for deliveries"

Rules persist across sessions. Physical MCP remembers why each rule was created and what's happened before via its memory system (`~/.physical-mcp/memory.md`).

**Notifications:** Desktop alerts (macOS/Linux/Windows), phone push via [ntfy.sh](https://ntfy.sh), or webhooks.

### Notification Backends

| Backend | Config | Platforms | Description |
|---------|--------|-----------|-------------|
| `local` | Default | All | In-chat alerts via MCP |
| `desktop` | `notifications.desktop_enabled: true` | macOS, Linux, Windows | Native OS notifications |
| `ntfy` | `notifications.ntfy_topic: "my-topic"` | All (phone push) | Free push via ntfy.sh |
| `webhook` | `notifications.webhook_url: "https://..."` | All | HTTP POST to custom endpoint |

**Desktop notification backends:**
- macOS: terminal-notifier (brew) or osascript fallback
- Linux: notify-send
- Windows: PowerShell toast

**ntfy.sh features:**
- Free push notifications to any phone
- Supports image attachments (camera frames sent with alerts)
- Priority levels: low (2), medium (3), high (4), critical (5)
- Rate limiting: min 10s between notifications

---

## Multi-Camera

Physical MCP supports multiple cameras. Each camera gets its own perception loop with independent change detection. Your AI sees all cameras and picks the right one(s) for each task.

```yaml
# ~/.physical-mcp/config.yaml
cameras:
  - id: "usb:0"
    name: "Office"
    device_index: 0
  - id: "usb:1"
    name: "Front Door"
    device_index: 1
```

Ask your AI "list cameras" to see what each one currently shows.

---

## Configuration Reference

Config file: `~/.physical-mcp/config.yaml`

Run `physical-mcp setup` to generate interactively, or `physical-mcp setup --advanced` for full options.

### All Config Options

#### Server

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server.transport` | string | `"stdio"` | `"stdio"` (Claude Desktop) or `"streamable-http"` (phone/web) |
| `server.host` | string | `"127.0.0.1"` | Bind address for HTTP transport |
| `server.port` | int | `8400` | Port for HTTP transport |

#### Cameras

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cameras[].id` | string | `"usb:0"` | Unique camera identifier |
| `cameras[].name` | string | `""` | Human-readable label |
| `cameras[].type` | string | `"usb"` | Camera type |
| `cameras[].device_index` | int | `0` | USB device index |
| `cameras[].width` | int | `1280` | Capture width |
| `cameras[].height` | int | `720` | Capture height |
| `cameras[].url` | string | `null` | RTSP/HTTP URL (for IP cameras) |
| `cameras[].enabled` | bool | `true` | Enable/disable camera |

#### Perception

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `perception.buffer_size` | int | `300` | Frames kept in ring buffer per camera |
| `perception.capture_fps` | int | `2` | Frames captured per second |
| `perception.change_detection.minor_threshold` | int | `5` | Perceptual hash distance for minor change |
| `perception.change_detection.moderate_threshold` | int | `12` | Distance for moderate change |
| `perception.change_detection.major_threshold` | int | `25` | Distance for major change |
| `perception.sampling.heartbeat_interval` | float | `300.0` | Seconds between forced analysis (5 min) |
| `perception.sampling.debounce_seconds` | float | `3.0` | Wait time after moderate change before analysis |
| `perception.sampling.cooldown_seconds` | float | `10.0` | Min seconds between LLM calls |

#### Reasoning (Vision Provider)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `reasoning.provider` | string | `""` | `"anthropic"`, `"openai"`, `"google"`, `"openai-compatible"`, or `""` (client-side) |
| `reasoning.api_key` | string | `""` | API key (supports `${ENV_VAR}` syntax) |
| `reasoning.model` | string | `""` | Model name (uses provider default if empty) |
| `reasoning.base_url` | string | `""` | Custom API endpoint (for openai-compatible) |
| `reasoning.image_quality` | int | `60` | JPEG quality for frames sent to LLM |
| `reasoning.max_thumbnail_dim` | int | `640` | Max dimension for thumbnails sent to LLM |

#### Cost Control

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cost_control.daily_budget_usd` | float | `0.0` | Daily spending cap (0 = unlimited) |
| `cost_control.max_analyses_per_hour` | int | `120` | Rate limit for LLM calls |

#### Notifications

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `notifications.default_type` | string | `"local"` | Default notification backend |
| `notifications.webhook_url` | string | `""` | Webhook POST endpoint |
| `notifications.desktop_enabled` | bool | `true` | Enable native desktop notifications |
| `notifications.ntfy_topic` | string | `""` | ntfy.sh topic for phone push |
| `notifications.ntfy_server_url` | string | `"https://ntfy.sh"` | ntfy server URL |

#### Vision API (HTTP)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `vision_api.enabled` | bool | `true` | Enable HTTP Vision API |
| `vision_api.host` | string | `"0.0.0.0"` | Bind address (0.0.0.0 = all interfaces) |
| `vision_api.port` | int | `8090` | HTTP port |

#### Persistence

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `rules_file` | string | `"~/.physical-mcp/rules.yaml"` | Watch rules persistence file |
| `memory_file` | string | `"~/.physical-mcp/memory.md"` | Persistent memory file |

---

## Architecture Deep Dive

### Perception Loop (per camera)

Each camera runs its own independent perception loop at `capture_fps` (default 2 FPS):

```
1. USBCamera.grab_frame()
   |
2. FrameBuffer.push(frame)        ← Ring buffer, last 300 frames
   |                                  Notifies MJPEG stream clients via asyncio.Event
   |
3. ChangeDetector.detect(frame)   ← Perceptual hash + pixel diff, <5ms, FREE
   |                                  Returns ChangeResult(level, hash_distance, pixel_diff_pct)
   |
4. FrameSampler.should_analyze()  ← Smart gate: should we call the LLM?
   |  MAJOR change  → immediate
   |  MODERATE       → debounce 3s then analyze
   |  MINOR/NONE     → skip
   |  Heartbeat      → every 5 min if rules active
   |  No rules       → NEVER call LLM (zero cost)
   |
5a. Server-side mode (has provider):
   |  FrameAnalyzer.analyze_scene()  → LLM returns {summary, objects, people_count}
   |  SceneState.update()
   |  FrameAnalyzer.evaluate_rules() → LLM evaluates each rule
   |  RulesEngine.process_evaluations()
   |  NotificationDispatcher.dispatch() if triggered
   |
5b. Client-side mode (no provider):
   |  AlertQueue.push(PendingAlert)  → Frame + rules queued
   |  Client calls check_camera_alerts() → gets PendingAlert
   |  Client's AI analyzes the frame
   |  Client calls report_rule_evaluation() → results processed
   |
6. Loop back to step 1 (sleep 1/capture_fps seconds)
```

### Dual-Mode Reasoning

**Client-side (default):**
- No API key configured → `reasoning.provider` is empty
- The perception loop detects changes locally (free)
- When watch rules are active, PendingAlerts are queued
- The MCP client (Claude/Cursor) polls `check_camera_alerts()` and analyzes frames itself
- User calls `report_rule_evaluation()` with analysis results

**Server-side (BYOK):**
- API key configured → server calls external vision API
- FrameAnalyzer handles all LLM communication
- Fully autonomous: detects changes, analyzes, evaluates rules, sends notifications
- Supports Anthropic, OpenAI, Google Gemini, or any OpenAI-compatible endpoint

### State Management

All state is held in a shared `state: dict` passed to both MCP server and Vision API:

```python
state = {
    "frame_buffers": {camera_id: FrameBuffer},   # Ring buffers (last 300 frames each)
    "scene_states": {camera_id: SceneState},       # Rolling scene summaries
    "camera_configs": {camera_id: CameraConfig},   # Camera configuration
    "_loop_tasks": [asyncio.Task],                 # Perception loop tasks
}
```

The Vision API shares this exact dict — zero duplication, instant access to all camera data.

### Three Access Methods

```
USB Cameras -> Perception Loop (24/7, runs continuously)
                    |
              State Dict (frame buffers + scene states)
                    |
    +---------------+---------------+
    |               |               |
 MCP Tools      HTTP API         CLI Snap
 (15 tools)     (8 endpoints)   (clipboard)
    |               |               |
 Claude          Any system      Any chat app
 Cursor          OpenClaw        ChatGPT, Gemini
 VS Code         Browser ext     Copilot, Perplexity
 Windsurf        Mobile apps     Qwen, Grok
                 Home auto       — all platforms
```

---

## MCP Tools Reference

### Camera Tools

| Tool | Args | Returns | Description |
|------|------|---------|-------------|
| `capture_frame` | `camera_id=""`, `quality=85` | Image + metadata | Capture a live camera frame |
| `list_cameras` | — | Camera list + scenes | List available cameras with current scene summaries |
| `get_camera_status` | `camera_id=""` | Status dict | Resolution, buffer size, uptime |

### Scene Analysis Tools

| Tool | Args | Returns | Description |
|------|------|---------|-------------|
| `get_scene_state` | — | Scene dict | Cached scene summary + reasoning mode (no API call) |
| `get_recent_changes` | `minutes=5`, `camera_id=""` | Change list | Timeline of changes via perceptual hashing (free) |
| `analyze_now` | `question=""`, `camera_id=""` | Image + analysis | On-demand scene analysis |

### Client-Side Reasoning Tools

| Tool | Args | Returns | Description |
|------|------|---------|-------------|
| `check_camera_alerts` | — | Pending alerts | Poll for scene changes needing evaluation |
| `report_rule_evaluation` | `evaluations` (JSON) | Results | Submit visual analysis of watch rules |

`evaluations` format:
```json
[{"rule_id": "r_abc123", "triggered": true, "confidence": 0.85, "reasoning": "Person at door"}]
```

### Watch Rules Tools

| Tool | Args | Returns | Description |
|------|------|---------|-------------|
| `add_watch_rule` | `name`, `condition`, `camera_id=""`, `priority="medium"`, `notification_type="local"`, `notification_url=""`, `notification_channel=""`, `cooldown_seconds=60` | Rule info | Create monitoring rule |
| `list_watch_rules` | — | Rule list | List all rules and status |
| `remove_watch_rule` | `rule_id` | Removal status | Remove a watch rule |

### System Tools

| Tool | Args | Returns | Description |
|------|------|---------|-------------|
| `get_system_stats` | — | Stats dict | API calls, cost, alerts, uptime |
| `configure_provider` | `provider`, `api_key`, `model=""`, `base_url=""` | Config status | Change vision provider at runtime |
| `read_memory` | — | Markdown string | Read persistent memory from previous sessions |
| `save_memory` | `event=""`, `rule_id=""`, `rule_context=""`, `preference_key=""`, `preference_value=""` | Save status | Save events, rule context, or preferences |

---

## Data Models

### Frame (`camera/base.py`)

```
Fields:
  image: np.ndarray          # BGR numpy array from OpenCV
  timestamp: datetime        # Capture time
  source_id: str             # Camera ID (e.g., "usb:0")
  sequence_number: int       # Incrementing frame counter
  resolution: tuple[int,int] # (width, height)

Methods:
  to_jpeg_bytes(quality=85) -> bytes     # Encode as JPEG
  to_base64(quality=85) -> str           # Base64-encoded JPEG
  to_thumbnail(max_dim=640, quality=60) -> str  # Resized base64
```

### ChangeLevel / ChangeResult (`perception/change_detector.py`)

```
ChangeLevel(Enum):
  NONE     = "none"      # No change (hash distance < minor_threshold)
  MINOR    = "minor"     # Small change (distance 5-11)
  MODERATE = "moderate"  # Medium change (distance 12-24)
  MAJOR    = "major"     # Large change (distance 25+)

ChangeResult(dataclass):
  level: ChangeLevel        # Detected change level
  hash_distance: int        # Hamming distance between perceptual hashes (0-64)
  pixel_diff_pct: float     # Percentage of pixels that changed (>25 intensity)
  description: str          # "Hash distance: X, pixel diff: Y%"
```

### SceneState (`perception/scene_state.py`)

Rolling summary of what a camera currently sees:

```
Fields:
  summary: str                    # LLM-generated scene description
  objects_present: list[str]      # Detected objects
  people_count: int               # Number of people visible
  last_updated: datetime | None   # Last LLM analysis time
  last_change_description: str    # Most recent change
  update_count: int               # Total LLM updates
  _change_log: deque[ChangeLogEntry]  # Last 200 changes (timestamped)

Methods:
  update(summary, objects, people_count, change_desc)  # Full LLM update
  record_change(description)                           # Local change only
  get_change_log(minutes=5) -> list[dict]              # Recent changes
  to_context_string() -> str                           # For LLM prompt injection
  to_dict() -> dict                                    # JSON serializable
```

### WatchRule (`rules/models.py`)

```
Fields:
  id: str                        # Unique rule ID (e.g., "r_abc123")
  name: str                      # Human-readable name
  condition: str                 # Natural language condition
  camera_id: str                 # Target camera ("" = all)
  priority: RulePriority         # low | medium | high | critical
  enabled: bool                  # Active flag
  notification: NotificationTarget  # {type, url, channel}
  cooldown_seconds: int          # Min seconds between alerts (default 60)
  created_at: datetime
  last_triggered: datetime | None
```

### RuleEvaluation (`rules/models.py`)

```
Fields:
  rule_id: str        # Which rule was evaluated
  triggered: bool     # Did the condition match?
  confidence: float   # 0.0-1.0 (only triggers if >= 0.7)
  reasoning: str      # Why it triggered or didn't
  timestamp: datetime
```

### AlertEvent (`rules/models.py`)

```
Fields:
  rule: WatchRule            # The rule that triggered
  evaluation: RuleEvaluation # The evaluation result
  scene_summary: str         # Current scene description
  frame_base64: str | None   # Camera frame (for notifications)
```

### PendingAlert (`rules/models.py`)

Used in client-side mode. Queued by perception loop, polled by client:

```
Fields:
  id: str                    # Alert ID
  camera_id: str             # Source camera
  camera_name: str           # Human-readable camera name
  timestamp: datetime        # When change was detected
  change_level: str          # "minor" | "moderate" | "major"
  change_description: str    # What changed
  frame_base64: str          # JPEG frame for client to analyze
  scene_context: str         # Previous scene summary
  active_rules: list[dict]   # [{id, name, condition, priority}]
  expires_at: datetime       # TTL for queue expiration
```

---

## Vision Providers

### Supported Providers (`reasoning/providers/`)

| Provider | Config Key | Default Model | Base URL |
|----------|-----------|---------------|----------|
| Anthropic | `"anthropic"` | `claude-haiku-4-20250414` | Anthropic API |
| OpenAI | `"openai"` | `gpt-4o-mini` | OpenAI API |
| Google | `"google"` | `gemini-2.0-flash` | Google GenAI |
| OpenAI-compatible | `"openai-compatible"` | (must specify) | Custom `base_url` |

### OpenAI-Compatible Endpoints

Works with any provider that implements the OpenAI chat completions format with vision:

- **NVIDIA NIM**: `base_url: "https://integrate.api.nvidia.com/v1"` (Kimi K2.5, Llama 3.2 Vision, etc.)
- **Groq**: `base_url: "https://api.groq.com/openai/v1"`
- **DeepSeek**: `base_url: "https://api.deepseek.com/v1"`
- **Together AI**: `base_url: "https://api.together.xyz/v1"`
- **Ollama (local)**: `base_url: "http://localhost:11434/v1"`

### Provider Interface (`reasoning/providers/base.py`)

All providers implement `VisionProvider`:

```
Properties:
  provider_name: str
  model_name: str

Methods:
  analyze_image(image_b64: str, prompt: str) -> str
  analyze_image_json(image_b64: str, prompt: str) -> dict
```

### Cost Estimates (Server-Side Mode)

| Provider | Model | Est. Cost/Analysis | Notes |
|----------|-------|-------------------|-------|
| Anthropic | claude-haiku-4 | ~$0.003 | Fast, cheap |
| OpenAI | gpt-4o-mini | ~$0.002 | Cheapest vision |
| Google | gemini-2.0-flash | ~$0.001 | Very cheap |
| NVIDIA NIM | varies | Free tier | Some models free |

---

## Source Tree

```
src/physical_mcp/
|-- __init__.py                    # Version: 0.1.0
|-- __main__.py                    # CLI: main, setup, snap, watch, tunnel, install/uninstall/status
|-- server.py                      # MCP server: 15 tools, app_lifespan, perception loop
|-- config.py                      # Pydantic config: 10 config classes, load/save, env var support
|-- platform.py                    # Cross-platform: autostart (launchd/systemd/taskscheduler), paths
|-- vision_api.py                  # HTTP Vision API: 8 endpoints (aiohttp), CORS, MJPEG/SSE/long-poll
|-- snap.py                        # Sync camera capture: capture_frame_sync(), snap()
|-- clipboard.py                   # Cross-platform clipboard: macOS/Linux/Windows image copy + paste
|-- ai_apps.py                     # AI app registry: 8 apps, auto-detect, auto-configure
|-- memory.py                      # Persistent memory: markdown file, events/rules/preferences
|-- stats.py                       # Cost tracking: daily budget, hourly rate, per-analysis estimates
|-- alert_queue.py                 # Bounded async queue: TTL expiration, drain semantics
|
|-- camera/
|   |-- __init__.py
|   |-- base.py                    # Frame dataclass + CameraSource ABC
|   |-- usb.py                     # USB camera: OpenCV VideoCapture, background capture thread
|   |-- buffer.py                  # FrameBuffer: ring buffer (deque), wait_for_frame (asyncio.Event)
|   |-- factory.py                 # Camera factory: create from CameraConfig
|
|-- perception/
|   |-- __init__.py
|   |-- change_detector.py         # ChangeDetector: perceptual hash (imagehash.phash), <5ms
|   |-- frame_sampler.py           # FrameSampler: skip/debounce/immediate/heartbeat logic
|   |-- scene_state.py             # SceneState: rolling summary, change log (deque, maxlen=200)
|
|-- reasoning/
|   |-- __init__.py
|   |-- analyzer.py                # FrameAnalyzer: scene analysis + rule evaluation orchestration
|   |-- prompts.py                 # LLM prompt templates for scene analysis and rule evaluation
|   |-- providers/
|       |-- __init__.py
|       |-- base.py                # VisionProvider ABC
|       |-- anthropic.py           # Anthropic Claude provider
|       |-- openai_compat.py       # OpenAI + any OpenAI-compatible endpoint
|       |-- google.py              # Google Gemini provider
|
|-- rules/
|   |-- __init__.py
|   |-- models.py                  # WatchRule, RuleEvaluation, AlertEvent, PendingAlert, NotificationTarget
|   |-- engine.py                  # RulesEngine: add/remove rules, evaluate, cooldown tracking
|   |-- store.py                   # YAML persistence for rules
|
|-- notifications/
    |-- __init__.py
    |-- desktop.py                 # Native desktop: terminal-notifier/osascript/notify-send/PowerShell
    |-- ntfy.py                    # ntfy.sh push: text + image, priority mapping, rate limiting
    |-- webhook.py                 # HTTP webhook: JSON POST to custom endpoint
```

---

## Development Guide

### Adding a New Camera Type

1. Create `camera/your_camera.py` implementing `CameraSource` from `camera/base.py`:
   ```python
   class YourCamera(CameraSource):
       async def open(self): ...
       async def close(self): ...
       async def grab_frame(self) -> Frame: ...
       def is_open(self) -> bool: ...
       @property
       def source_id(self) -> str: ...
   ```
2. Add one `elif` in `camera/factory.py`
3. That's it — the server, perception, and rules layers work automatically

### Adding a Notification Channel

1. Create `notifications/your_channel.py` with a class that has `async def notify(self, alert: AlertEvent) -> bool`
2. Add dispatch logic in the NotificationDispatcher

### Adding a Vision Provider

1. Create `reasoning/providers/your_provider.py` implementing `VisionProvider`:
   ```python
   class YourProvider(VisionProvider):
       @property
       def provider_name(self) -> str: ...
       @property
       def model_name(self) -> str: ...
       async def analyze_image(self, image_b64: str, prompt: str) -> str: ...
       async def analyze_image_json(self, image_b64: str, prompt: str) -> dict: ...
   ```
2. Register in `reasoning/analyzer.py`'s provider creation logic

### Cross-Platform Clipboard (`clipboard.py`)

| Platform | Copy Method | Paste Simulation |
|----------|-------------|-----------------|
| macOS | osascript JXA (NSPasteboard) | AppleScript System Events `keystroke "v" using command down` |
| Linux | xclip / xsel | xdotool `key ctrl+v` |
| Windows | PowerShell `Clipboard.SetImage()` | PowerShell `SendKeys ^v` |

Zero Python package dependencies — all use OS-native tools.

### Running Tests

```bash
git clone https://github.com/idnaaa/physical-mcp
cd physical-mcp
pip install -e ".[dev,all]"
uv run pytest tests/ -v
```

---

## Test Coverage

**135 tests** across 14 test files. All pass.

| Test File | Tests | What It Covers |
|-----------|-------|---------------|
| `test_change_detector.py` | 5 | Perceptual hash change detection: initial frame, identical, different, small region, reset |
| `test_frame_sampler.py` | 5 | Smart sampling: no rules, initial frame, heartbeat, cooldown, minor skip |
| `test_rules_engine.py` | 8 | Rule add/remove, triggered alerts, cooldown, low confidence, disabled rules |
| `test_client_reasoning.py` | 8 | Client-side evaluations: triggered, not triggered, low confidence, unknown rule, malformed, cooldown, multi-rule |
| `test_memory.py` | 8 | Memory persistence: read empty, append event, recent events, rule context, preferences, trimming |
| `test_alert_queue.py` | 6 | Alert queue: push/pop, empty, bounded size, TTL expiration, has_pending, clear |
| `test_camera_factory.py` | 3 | Camera factory: USB creation, unknown type, default config |
| `test_ai_apps.py` | 17 | AI app registry: all 8 apps, config paths, detection, auto-configure, idempotent, Trae format |
| `test_snap.py` | 12 | Snap + clipboard: capture sync, snap flow, paste, save, platform dispatch, macOS specifics, VisionAPIConfig |
| `test_vision_api.py` | 25 | HTTP Vision API: all 8 endpoints, CORS, MJPEG stream, SSE events, long-poll, since filter |
| `test_desktop.py` | 7 | Desktop notifications: rate limiting, macOS backends, Linux, unsupported platform, error handling |
| `test_ntfy.py` | 9 | ntfy.sh: no topic, text post, image put, title, body, priority mapping, errors, scene changes |
| `test_webhook.py` | 3 | Webhook: no URL, payload format, error handling |

**Test infrastructure:**
- `pytest` + `pytest-asyncio` (strict mode)
- Async fixtures use `@pytest_asyncio.fixture`
- aiohttp test client/server for HTTP endpoint tests
- Extensive mocking (cv2, subprocess, aiohttp sessions)

---

## CLI Commands Reference

| Command | Description | Key Flags |
|---------|-------------|-----------|
| `physical-mcp` | Start MCP server | `--config`, `--transport`, `--port` |
| `physical-mcp setup` | Interactive setup wizard | `--config`, `--advanced` |
| `physical-mcp snap` | Capture frame to clipboard | `--camera`, `--paste/-p`, `--save` |
| `physical-mcp watch` | Continuous monitoring | `--on-change`, `--interval N`, `--paste/-p`, `--camera` |
| `physical-mcp tunnel` | HTTPS tunnel for ChatGPT | — |
| `physical-mcp install` | Install as background service | — |
| `physical-mcp uninstall` | Remove background service | — |
| `physical-mcp status` | Check service status, show QR | — |

---

## Install with Provider Support

```bash
pip install physical-mcp              # Client-side only (no API key needed)
pip install physical-mcp[hotkey]      # + Global hotkey for snap/watch
pip install physical-mcp[tunnel]      # + HTTPS tunnel for ChatGPT
pip install physical-mcp[anthropic]   # + Anthropic Claude
pip install physical-mcp[openai]      # + OpenAI / OpenAI-compatible
pip install physical-mcp[google]      # + Google Gemini
pip install physical-mcp[all]         # All providers
```

---

## v1.0 Hardening Notes

Recent reliability and operability upgrades shipped in this sprint:

- [v1 hardening changelog](docs/v1-hardening-changelog.md)
- [migration guide: client-side polling → server-side monitoring](docs/migration-client-to-server-side.md)
- [ChatGPT GPT Action wrapper docs](gpt-action/README.md)

## Troubleshooting

**Camera not detected**
- Check that no other app is using the camera
- Try `physical-mcp setup` to re-detect
- On Linux, ensure your user is in the `video` group: `sudo usermod -aG video $USER`
- On macOS, grant camera permission to your terminal app in System Settings > Privacy & Security > Camera

**Claude Desktop not connecting**
- Run `physical-mcp setup` to auto-configure
- Restart Claude Desktop after setup
- Check config: `cat ~/Library/Application\ Support/Claude/claude_desktop_config.json`

**Phone can't connect (HTTP mode)**
- Make sure phone and computer are on the same Wi-Fi network
- Run `physical-mcp status` to see the connection URL and QR code
- Check firewall isn't blocking port 8400

**High API costs (server-side mode)**
- Switch to client-side mode (no API key) — it's free
- Lower `perception.capture_fps` in config
- Set `cost_control.daily_budget_usd` to cap spending

**MJPEG stream not loading**
- Ensure server is running: `curl localhost:8090/`
- Check Vision API is enabled in config (`vision_api.enabled: true`)
- Try lower FPS: `localhost:8090/stream?fps=2`

---

## Git History

```
85e5cab Add MJPEG streaming, SSE events, and long-poll to Vision API
59c3a2b Universal vision: HTTP API, snap-to-clipboard, and watch modes
be4cfbd Add Trae + CodeBuddy support, ChatGPT HTTPS tunnel command
4fd0813 Auto-detect and configure ALL installed AI apps on setup
7b10ad9 Initial release: ambient perception MCP server with cross-platform setup
```

---

## License

MIT
