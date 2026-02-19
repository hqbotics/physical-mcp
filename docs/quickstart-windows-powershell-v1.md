# Quickstart: Windows PowerShell + physical-mcp (v1)

## Prerequisites
- Windows 10/11
- Python 3.10+
- USB/UVC camera connected
- PowerShell terminal

## Install
```powershell
py -m pip install physical-mcp
physical-mcp
```

## Verify
```powershell
physical-mcp --version
physical-mcp doctor
```
Confirm diagnostics and camera checks pass.

## First use
In your AI app, run:
- `List available MCP tools`
- `Capture a frame from camera 0`
- `Create a watch rule for package arrival`

## Troubleshooting
- If command not found: restart PowerShell after install.
- If camera fails: close camera-using apps and re-run `physical-mcp doctor`.
- If remote client needs HTTPS: run `physical-mcp tunnel`.
