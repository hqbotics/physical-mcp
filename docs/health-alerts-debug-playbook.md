# Health + Alerts Debug Playbook (Operator Quick Flow)

Use this when monitoring looks stale or alerts seem inconsistent.

## 1) Check camera health first

Call:
- `GET /health`
- or `GET /health/{camera_id}`

Look at:
- `status` (`running`, `degraded`, `backoff`)
- `consecutive_errors`
- `backoff_until`
- `last_success_at`

## 2) Correlate with replayed alert events

Call:
- `GET /alerts?event_type=provider_error&limit=10`
- `GET /alerts?event_type=startup_warning&limit=10`
- `GET /alerts?camera_id=<camera_id>&limit=20`

Interpretation:
- repeated `provider_error` + `degraded/backoff` health => provider outage or key/model/network issue
- `startup_warning` events => server started in fallback client-side mode

## 3) Validate cursor usage

If you use `since`, ensure it is not in the future.

Quick baseline check:
- `GET /alerts?limit=20`

Then re-apply cursor:
- `GET /alerts?since=<last_seen_timestamp>&limit=20`

## 4) Recovery actions

- If fallback mode is active, configure provider:
  - `configure_provider(provider, api_key, model, base_url?)`
- If provider remains degraded:
  - verify API key/model/base URL
  - verify network egress and provider status

## 5) Re-check health + replay

After remediation:
- `GET /health` should trend to `status=running`, `consecutive_errors=0`
- `GET /alerts?event_type=provider_error&limit=5` should stop accumulating new errors

## Degraded → Recovered walkthrough (example)

1. **Symptom**
   - `/health/usb:0` shows `status=degraded`, `consecutive_errors=5`, non-null `backoff_until`
2. **Correlate**
   - `/alerts?camera_id=usb:0&event_type=provider_error&limit=10` shows recent provider timeouts
3. **Fix**
   - update provider config (`configure_provider(...)`) or restore network/API key
4. **Verify recovery**
   - `/health/usb:0` returns `status=running`, `consecutive_errors=0`, updated `last_success_at`
   - new `/alerts?camera_id=usb:0&event_type=provider_error&limit=5` no longer grows
