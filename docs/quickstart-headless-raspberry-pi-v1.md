# Quickstart: Headless Raspberry Pi + physical-mcp (v1)

## Prerequisites
- Raspberry Pi with Raspberry Pi OS (Lite/headless OK)
- SSH access to Pi
- Python 3.10+
- USB/UVC camera connected

## Install
```bash
python3 -m pip install physical-mcp
physical-mcp
```

## Verify
```bash
physical-mcp --version
physical-mcp doctor
```
Ensure camera and environment checks pass.

## Run as background service
```bash
physical-mcp install
physical-mcp status
```

## First use
From your AI client:
- list tools
- capture first frame
- create one watch rule

## Troubleshooting
- If camera missing, check `ls /dev/video*` and USB power.
- If remote client needs HTTPS, run `physical-mcp tunnel`.
- If service fails, rerun install and check status output.
