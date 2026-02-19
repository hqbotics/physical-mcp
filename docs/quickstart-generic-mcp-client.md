# Quickstart: Generic MCP Client + physical-mcp

## Prerequisites
- Any MCP-compatible client
- Python 3.10+
- USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```

## Connect
Use your client’s MCP server config to point at physical-mcp.
If remote/HTTPS is required:
```bash
physical-mcp tunnel
```

## Verify
1. List available tools in your MCP client.
2. Confirm camera tools (e.g. `capture_frame`) are visible.

## First use
- `Capture current frame.`
- `Set a watch rule and return alerts.`

## Troubleshooting
- Ensure physical-mcp process is running.
- Check firewall/port access if remote client cannot connect.
- Run `physical-mcp doctor` for quick diagnostics.
