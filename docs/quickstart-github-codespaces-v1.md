# Quickstart: GitHub Codespaces + physical-mcp (v1)

## Prerequisites
- GitHub account with Codespaces access
- Browser access to your Codespace
- A reachable camera source (local USB passthrough may be limited in cloud)

## Start
1. Open the repo in Codespaces.
2. In terminal:
```bash
pip install physical-mcp
physical-mcp --version
physical-mcp doctor
```

## Verify
- Confirm install and diagnostics run.
- Validate MCP/HTTP endpoints start without config errors.

## First use (cloud-safe path)
- Test tooling and config flow first.
- For live camera workflows, run physical-mcp on a local machine and connect from your client using HTTPS tunnel when needed.

## Notes
- Codespaces is great for code/docs/tests and integration checks.
- Camera hardware access is usually better from local host environments.
