# Quickstart: VS Code + physical-mcp

## Prerequisites
- VS Code with MCP-compatible extension/workflow
- Python 3.10+
- A USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```
The setup wizard writes MCP config for supported VS Code workflows.

## Verify
1. Restart VS Code.
2. Open your AI assistant panel.
3. Ask: `What MCP tools are connected?`

## First use
Try:
- `Capture a frame from camera 0.`
- `Watch this camera and notify when a package appears.`

## Troubleshooting
- Re-run `physical-mcp` after VS Code updates/extensions change.
- Check camera permissions if frame capture fails.
