# Quickstart: Trae + physical-mcp

## Prerequisites
- Trae installed
- Python 3.10+
- USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```
physical-mcp setup detects compatible apps and writes config.

## Verify
1. Restart Trae.
2. Ask for available MCP tools.
3. Confirm camera tool visibility (e.g. `capture_frame`).

## First use
Try:
- `Capture current frame from camera 0.`
- `Set a watch rule and return alerts when triggered.`

## Troubleshooting
- If tools are missing, re-run setup and restart Trae.
- If camera access fails, close other camera apps and retry.
