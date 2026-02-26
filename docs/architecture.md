# physical-mcp Architecture

## System Overview

```
                          USERS
            Discord / WhatsApp / Telegram / Slack / Signal
                          |
                          v
                 +------------------+
                 |  OpenClaw        |    (internal plumbing - invisible to users)
                 |  Gateway         |
                 |  (Node.js)       |
                 +--------+---------+
                          |
                          v
                 +------------------+
                 |  AI Agent        |    GPT-5.3 Codex / Kimi K2.5
                 |  (main session)  |    reads SKILL.md for camera commands
                 +--------+---------+
                          |
              runs physical-mcp.sh commands
                          |
            +-------------+-------------+
            |                           |
            v                           v
   +-----------------+        +------------------+
   |  MCP Server     |        |  Vision Proxy    |    <-- the 24/7 brain
   |  (stdio)        |        |  (HTTP :8090)    |
   |                 |        |                  |
   |  Claude Desktop |        |  Perception Loop |
   |  tool calls     |        |  Change Detect   |
   +-----------------+        |  AI Analysis     |
                              |  Rule Evaluation |
                              |  Notifications   |
                              +--------+---------+
                                       |
                    +------------------+------------------+
                    |                  |                  |
                    v                  v                  v
              +-----------+    +-------------+    +--------------+
              |  Cameras  |    |  Rules      |    |  Notifier    |
              |           |    |  Engine     |    |              |
              | USB (0,1) |    | rules.yaml  |    | -> openclaw  |
              | Cloud     |    |             |    | -> desktop   |
              | HTTP/RTSP |    | Evaluate    |    | -> ntfy      |
              +-----------+    | conditions  |    | -> webhook   |
                               +-------------+    +--------------+
```

## Data Flow

```
  Camera Frame (JPEG)
       |
       v
  Frame Buffer (circular, 300 frames)
       |
       v
  Change Detector (perceptual hash - FREE, local, <5ms)
       |
       +-- minor change --> skip (save cost)
       +-- moderate change --> debounce 0.5s, then analyze
       +-- major change --> analyze immediately
       +-- heartbeat (120s) --> analyze anyway
       |
       v
  Vision LLM (Kimi K2.5 via OpenRouter - ~$0.003/call)
       |
       +-- Scene description (summary, objects, people count)
       +-- Rule evaluations (triggered? confidence? reasoning?)
       |
       v
  Rules Engine
       |
       +-- triggered=true, confidence >= 0.7
       |       |
       |       v
       |   Notification Dispatcher
       |       |
       |       +-- openclaw message send --channel discord --target #channel
       |       |       |
       |       |       v
       |       |   User sees: "Hey! I noticed someone waving!"
       |       |
       |       +-- desktop notification (macOS)
       |       +-- ntfy push (phone)
       |       +-- webhook (HTTP POST)
       |
       +-- triggered=false --> no action
```

## Key Files

```
~/.physical-mcp/
  config.yaml          Camera config, AI provider, notification settings
  rules.yaml           Watch rules (auto-reloaded every 5s)
  scene_cache.json     Latest scene state
  pending.yaml         Cloud cameras awaiting approval

~/Desktop/physical-mcp/
  vision_proxy.py      24/7 perception daemon (port 8090)
  src/physical_mcp/
    server.py          MCP server (Claude Desktop integration)
    vision_api.py      REST API + dashboard + cloud camera endpoints
    camera/            USB, RTSP, HTTP, Cloud camera drivers
    reasoning/         AI providers (Anthropic, OpenAI, Google, OpenAI-compat)
    perception/        Change detection, frame sampling, scene state
    rules/             Watch rules engine + models
    notifications/     Multi-channel alert dispatcher
    dashboard.py       Web dashboard (HTML/JS)

~/.openclaw/
  openclaw.json        Gateway config (channels, agents, models)
  workspace/
    skills/physical-mcp/
      SKILL.md         Skill docs (loaded by AI agent as system prompt)
      scripts/physical-mcp.sh   Bash wrapper for all commands
    SOUL.md            Agent personality
    AGENTS.md          Agent behavior rules
```

## Processes

| Process | Port | Started By | Purpose |
|---------|------|------------|---------|
| physical-mcp (MCP) | stdio | Claude Desktop | Tool calls from Claude |
| vision_proxy.py | 8090 | MCP server (subprocess) | 24/7 perception + HTTP API |
| openclaw gateway | WebSocket | systemd/manual | Discord/Slack/WhatsApp bridge |

## Cost Model

| Activity | Cost | Frequency |
|----------|------|-----------|
| Frame capture | FREE | 5 FPS continuous |
| Change detection (hash) | FREE | Every frame |
| AI scene analysis | ~$0.003 | On change + heartbeat |
| Static room, no rules | $0/day | No API calls |
| Static room, with rules | ~$0.86/day | ~12/hr (heartbeat) |
| Active room, with rules | ~$1.50/day | ~20-40/hr |
| Daily budget cap | $1.00 | Hard limit in config |
