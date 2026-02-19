# Quickstart: OpenClaw + physical-mcp

## Prerequisites
- OpenClaw running
- Python 3.10+
- A USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```
Keep physical-mcp running locally or as a background service.

## Verify
1. In OpenClaw, connect to the physical-mcp MCP endpoint.
2. Ask your agent: `List available camera tools.`
3. Confirm tool calls like `capture_frame` succeed.

## First use
Try:
- `Capture and analyze the current frame.`
- `Set a watch rule for front-door package arrival.`

## Troubleshooting
- If endpoint is unreachable, check host/port and firewall.
- For remote access, use `physical-mcp tunnel` and HTTPS endpoint.
