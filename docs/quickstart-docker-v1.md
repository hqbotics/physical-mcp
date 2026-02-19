# Quickstart: Docker + physical-mcp (v1)

## Prerequisites
- Docker installed
- Camera access from host environment (USB passthrough support varies by OS)

## Build image (from repo root)
```bash
docker build -t physical-mcp:local .
```

## Run (host networking example)
```bash
docker run --rm -it --network host physical-mcp:local physical-mcp --version
```

## Verify
- Container starts and CLI responds.
- Run health checks from host-side setup path where camera is available.

## First use recommendation
For fastest camera success, run physical-mcp directly on host first. Use Docker primarily for repeatable dev/test packaging unless your camera passthrough setup is validated.

## Troubleshooting
- If camera isn’t visible in container, switch to host-run path.
- If ports conflict, stop existing services and retry.
