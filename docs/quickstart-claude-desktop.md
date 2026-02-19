# Quickstart: Claude Desktop + physical-mcp

## Prerequisites
- macOS or Windows with Claude Desktop installed
- Python 3.10+
- A USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```
The setup wizard auto-detects camera + Claude Desktop and writes config.

## Verify
1. Restart Claude Desktop.
2. In Claude, ask: `List available MCP tools.`
3. Confirm tools like `capture_frame` appear.

## First use
Prompt Claude:
- `Capture a frame and describe what you see.`
- `Watch for changes at my desk and alert me.`

## Troubleshooting
- If no tools appear, run `physical-mcp` again and restart Claude.
- If no camera is found, test another USB port and re-run setup.
