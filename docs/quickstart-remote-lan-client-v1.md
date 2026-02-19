# Quickstart: Remote LAN Client + physical-mcp (v1)

## Prerequisites
- physical-mcp running on a host in your LAN
- Host IP reachable from your AI client device
- LAN firewall allows configured port

## Start on host
```bash
physical-mcp
```
Note the LAN endpoint shown by setup/status.

## Verify host health
```bash
physical-mcp doctor
physical-mcp status
```

## Connect from client
- In your AI app/client, configure MCP/HTTP endpoint using host LAN IP.
- If your client requires HTTPS, use `physical-mcp tunnel` instead.

## First use
- list connected tools
- capture first frame
- create one watch rule and trigger one alert

## Troubleshooting
- Check host/client are on same network.
- Confirm firewall allows host port.
- Re-run setup if endpoint changed.
