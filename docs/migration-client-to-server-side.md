# Migration Guide: Client-Side Polling → Server-Side Monitoring (5 minutes)

## Why migrate

Server-side reasoning is the recommended default for v1.0:
- non-blocking chat UX
- background monitoring without tight polling loops
- cleaner alert delivery via MCP logs and replay APIs

Client-side polling remains fallback mode only.

## Prerequisites

- physical-mcp running
- one provider API key (Anthropic/OpenAI/Google/OpenAI-compatible)
- at least one camera configured

## Step 1 — Check current mode

Call:
- `get_system_stats()`

If `reasoning_mode` is `client`, continue.

## Step 2 — Configure provider

Call:
- `configure_provider(provider, api_key, model, base_url?)`

Examples:

### Anthropic
```text
configure_provider(
  provider="anthropic",
  api_key="sk-ant-...",
  model="claude-3-5-sonnet-20241022"
)
```

### OpenAI
```text
configure_provider(
  provider="openai",
  api_key="sk-...",
  model="gpt-4.1-mini"
)
```

### Google
```text
configure_provider(
  provider="google",
  api_key="AIza...",
  model="gemini-1.5-flash"
)
```

### OpenAI-compatible
```text
configure_provider(
  provider="openai-compatible",
  api_key="token-or-key",
  model="your-model-name",
  base_url="https://your-endpoint/v1"
)
```

## Step 3 — Verify migration

Call:
- `get_system_stats()`

Expected:
- `reasoning_mode: "server"`
- provider metadata present

## Step 4 — Verify monitoring health

Call:
- `get_camera_health()`

Expected camera fields:
- `status` should become `running`
- `consecutive_errors` should trend to `0`
- `last_success_at` should update during analysis cycles

## Step 5 — Stop client polling behavior

When in server-side mode:
- Do **not** keep fixed 10-15s `check_camera_alerts()` loops
- Keep watch rules active; rely on server-side alerting + MCP log notifications
- Use `GET /alerts` (Vision API) to replay missed events after reconnects

## Troubleshooting

### Provider errors / backoff

- Check `get_camera_health()` and `/health`
- If `status=degraded` or `backoff`, verify:
  - API key validity
  - model name
  - network egress
  - provider endpoint (`base_url` for compatible providers)

### Temporary rollback to fallback mode

Only if needed:
```text
configure_provider(provider="", api_key="")
```
Then resume client polling protocol until provider is restored.

## Recommended SOP policy

- Default all new installs to server-side setup during onboarding
- Treat fallback mode as emergency-only
- Keep `/alerts` replay integrated in clients that can reconnect/resume
