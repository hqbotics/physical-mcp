# Quickstart: Gemini + physical-mcp

## Prerequisites
- Gemini app/workflow that can call external MCP/HTTP tools
- Python 3.10+
- USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```
If Gemini needs HTTPS/remote endpoint, run:
```bash
physical-mcp tunnel
```

## Verify
1. Confirm physical-mcp is running.
2. In Gemini, connect configured endpoint.
3. Ask Gemini to list camera/tool capabilities.

## First use
Try:
- `Capture a frame and summarize what changed.`
- `Create a watch rule for package arrival.`

## Troubleshooting
- If Gemini can’t reach local endpoint, use tunnel URL.
- Re-run `physical-mcp doctor` for diagnostics.
