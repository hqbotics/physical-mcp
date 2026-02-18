# ChatGPT GPT Action Wrapper (No MCP Required)

ChatGPT doesn't support MCP tool servers directly, so use this GPT Action wrapper over the HTTP Vision API.

## 1) Start physical-mcp with Vision API enabled

Vision API is on by default (`vision_api.enabled: true`) and serves on port `8090`.

## 2) Expose HTTPS endpoint

ChatGPT Actions require HTTPS. Use `physical-mcp tunnel` (or Cloudflare/ngrok) and copy the public URL.

## 3) Create GPT Action

1. Open ChatGPT GPT Builder
2. Go to **Actions** → **Add action**
3. Paste `gpt-action/openapi.yaml`
4. Replace `https://YOUR-PHYSICAL-MCP-HOST` with your HTTPS endpoint
5. Save

## 4) Recommended Action policy

- Use `/scene` first for lightweight context
- Use `/changes?wait=true` for non-blocking monitoring
- Pull `/frame/{camera_id}` only when visual confirmation is required
- Use `/health` if monitoring quality appears degraded (provider/backoff visibility)
- Use `/alerts` for replay after reconnects or missed turns
- PMCP logs are now mirrored to structured internal `mcp_log` events (same `event_id`) for subscriber integrations/observability.
- Keep polling interval >= 10s to reduce load

## Troubleshooting

- **No events in `/alerts` after reconnect**
  - Check `since` cursor isn't in the future.
  - Retry without `since` to confirm baseline replay works.
  - Invalid `since` values are ignored by the API (treated as no cursor).
  - Example: `GET /alerts?event_type=startup_warning` to confirm fallback-mode warnings are being recorded.
- **Monitoring appears stale**
  - Call `/health` and check `status`, `consecutive_errors`, `backoff_until`.
  - If degraded/backoff persists, verify provider key/model/network in MCP config.
  - Example: `GET /alerts?event_type=provider_error&limit=5` to correlate health degradation with provider failures.
  - Pending-eval queue example: `GET /alerts?camera_id=%20usb:0%20&event_type=CAMERA_ALERT_PENDING_EVAL&limit=1`.
  - Correlation pattern: a `camera_alert_pending_eval` event often precedes a `watch_rule_triggered` event for the same camera.
  - Correlate by `event_id`: `/alerts` rows, PMCP logs, and internal `mcp_log` fanout now share the same id for key alert paths (e.g., `provider_error`, `watch_rule_triggered`).
  - Event-id-first triage flow: capture `event_id` from PMCP log, then query `/alerts?event_type=<type>&limit=50` and match the same `event_id` row for replay/context.

  Correlation matrix:
  - `provider_error` → fields: `event_id`, `camera_id`
  - `watch_rule_triggered` → fields: `event_id`, `camera_id`, `rule_id`
  - `camera_alert_pending_eval` → fields: `event_id`, `camera_id`
  - `startup_warning` → fields: `event_id`
  - Startup warning triage: if PMCP startup warning appears, use that `event_id` to find the same `/alerts` row and confirm fallback-mode context (startup or runtime switch from server-side to fallback).

  Startup warning expected JSON shape:
  - ```json
    {
      "event_id": "evt_start_101",
      "event_type": "startup_warning",
      "camera_id": "",
      "camera_name": "",
      "rule_id": "",
      "rule_name": "",
      "message": "Server is running in fallback client-side reasoning mode...",
      "timestamp": "2026-02-18T04:12:30.000000"
    }
    ```
  - Runtime-switch variant uses the same event schema and `event_type=startup_warning`, but message text indicates server-side → fallback transition.

  Startup_warning message patterns:
  - Startup fallback: `Server is running in fallback client-side reasoning mode...`
  - Runtime switch fallback: `Runtime switched to fallback client-side reasoning mode...`
  - `event_type` is stable (`startup_warning`) for both; use `message` text to distinguish startup vs runtime-switch variants.
  - PMCP log wording should mirror the same pattern split (startup logs should not contain runtime-switch phrasing, and vice versa).
  - PMCP prefix contract: startup_warning PMCP log lines begin with `PMCP[STARTUP_WARNING] | event_id=`.
  - EventBus mirror contract: `mcp_log.data` uses the same `PMCP[STARTUP_WARNING] | event_id=` prefix.
  - OpenAPI references: `startup_warning_event_id_correlation` (startup) and `startup_warning_runtime_switch_variant` (runtime switch).

  Fallback startup warning diagnostics (quick table):
  - Symptom: PMCP shows fallback startup warning on connect
    - PMCP line: `PMCP[STARTUP_WARNING] | event_id=... | ...`
    - Replay query: `GET /alerts?event_type=startup_warning&limit=5`
    - Expected row: same `event_id`, message mentions fallback mode + provider recommendation
  - Symptom: Warning seen in `/alerts` but not in PMCP chat
    - PMCP line: absent
    - Replay query: `GET /alerts?event_type=startup_warning&limit=5`
    - Expected row: startup warning exists; verify client session/log permissions
  - Per-camera drilldown example: `GET /alerts?since=<last_seen>&camera_id=usb:0&event_type=provider_error&limit=10`
  - Replay order is deterministic: oldest→newest by `timestamp` (tie-break by `event_id`).
  - `since` is exclusive: events exactly at the cursor timestamp are not returned.
  - Boundary + limit example: `GET /alerts?since=2026-02-18T02:50:00&camera_id=%20usb:0%20&event_type=PROVIDER_ERROR&limit=1`
  - Normalized-input example: `GET /alerts?camera_id=%20usb:0%20&event_type=PROVIDER_ERROR&limit=1`
  - Mixed-edge example: `GET /alerts?since=not-a-time&camera_id=%20usb:0%20&event_type=PROVIDER_ERROR&limit=1`
  - `event_type` matching is case-insensitive (including replayed events with uppercase or space-padded stored types), and surrounding spaces in `camera_id` are ignored.
  - Replay filtering also tolerates legacy stored rows where `camera_id` or `event_type` were space-padded/mixed-case.
  - Legacy malformed alert timestamps are tolerated; for `since` cursor queries those malformed rows are skipped to preserve deterministic pagination.
  - `since` accepts `Z` timezone values (example: `2026-02-18T03:30:00Z`).
  - Boundary-equal rows are always excluded (`since` is exclusive), including mixed timezone rows (`+00:00` and naive timestamps).
  - Migration note: if your old client depended on lexical string timestamp comparison, switch to strict ISO datetime parsing and treat all times as UTC-normalized before cursor math.
  - `/changes` has the same camera-id normalization; invalid `since` values are ignored there too.
  - Example: `GET /changes?since=bad-cursor&camera_id=%20usb:0%20`
- **Frame fetch fails for a camera**
  - Verify camera id from `/scene` keys.
  - Expect JSON errors like `camera_not_found` when ids mismatch.

- **Provider switch changed monitoring mode unexpectedly**
  - `configure_provider(...)` response now includes:
    - `fallback_warning_emitted` (boolean)
    - `fallback_warning_reason` (`"runtime_switch"` or `""`)
  - Downgrade example (server → fallback):
    - `{ "reasoning_mode": "client", "fallback_warning_emitted": true, "fallback_warning_reason": "runtime_switch" }`
  - Upgrade example (fallback → server):
    - `{ "reasoning_mode": "server", "fallback_warning_emitted": false, "fallback_warning_reason": "" }`
  - Replay verification after downgrade: if `fallback_warning_reason == "runtime_switch"`, confirm warning persistence via `/alerts?event_type=startup_warning&limit=5` and match `event_id` with PMCP log.

## Notes

- This wrapper is read-only by design for safety.
- For full watch-rule automation, use MCP clients (Claude Desktop, Cursor, OpenClaw).
- For operator incident response flow, see `docs/health-alerts-debug-playbook.md`.
- For replay cursor/timezone migration details, see `docs/replay-cursor-migration.md`.
