# Replay Cursor Migration Notes (Vision API `/alerts`)

Use this when upgrading older clients that consumed `/alerts` with ad-hoc timestamp logic.

## Current semantics (authoritative)

- `since` is **exclusive**.
  - Rows with `timestamp == since` are excluded.
- `since` accepts ISO datetime, including `Z` suffix.
  - Example: `since=2026-02-18T03:30:00Z`
- Invalid `since` values are ignored.
  - Behaves like no cursor.
- Replay ordering is deterministic:
  - sort by parsed timestamp (oldest → newest), then `event_id`.
- Mixed timestamp formats are tolerated:
  - naive (`2026-02-18T03:30:00`)
  - aware (`2026-02-18T03:30:00+00:00`)
- Malformed stored timestamps are tolerated:
  - excluded from cursor comparisons
  - still handled safely in replay ordering

## If your old client used lexical string comparison

Migrate to this algorithm:

1. Parse `timestamp` as ISO datetime (strict parser)
2. Normalize to UTC
3. Compare datetimes (not strings)
4. Apply exclusive cursor (`event_ts > since_ts`)
5. Apply filters (`camera_id`, `event_type`) and `limit`

## Query patterns

- Resume after reconnect:
  - `GET /alerts?since=<last_seen_iso>&camera_id=usb:0&limit=50`
- Provider-only replay:
  - `GET /alerts?event_type=provider_error&limit=20`
- Invalid cursor fallback behavior check:
  - `GET /alerts?since=bad-cursor&camera_id=usb:0&event_type=provider_error&limit=1`

## Related docs

- `gpt-action/README.md`
- `docs/migration-client-to-server-side.md`
- `docs/health-alerts-debug-playbook.md`
