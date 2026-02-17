# v1.0 Hardening Changelog (Feb 18, 2026)

## Server-side default posture
- Added startup fallback warnings when provider is not configured.
- Added in-chat startup warning emission once MCP session is available.
- Startup fallback warning now records a replayable alert event.

## MCP notifications and eventing
- Standardized MCP log format:
  - `PMCP[EVENT_TYPE] | event_id=... | camera_id=... | rule_id=... | ...`
- Added event IDs across alert/error log paths.
- Added bounded in-memory alert event store with replay retention cap.

## Vision API improvements
- Added `/health` and `/health/{camera_id}` endpoints.
- Added `/alerts` replay endpoint with filters (`limit`, `since`, `camera_id`, `event_type`).
- Standardized JSON error responses (`code`, `message`, optional `camera_id`).
- Added robust query parsing with fallback/clamping for malformed input.

## ChatGPT GPT Action wrapper
- Expanded OpenAPI schemas and examples for scene/changes/frame.
- Added health/replay endpoint support to OpenAPI.
- Added concrete schemas: `CameraHealth`, `AlertEvent`, `AlertsResponse`, etc.
- Updated GPT Action README with replay/health operational guidance.

## Reliability and tests
- Added direct tests for MCP log format and alert event buffer capping.
- Added coverage for `/health` and `/alerts` endpoint behavior.
- Added coverage for JSON error contract.
- Deflaked change detector high-change random-frame test.
- Removed notifier test warning debt by fixing async context-manager mocks.
