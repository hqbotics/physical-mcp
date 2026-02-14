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

### Claude Desktop

The setup wizard auto-configures Claude Desktop for you:

```
$ physical-mcp

Welcome to Physical MCP! Let's set up your camera.

Physical MCP Setup
========================================

Detecting cameras...
Found 1 camera(s):
  Index 0: 1280x720

Which AI app will you use?
  1. Claude Desktop (Mac/Windows/Linux app)
  2. ChatGPT, Gemini, or other (phone or web)
Choice [1]: 1

Auto-configure Claude Desktop? [Y/n]: Y
  Done! Restart Claude Desktop to connect.
```

Restart Claude Desktop and start chatting about what your camera sees.

### Phone & Web Apps (ChatGPT, Gemini, etc.)

Choose option 2 during setup. The wizard shows a QR code you can scan with your phone:

```
$ physical-mcp

Which AI app will you use?
Choice [1]: 2

Connect from this computer:  http://127.0.0.1:8400/mcp
Connect from your phone:     http://192.168.1.42:8400/mcp

█████████████████
█ QR CODE HERE  █
█████████████████
Scan this QR code with your phone to connect.
```

Point your AI app's MCP settings at the URL and you're connected.

### Run in Background

Don't want to keep a terminal open? Install as a background service:

```bash
physical-mcp install      # Start on login, runs automatically
physical-mcp uninstall    # Remove background service
physical-mcp status       # Check if running, show QR code
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

## Install with Provider Support

```bash
pip install physical-mcp              # Client-side only (no API key needed)
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
├── __main__.py            # CLI: setup, install, status, cameras
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
