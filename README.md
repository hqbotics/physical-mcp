# physical-mcp

### Give your AI eyes.

[![PyPI](https://img.shields.io/pypi/v/physical-mcp)](https://pypi.org/project/physical-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/physical-mcp)](https://pypi.org/project/physical-mcp/)
[![Tests](https://img.shields.io/badge/tests-456%20passing-brightgreen)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/hqbotics/physical-mcp)](https://github.com/hqbotics/physical-mcp/releases)

[![Claude Desktop](https://img.shields.io/badge/Works%20With-Claude%20Desktop-blue)](#standalone-setup)
[![ChatGPT](https://img.shields.io/badge/Works%20With-ChatGPT-10a37f)](#standalone-setup)
[![Cursor](https://img.shields.io/badge/Works%20With-Cursor-6f42c1)](#standalone-setup)
[![VS%20Code](https://img.shields.io/badge/Works%20With-VS%20Code-007acc)](#standalone-setup)
[![Gemini](https://img.shields.io/badge/Works%20With-Gemini-8e75ff)](#standalone-setup)
[![OpenClaw](https://img.shields.io/badge/Works%20With-OpenClaw-orange)](#quick-start)

**physical-mcp** is an open-source [MCP](https://modelcontextprotocol.io) server that gives any AI real-time camera vision.
Get alerts on **WhatsApp, Telegram, Discord, Slack, Signal** — or talk to your AI about what it sees.

> "Watch my front door and tell me when someone arrives"
> -> Your AI sees through the camera and alerts you on WhatsApp / Telegram / Discord / Slack

---

## Quick Start

### 1. Install OpenClaw + physical-mcp

```bash
npm install -g openclaw
pip install physical-mcp
```

### 2. Connect your chat apps

```bash
openclaw configure
```

Connect WhatsApp, Telegram, Discord, Slack, or Signal — whichever you already use.

### 3. Start the camera

```bash
physical-mcp
```

The setup wizard detects your camera and starts the vision server.

### 4. Talk to your AI

Open any connected chat app and tell your AI what to watch for:

- "Watch my front door and alert me when someone arrives"
- "Tell me if my kid leaves the room"
- "Say 'hello!' when I wave at the camera"
- "Monitor the stove and warn me if something is burning"

Your AI sees through the camera, understands the scene, and sends you alerts through the chat apps you already use. No new app to install.

---

## How It Works

```
You (WhatsApp/Telegram/Discord/Slack)
  |
  v
OpenClaw (routes messages to your AI)
  |
  v
physical-mcp (camera vision + watch rules)
  |
  v
Your camera (laptop, USB, IP/RTSP)
```

1. **You chat** with your AI in WhatsApp, Telegram, Discord, or Slack
2. **OpenClaw** routes your messages to the AI and connects physical-mcp as a skill
3. **physical-mcp** captures camera frames, analyzes scenes with vision AI, and evaluates watch rules
4. **Alerts fire** back to your chat app when conditions are met

---

## Features

- **Any camera** — laptop webcam, USB, RTSP/HTTP IP cameras
- **Any AI** — Claude Desktop, ChatGPT, Cursor, VS Code, Gemini (via MCP protocol)
- **Any messenger** — WhatsApp, Telegram, Discord, Slack, Signal (via OpenClaw)
- **Custom alerts** — "say 'NO WAY YOU DID IT!' when I do an X shape"
- **24/7 vision** — local change detection (<5ms), only calls AI when something changes (~$5/mo)
- **14 rule templates** — person detection, package delivery, pet monitoring, baby monitor, and more
- **Web dashboard** — live camera feed, scene analysis, alerts at `localhost:8090/dashboard`
- **Cloud-ready** — deploy to Fly.io or Docker with remote camera support
- **456 tests** — thoroughly tested, MIT licensed

---

## Standalone Setup

physical-mcp also works directly with MCP-compatible AI apps — no OpenClaw needed:

- [Claude Desktop quickstart](docs/quickstart-claude-desktop.md)
- [ChatGPT quickstart](docs/quickstart-chatgpt.md)
- [Cursor quickstart](docs/quickstart-cursor.md)
- [VS Code quickstart](docs/quickstart-vscode.md)
- [Gemini quickstart](docs/quickstart-gemini.md)
- [OpenClaw quickstart](docs/quickstart-openclaw.md)
- [Windsurf quickstart](docs/quickstart-windsurf.md)
- [Trae quickstart](docs/quickstart-trae.md)
- [CodeBuddy quickstart](docs/quickstart-codebuddy.md)
- [Generic MCP client quickstart](docs/quickstart-generic-mcp-client.md)

### Platform quickstarts

- [Windows PowerShell quickstart](docs/quickstart-windows-powershell-v1.md)
- [Linux systemd quickstart](docs/quickstart-linux-systemd-v1.md)
- [macOS launchd quickstart](docs/quickstart-macos-launchd-v1.md)
- [GitHub Codespaces quickstart](docs/quickstart-github-codespaces-v1.md)
- [Docker quickstart](docs/quickstart-docker-v1.md)
- [Headless Raspberry Pi quickstart](docs/quickstart-headless-raspberry-pi-v1.md)

### Troubleshooting

- [60-second quickstart checklist](docs/quickstart-60-second-checklist-v1.md)
- [First 10 minutes playbook](docs/first-10-minutes-playbook-v1.md)
- [Windsurf/Trae troubleshooting](docs/quickstart-windsurf-trae-troubleshooting-v1.md)
- [Common install failures](docs/common-install-failures-v1.md)
- [Recommended cameras (USB + RTSP)](docs/recommended-cameras.md)

### Standalone quick install

```bash
pip install physical-mcp
physical-mcp
```

For ChatGPT HTTPS access:

```bash
pip install 'physical-mcp[tunnel]'
physical-mcp tunnel
```

---

## CLI commands

```bash
physical-mcp               # setup wizard + run server
physical-mcp status        # check service status
physical-mcp tunnel        # expose over HTTPS (for ChatGPT)
physical-mcp doctor        # run diagnostics
physical-mcp discover      # scan LAN for IP cameras
physical-mcp cameras       # list available cameras
physical-mcp rules         # list active watch rules
physical-mcp --version     # show version
```

Once running, open `http://localhost:8090/dashboard` for a live web dashboard.

---

## Guides

- **[Setup Guide](docs/setup-guide.md)** — Full walkthrough: install, configure, first alert (10 min)
- [Module Reference](docs/module-reference.md) — Complete API reference for all components
- [Architecture](docs/architecture.md) — How the system works under the hood
- [Vision agent architecture](docs/openclaw-vision-agent-architecture.md)
- [Platform quickstarts](docs/) — Claude Desktop, ChatGPT, Cursor, VS Code, Gemini, Docker

---

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md).
Use issue templates for bug reports and feature requests.

---

## License

MIT
