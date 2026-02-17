# Physical MCP

Give your AI eyes. Connect cameras to Claude, ChatGPT, Gemini, or any AI app through the [Model Context Protocol](https://modelcontextprotocol.io).

Physical MCP turns any USB camera into an ambient perception system for your AI. Set up natural language watch rules like "alert me when someone comes to the door" — the system monitors continuously using perceptual hashing for change detection, calling the AI only when something actually changes. Zero API costs in default mode.

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

1. **Client-side (default, free)** — Your AI app (Claude, ChatGPT) analyzes camera frames directly. No API key needed.
2. **Server-side (BYOK)** — Bring your own API key. The server calls Anthropic, OpenAI, Google, or any OpenAI-compatible provider.

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
  ✓ Claude Desktop — auto-configured
  ✓ Cursor — auto-configured
  ✓ VS Code — auto-configured
  ✓ Trae — auto-configured

Config saved to ~/.physical-mcp/config.yaml

Restart Claude Desktop, Cursor, VS Code and Trae to start using camera features!

For phone / LAN apps:
  http://192.168.1.42:8400/mcp
  [QR CODE]

For ChatGPT (requires HTTPS):
  Run: physical-mcp tunnel
  Then paste the HTTPS URL into ChatGPT → Settings → Connectors
```

**Supported apps (auto-configured):** Claude Desktop, Cursor, Windsurf, VS Code, Trae, CodeBuddy

**HTTP apps (paste URL or scan QR):** Gemini, Qwen, any MCP-compatible app

### ChatGPT

ChatGPT requires an HTTPS connection (can't connect to localhost directly).

```bash
# Option A: Built-in tunnel
pip install 'physical-mcp[tunnel]'
physical-mcp tunnel
# Paste the HTTPS URL into ChatGPT → Settings → Connectors → Developer Mode → Create

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

## Multi-Camera

Physical MCP supports multiple cameras. Each camera gets its own perception loop with independent change detection. Your AI sees all cameras and picks the right one(s) for each task.

```yaml
# ~/.physical-mcp/config.yaml
cameras:
  - id: "usb:0"
    device_index: 0
  - id: "usb:1"
    device_index: 1
```

Ask your AI "list cameras" to see what each one currently shows.

## Works with Every AI Chat App

Physical MCP works with **every** AI chat app — not just MCP-enabled ones.

### Snap to Clipboard

Capture a camera frame to your clipboard, then paste into any chat app:

```bash
physical-mcp snap              # Camera → clipboard. Cmd+V to paste.
physical-mcp snap --paste      # Camera → clipboard → auto-paste into focused app
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

### HTTP Vision API

Any system can access camera data via simple HTTP endpoints:

```bash
curl localhost:8090/frame -o latest.jpg     # Latest camera frame (JPEG)
curl localhost:8090/scene | jq .            # Scene summaries (JSON)
curl localhost:8090/changes?minutes=5       # Recent changes
```

The Vision API starts automatically on port 8090. Access from mobile devices on the same WiFi via your computer's LAN IP.

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

## Watch Rules & Monitoring

The killer feature. Set up monitoring rules in natural language:

- "Watch my kids and alert me if they leave the room"
- "Let me know when the oven timer goes off"
- "Alert me if someone comes to the front door"
- "Monitor the driveway for deliveries"

Rules persist across sessions. Physical MCP remembers why each rule was created and what's happened before via its memory system (`~/.physical-mcp/memory.md`).

**Notifications:** Desktop alerts (macOS/Linux/Windows), phone push via [ntfy.sh](https://ntfy.sh), or webhooks.

## Configuration

Config file: `~/.physical-mcp/config.yaml`

Run `physical-mcp setup` to generate interactively, or `physical-mcp setup --advanced` for full options (vision provider, notifications, etc.).

See [`config.example.yaml`](config.example.yaml) for all available settings.

Key settings:
| Setting | Description |
|---------|-------------|
| `server.transport` | `stdio` (Claude Desktop) or `streamable-http` (phone/web) |
| `cameras` | Camera sources (USB index, resolution, RTSP URL) |
| `reasoning.provider` | Vision API provider (empty = client-side, free) |
| `perception.capture_fps` | Frames captured per second (default: 2) |
| `cost_control.daily_budget_usd` | Daily spending cap for server-side mode |
| `notifications.desktop_enabled` | Native desktop notifications |
| `notifications.ntfy_topic` | Phone push notifications via ntfy.sh |
| `vision_api.enabled` | HTTP Vision API on/off (default: true) |
| `vision_api.port` | Vision API port (default: 8090) |

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

## Tools Reference

| Tool | Description |
|------|-------------|
| `capture_frame` | Capture a live camera frame |
| `list_cameras` | List available cameras with current scene summaries |
| `get_camera_status` | Active camera resolution, buffer size, uptime |
| `get_scene_state` | Get cached scene summary and reasoning mode |
| `get_recent_changes` | Timeline of recent scene changes |
| `analyze_now` | On-demand scene analysis with optional question |
| `check_camera_alerts` | Poll for scene changes needing evaluation |
| `report_rule_evaluation` | Report visual analysis of watch rules |
| `add_watch_rule` | Create a continuous monitoring rule |
| `list_watch_rules` | List all watch rules and status |
| `remove_watch_rule` | Remove a watch rule |
| `get_system_stats` | System statistics, API calls, cost tracking |
| `configure_provider` | Change vision provider at runtime |
| `read_memory` | Read persistent memory from previous sessions |
| `save_memory` | Save events, rule context, or preferences |

## For Developers

### Architecture

```
physical_mcp/
├── server.py              # MCP server — 15 tools, multi-camera state
├── config.py              # Pydantic config models
├── platform.py            # Cross-platform: autostart, paths, Claude config
├── __main__.py            # CLI: setup, install, status, snap, watch
├── vision_api.py          # HTTP Vision API (/frame, /scene, /changes)
├── snap.py                # Sync camera capture for CLI snap command
├── clipboard.py           # Cross-platform clipboard image copy + paste
├── camera/
│   ├── base.py            # CameraSource ABC + Frame dataclass
│   ├── usb.py             # USB camera (OpenCV)
│   ├── buffer.py          # Ring buffer for frames
│   └── factory.py         # Camera creation from config
├── perception/
│   ├── change_detector.py # Perceptual hashing (<5ms change detection)
│   ├── frame_sampler.py   # Smart sampling (skip/debounce/immediate)
│   └── scene_state.py     # Rolling scene summary
├── reasoning/
│   ├── analyzer.py        # Scene analysis orchestration
│   ├── prompts.py         # LLM prompt templates
│   └── providers/         # Anthropic, OpenAI, Google, OpenAI-compatible
├── rules/
│   ├── models.py          # WatchRule, PendingAlert models
│   ├── engine.py          # Rule evaluation engine
│   └── store.py           # YAML persistence
├── notifications/
│   ├── desktop.py         # Native desktop notifications (Mac/Linux/Windows)
│   ├── ntfy.py            # Phone push via ntfy.sh
│   └── webhook.py         # HTTP webhook
├── alert_queue.py         # Async alert queue
├── memory.py              # Persistent memory (markdown)
└── stats.py               # Cost tracking and rate limiting
```

### Adding a New Camera Type

1. Create `camera/your_camera.py` implementing `CameraSource` from `camera/base.py`
2. Add one `elif` in `camera/factory.py`
3. That's it — the server, perception, and rules layers work automatically

### Adding a Notification Channel

1. Create `notifications/your_channel.py`
2. Add dispatch logic in `server.py`'s notification section

### Running Tests

```bash
git clone https://github.com/idnaaa/physical-mcp
cd physical-mcp
pip install -e ".[dev,all]"
pytest tests/ -v
```

## Troubleshooting

**Camera not detected**
- Check that no other app is using the camera
- Try `physical-mcp cameras` to see what's available
- On Linux, ensure your user is in the `video` group: `sudo usermod -aG video $USER`

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

## License

MIT
