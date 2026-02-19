# Quickstart: Cursor + physical-mcp

Connect real camera events to your coding workflow.

## 1) Install
```bash
pip install physical-mcp
physical-mcp
```
Choose Cursor when prompted for MCP client setup.

## 2) Restart Cursor
Fully restart Cursor so MCP config reloads.

## 3) Verify in chat
Ask Cursor:
- `List physical-mcp tools.`
- `Capture a frame from camera usb:0 and summarize it.`

## 4) Useful dev rule
`Watch my 3D printer area and alert me in this chat when print failure is likely.`

## Why this beats consumer camera apps
- You get AI context in your dev environment
- Open APIs for downstream actions
- Not locked to one camera brand or app

## Troubleshooting
- MCP tools missing: rerun `physical-mcp` setup and reselect Cursor.
- Frame timeouts: reduce resolution/FPS in config and retry.