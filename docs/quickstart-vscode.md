# Quickstart: VS Code + physical-mcp

Turn VS Code into a live vision-aware assistant workspace.

## 1) Install physical-mcp
```bash
pip install physical-mcp
physical-mcp
```
Select VS Code integration when prompted.

## 2) Reload VS Code
Run “Developer: Reload Window” or restart VS Code.

## 3) Validate MCP connection
In your AI assistant panel, run:
- `List physical-mcp MCP tools`
- `Capture one frame and describe scene changes`

## 4) Add a practical watch rule
Example:
`Watch front door camera and send me context-rich alerts, not just motion pings.`

## Why use this setup
- AI reasoning + action hooks, not dead-end notifications
- Open source and local-first
- No 5-minute blind spot behavior on free usage path

## Troubleshooting
- No tools loaded: rerun setup and check VS Code MCP config path.
- Camera unavailable: test with `physical-mcp doctor`.