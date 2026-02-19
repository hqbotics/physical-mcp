# OpenClaw Vision Agent Architecture (v1.0)

## Goal

Integrate physical-mcp with OpenClaw so monitoring runs continuously in background while chat stays responsive.

## Recommended topology

1. **physical-mcp server** (camera + perception + HTTP Vision API)
2. **OpenClaw main assistant session** (user-facing chat)
3. **OpenClaw isolated vision sub-agent** (long-running watcher)
4. **Notification bridge**
   - MCP log messages for in-chat surfacing
   - optional ntfy/webhook/desktop for out-of-band alerts

## Control flow

1. Main chat receives: "watch front door"
2. Main assistant creates/updates watch rule in physical-mcp
3. Main assistant spawns isolated sub-agent dedicated to monitoring
4. Vision sub-agent:
   - preferred: server-side mode (provider configured)
   - fallback: polls `check_camera_alerts` + `report_rule_evaluation`
5. physical-mcp emits MCP logs on trigger/error
6. Main assistant remains free for normal conversation

## Why this works

- Avoids blocking UX from tight polling loops
- Contains long-running monitor behavior in isolated agent
- Alerts still surface to user in the main chat channel
- Supports ChatGPT via HTTP wrapper and Claude/Cursor/OpenClaw via MCP

## Operational SOP

- Default policy: configure provider key on setup and run server-side mode
- If provider unavailable, start fallback polling sub-agent with explicit stop condition
- Use cooldowns and MCP log levels (`warning` for alerts, `error` for provider failures)
- Keep per-camera failures isolated; never stall all cameras on one provider error

## Future extension

- Add `monitor_session_id` to each watch rule for explicit ownership
- Add event replay endpoint (`/alerts`) so agents can recover after restart
- Add per-camera provider routing (different models per camera criticality)
