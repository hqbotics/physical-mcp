# Windsurf + Trae Troubleshooting (v1)

## 1) Tools not visible after setup
- Re-run:
```bash
physical-mcp
```
- Fully restart Windsurf/Trae.
- Ask assistant to list MCP tools again.

## 2) Camera not detected
- Reconnect USB camera.
- Close other camera apps (Zoom/Meet/OBS/etc).
- Run:
```bash
physical-mcp doctor
```

## 3) Endpoint/connectivity errors
- Ensure physical-mcp process is running.
- If remote/HTTPS is required, run:
```bash
physical-mcp tunnel
```
- Use the generated HTTPS URL in your app integration path.

## 4) Alerts too noisy
- Start with simpler watch-rule wording.
- Use persistence/duration constraints (for example “for 2 minutes”).
- Improve lighting/camera angle stability.

## 5) Still blocked?
Open an issue with:
- OS + Python version
- app (Windsurf/Trae)
- exact command output/logs
- repro steps
