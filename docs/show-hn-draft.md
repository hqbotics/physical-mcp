# Show HN Draft

## Title (max 80 chars)

Show HN: Physical-MCP – Give your AI eyes with any camera (open source, MCP)

## Post body

Hi HN,

I built physical-mcp, an open-source MCP server that connects any camera (laptop, USB, IP/RTSP) to any AI system — Claude Desktop, ChatGPT, Cursor, VS Code, Gemini, and more.

Instead of getting dumb motion alerts from your cameras, you tell your AI what to watch for in plain English:

- "Watch my front door and text me when someone arrives"
- "Alert me if my kid leaves the room"
- "Monitor the stove and warn me if something is burning"

**How it works:**

1. `pip install physical-mcp && physical-mcp` — setup wizard detects your camera
2. Connect to any MCP-compatible AI app (or use via WhatsApp/Telegram/Discord/Slack through OpenClaw)
3. Tell your AI what to watch for — it creates watch rules and monitors 24/7
4. Get alerts on your phone via Telegram, WhatsApp, Discord, Slack, or Signal

**Architecture:**

Camera frames → local change detection (<5ms, no cloud) → only sends frames to vision AI when something changes → evaluates your watch rules → fires alerts with reasoning.

This keeps API costs under $5/month for 24/7 monitoring since most frames are filtered locally.

**Key features:**

- Works with any MCP client (Claude Desktop, ChatGPT, Cursor, VS Code, Gemini)
- Any camera: laptop webcam, USB, RTSP/HTTP IP cameras
- 14 pre-built rule templates (person detection, package delivery, pet monitoring, etc.)
- Web dashboard at `/dashboard` for quick status checks
- Cloud-deployable (Fly.io, Docker) with remote camera support
- 443 tests, MIT licensed

**What makes this different from security cameras:**

Ring/Wyze send you "motion detected" notifications. Physical-mcp gives your AI continuous visual understanding of the physical world. Your AI doesn't just detect motion — it understands scenes, tracks context over time, and can respond to complex conditions in natural language.

GitHub: https://github.com/hqbotics/physical-mcp
PyPI: `pip install physical-mcp`

Would love feedback on the architecture and use cases you'd find interesting.

---

## Reddit r/selfhosted Draft

**Title:** physical-mcp: Open-source MCP server that gives your AI eyes via any camera (laptop, USB, RTSP)

**Body:**

I've been building physical-mcp — an open-source server that connects cameras to AI systems via the MCP protocol.

**The idea:** Instead of motion alerts, tell your AI what to watch for in plain English. It monitors 24/7 and alerts you on Telegram/Discord/Slack when your conditions are met.

**Self-hosting details:**
- Pure Python, `pip install physical-mcp`
- Runs on any Linux box, Mac, RPi, or Docker
- Local change detection means <5ms frame filtering, minimal bandwidth
- Vision AI calls only when something changes (~$5/mo for 24/7)
- Web dashboard at `:8090/dashboard`
- Works with Claude Desktop, ChatGPT, Cursor, VS Code, Gemini via MCP

**Use cases I've tested:**
- Front door person detection → Telegram alert with photo
- Pet on furniture monitoring
- Baby room monitoring
- Workspace activity tracking

443 tests, MIT license, no cloud account required.

GitHub: https://github.com/hqbotics/physical-mcp

Happy to answer questions about the architecture or self-hosting setup.
