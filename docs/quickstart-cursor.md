# Quickstart: Cursor + physical-mcp

## Prerequisites
- Cursor installed
- Python 3.10+
- A USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```
Setup auto-configures Cursor MCP settings.

## Verify
1. Restart Cursor.
2. Ask Cursor agent: `Show available MCP tools.`
3. Confirm `capture_frame` and related tools are visible.

## First use
Use prompts:
- `Capture a frame and tell me what changed since last frame.`
- `Create a rule to alert when motion persists for 2 minutes.`

## Troubleshooting
- If tools are missing, re-run `physical-mcp` then restart Cursor.
- If camera is busy, close other camera apps and retry.
