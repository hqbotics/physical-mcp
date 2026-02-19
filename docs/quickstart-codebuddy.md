# Quickstart: CodeBuddy + physical-mcp

## Prerequisites
- CodeBuddy installed
- Python 3.10+
- USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```
Setup auto-detects compatible app configs where supported.

## Verify
1. Restart CodeBuddy.
2. Ask your assistant to list connected MCP tools.
3. Confirm camera tools (for example `capture_frame`) are available.

## First use
Try:
- `Capture a frame and summarize the scene.`
- `Create a watch rule for package arrival and return alerts.`

## Troubleshooting
- Re-run `physical-mcp` after app/config updates.
- Run `physical-mcp doctor` if tools or camera access fail.
