# Quickstart: OpenClaw + physical-mcp

Use physical-mcp as the vision provider for OpenClaw automations.

## 1) Install and initialize

```bash
pip install physical-mcp
physical-mcp
```

During setup, enable HTTP mode for LAN access.

## 2) Start service

```bash
physical-mcp --transport streamable-http --port 8090
```

Or run as background service for always-on monitoring:
```bash
physical-mcp install --port 8090
```

## 3) Access Vision API

The dashboard is available at:
- Local: `http://127.0.0.1:8090/dashboard`
- LAN: `http://<your-ip>:8090/dashboard` (shown in startup output)
- mDNS: `http://physical-mcp.local:8090/dashboard` (if supported)

## 4) Connect in OpenClaw

Use the REST endpoints directly:
- `GET /frame` - capture current frame (returns JPEG)
- `GET /stream` - MJPEG stream for live view
- `GET /health` - camera health status
- `GET /scene` - current scene description

## First automation example

Rule: Pantry shelf looks low  
Action: OpenClaw webhook -> shopping list updated

## Why this combo is strong

- Camera event -> AI reasoning -> workflow action
- Open interfaces (MCP + REST)
- Works with existing USB/IP cameras

## Troubleshooting

- Endpoint not reachable: verify host/port and firewall.
- No detections: check camera framing, light, and watch rule threshold.
- mDNS not working: use IP address directly
