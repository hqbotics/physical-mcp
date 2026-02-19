# Quickstart: OpenClaw + physical-mcp

Use physical-mcp as the vision provider for OpenClaw automations.

## 1) Install and initialize
```bash
pip install physical-mcp
physical-mcp
```
During setup, enable OpenClaw client config.

## 2) Start service
```bash
physical-mcp serve --vision-api --host 0.0.0.0 --port 8000
```
(Optional) run as background service for always-on monitoring.

## 3) Connect in OpenClaw
Add/use the physical-mcp endpoint in your OpenClaw workflow tools.

## 4) First automation example
Rule:
- Pantry shelf looks low
Action:
- OpenClaw sends webhook -> shopping list updated

## Why this combo is strong
- Camera event -> AI reasoning -> workflow action
- Open interfaces (MCP + REST)
- Works with existing USB/IP cameras

## Troubleshooting
- Endpoint not reachable: verify host/port and firewall.
- No detections: check camera framing, light, and watch rule threshold.