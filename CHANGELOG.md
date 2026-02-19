# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
