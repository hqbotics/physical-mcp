# Quickstart: macOS + launchd + physical-mcp (v1)

## Prerequisites
- macOS
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

## Run as background service
```bash
physical-mcp install
physical-mcp status
```
This registers a launchd user service and starts automatically.

## First use
In your AI app:
- list connected tools
- capture first frame
- create one watch rule and trigger one alert

## Troubleshooting
- Re-run `physical-mcp install` if service is missing.
- Check camera permissions in macOS Privacy settings.
- Use `physical-mcp tunnel` for HTTPS-required clients.
