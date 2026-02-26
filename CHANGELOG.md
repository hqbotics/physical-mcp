# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-02-27

### Added
- Self-contained web dashboard at `/dashboard` — DJI-style dark theme with live camera feed, scene analysis, watch rules, alerts, and template quick-add
- Mobile-responsive dashboard with auto-refresh (5s interval)
- Token-based dashboard access via query parameter
- Show HN and Reddit r/selfhosted launch post drafts
- 19 new tests: dashboard (6), template REST endpoints (8), camera endpoints (5)

### Changed
- Updated API docstring to document all current endpoints (18 total)
- Total test count: 455 (up from 436)

## [1.1.0] - 2026-02-26

### Added
- Cloud-ready deployment: Fly.io, Docker, headless mode with env var configuration
- RTSP/HTTP IP camera support for cloud relay architecture
- Dynamic camera registration via REST API (POST /cameras)
- Direct messaging notifiers: Telegram (with photo), Discord (embeds), Slack (Block Kit)
- LAN camera auto-discovery via async TCP port scan
- 14 pre-built rule templates across 5 categories (security, pets, family, automation, business)
- MCP tools: `list_rule_templates()`, `create_rule_from_template()`
- REST API: GET /templates, POST /templates/{id}/create
- Consumer-friendly error messages with actionable fix suggestions
- Fly.io auto-deploy CI workflow (on push to main)
- Full headless perception pipeline: camera → frame analysis → rule evaluation → notification dispatch

### Fixed
- Telegram notification emoji encoding (surrogate pairs → proper Unicode)
- Perception loop not starting from REST API (POST /rules, POST /cameras)
- Headless mode missing full pipeline (notifier, stats, memory, rules store)
- Critical bug: alerts silently dropped after trigger (cooldown filter excluded just-triggered rules)
- Stale alerts firing after watch rule deletion
- Heartbeat cost optimization (from ~$155/mo to ~$5-15/mo)

### Changed
- Architecture: MCP server (port 8400) + Vision REST API (port 8090) dual-port mode
- Auto-select best notification channel (Telegram > Discord > Slack > ntfy)
- Rule evaluation uses `list_rules()` instead of `get_active_rules()` to prevent alert loss

## [1.0.0] - 2026-02-21

### Added
- RTSP camera backend with auto-reconnect, TCP transport, credential masking
- HTTP MJPEG camera backend for ESP32-CAM, OctoPrint, and cheap IP cameras
- LAN camera auto-discovery (async TCP port scan for RTSP/HTTP on /24 subnet)
- Setup wizard: LAN camera scan + manual RTSP entry flow
- Cloudflare tunnel support (`physical-mcp tunnel`) with auto-detect fallback to ngrok
- mDNS/Bonjour advertisement for zero-config LAN discovery
- Structured logging with console + rotating file handler (~/.physical-mcp/logs/)
- SIGTERM/SIGINT signal handlers for graceful shutdown (flush state, close cameras)
- LLM call timeouts (30s max per analysis, prevents perception loop hangs)
- `physical-mcp doctor` command for system diagnostics
- `physical-mcp --version` flag
- GitHub Actions CI/CD (test matrix: macOS/Linux/Windows x Python 3.10-3.13)
- PyPI release workflow (trusted publishing on tag push)
- Makefile for standard dev workflow
- Vision API bearer token auth (auto-generated on setup)
- CHANGELOG.md
- Multi-user concurrent streaming — verified 3+ simultaneous MJPEG clients
- Cross-platform health endpoint hardening with normalized camera health

### Fixed
- Robust JSON extraction across all vision providers (4-stage fallback: strip markdown fences, direct parse, boundary extraction, truncation repair)
- Scene state overwrite protection in both MCP server and Vision API perception loops
- Google Gemini provider max_output_tokens increased from 500 to 1024
- Anthropic provider max_output_tokens increased from 500 to 1024

### Changed
- All vision providers now share `json_extract.extract_json()` for consistent JSON parsing
- Camera factory now supports 3 types: usb, rtsp, http

## [0.1.0] - 2026-02-17

### Added
- Initial release: ambient perception MCP server
- 16 MCP tools for camera control, scene analysis, watch rules, and memory
- Vision API with 11+ REST endpoints (frame, stream, scene, events, dashboard)
- Interactive setup wizard with auto-detection of cameras and AI apps
- Cross-platform support: macOS, Linux, Windows
- Auto-configuration for Claude Desktop, Cursor, VS Code, Windsurf, Trae, CodeBuddy
- Server-side vision analysis with pluggable providers (Anthropic, OpenAI, Google Gemini, OpenAI-compatible)
- Client-side reasoning mode (no API key needed)
- Web dashboard with live camera feed, scene descriptions, watch rules, alerts
- iOS-compatible PWA (Add to Home Screen)
- Background service installation (launchd, systemd, Task Scheduler)
- `physical-mcp snap` — capture camera frame to clipboard
- `physical-mcp watch` — continuous monitoring with hotkey, interval, or change detection
- `physical-mcp tunnel` — HTTPS tunnel via ngrok for ChatGPT GPT Action
- ChatGPT GPT Action OpenAPI spec
- Notifications: desktop, ntfy.sh push, webhook
- Perceptual hash-based change detection (local, free, <5ms)
- Persistent watch rules and memory across sessions
- QR code for phone/LAN access
- Cost control with daily budget and rate limiting
- 250 tests, MIT license
