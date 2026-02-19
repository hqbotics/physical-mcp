# physical-mcp

### Give your AI eyes.

[![PyPI](https://img.shields.io/pypi/v/physical-mcp)](https://pypi.org/project/physical-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/physical-mcp)](https://pypi.org/project/physical-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Claude Desktop](https://img.shields.io/badge/Works%20With-Claude%20Desktop-blue)](#works-with)
[![ChatGPT](https://img.shields.io/badge/Works%20With-ChatGPT-10a37f)](#works-with)
[![Cursor](https://img.shields.io/badge/Works%20With-Cursor-6f42c1)](#works-with)
[![VS%20Code](https://img.shields.io/badge/Works%20With-VS%20Code-007acc)](#works-with)
[![Gemini](https://img.shields.io/badge/Works%20With-Gemini-8e75ff)](#works-with)
[![OpenClaw](https://img.shields.io/badge/Works%20With-OpenClaw-orange)](#works-with)

**physical-mcp is an open-source AI Vision Provider.**
It connects cameras to AI apps in about a minute.

```bash
pip install physical-mcp
physical-mcp
```

> Not a security camera product. Not a hardware launch.
> This is software that gives AI apps camera perception.

---

## Why physical-mcp

- One command setup (`physical-mcp`)
- Works with multiple AI apps, not one locked ecosystem
- Local change detection first (<5ms, low cost)
- Supports client-side and server-side reasoning workflows
- REST + MCP interfaces for integrations

---

## Works With

- Claude Desktop
- ChatGPT (via HTTPS tunnel / GPT Action path)
- Cursor
- VS Code
- Gemini
- OpenClaw
- Other MCP/HTTP-compatible clients

### Per-app quickstarts

- [Claude Desktop quickstart](docs/quickstart-claude-desktop.md)
- [ChatGPT quickstart](docs/quickstart-chatgpt.md)
- [Cursor quickstart](docs/quickstart-cursor.md)
- [VS Code quickstart](docs/quickstart-vscode.md)
- [OpenClaw quickstart](docs/quickstart-openclaw.md)
- [Gemini quickstart](docs/quickstart-gemini.md)
- [Windsurf quickstart](docs/quickstart-windsurf.md)
- [Trae quickstart](docs/quickstart-trae.md)
- [Generic MCP client quickstart](docs/quickstart-generic-mcp-client.md)
- [First 10 minutes playbook](docs/first-10-minutes-playbook-v1.md)

---

## 60-second setup

```bash
pip install physical-mcp
physical-mcp
```

The setup wizard detects your camera and writes config for supported apps.

For ChatGPT HTTPS access:

```bash
pip install 'physical-mcp[tunnel]'
physical-mcp tunnel
```

---

## First commands

```bash
physical-mcp               # setup + run
physical-mcp status        # service/status info
physical-mcp tunnel        # HTTPS endpoint for ChatGPT
physical-mcp doctor        # diagnostics
physical-mcp --version     # version
```

---

## Developer docs

- [Migration: client-side -> server-side](docs/migration-client-to-server-side.md)
- [Vision agent architecture](docs/openclaw-vision-agent-architecture.md)
- [Replay/cursor migration notes](docs/replay-cursor-migration.md)
- [v1 hardening changelog](docs/v1-hardening-changelog.md)

---

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md).
Use issue templates for bug reports and feature requests.

---

## License

MIT
