# Pantry -> Notion Webhook Demo (v1)

## Goal
When pantry stock looks low, trigger a webhook that updates a shopping list in Notion.

## Prerequisites
- physical-mcp running
- Camera pointed at pantry shelves
- Webhook endpoint that writes to Notion

## Flow
1. Create watch rule:
   - "Alert when rice or cereal container looks low for 2+ minutes"
2. On trigger, send structured payload to webhook:
```json
{
  "event": "pantry_low_stock",
  "item_hint": "rice",
  "camera_id": "camera0",
  "timestamp": "<iso-time>"
}
```
3. Webhook appends item to Notion shopping list.

## Quick test
- Simulate low stock scene
- Confirm alert generated
- Confirm Notion list updated

## Notes
- Keep item names constrained for reliable automation.
- Use persistence windows to reduce noisy triggers.
