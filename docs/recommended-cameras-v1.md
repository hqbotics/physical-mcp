# Recommended Cameras (v1, software-only launch)

> physical-mcp is software-first. These are practical UVC camera suggestions for reliable onboarding.

## What to look for
- UVC USB compatibility
- Stable 720p/1080p output
- Decent low-light behavior
- Reliable auto-exposure (reduces noisy false triggers)

## Starter shortlist (from current HW validation notes)
1. **OV2710 2MP USB** (budget baseline)
2. **IMX335 5MP USB** (balanced quality/cost)
3. **OS08A10 8MP USB** (premium low-light)

## Suggested defaults
- Start at 1280x720
- Keep camera static when possible
- Avoid strong backlight directly facing lens

## Setup check
1. Connect camera
2. Run `physical-mcp`
3. Verify frame capture succeeds
4. Run `physical-mcp doctor`

## Notes
- High megapixel is less important than stable exposure for watch-rule quality.
- For launch docs, recommend widely available UVC devices before niche modules.
