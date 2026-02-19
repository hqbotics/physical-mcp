# Quickstart: Claude Desktop + physical-mcp

Give your AI eyes in ~5 minutes.

## 1) Install
```bash
pip install physical-mcp
physical-mcp
```
During setup, pick your camera and enable Claude Desktop integration.

## 2) Restart Claude Desktop
Completely quit and reopen Claude Desktop.

## 3) Verify tools
Ask Claude:
- `List available MCP tools from physical-mcp.`
- `Capture a frame and describe what you see.`

You should see tools like `capture_frame`, `watch_scene`, and alert tools.

## 4) First automation
Try:
`Create a watch rule for my pantry shelf and alert me when items look low.`

## Why this beats app-only camera alerts
- Open workflow (MCP + REST), not dead-end notifications
- No 5-minute blind spot behavior on free usage path
- Works with your existing camera hardware

## Troubleshooting
- No tools in Claude: run `physical-mcp` again, then restart Claude.
- Camera not found: reconnect camera and run `physical-mcp doctor`.