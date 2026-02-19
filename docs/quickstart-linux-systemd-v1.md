# Quickstart: Linux + systemd + physical-mcp (v1)

## Prerequisites
- Linux host with systemd
- Python 3.10+
- USB/UVC camera connected

## Install
```bash
pip install physical-mcp
physical-mcp
```

## Verify
```bash
physical-mcp --version
physical-mcp doctor
```
Ensure camera checks pass.

## Run as background service
```bash
physical-mcp install
physical-mcp status
```
This installs a user service and starts on login.

## First use
In your AI app:
- list available tools
- capture first frame
- create a watch rule and trigger one alert

## Troubleshooting
- If service not active, re-run `physical-mcp install`.
- If camera fails, check permissions and app conflicts, then run `physical-mcp doctor`.
- For HTTPS-required clients, run `physical-mcp tunnel`.
