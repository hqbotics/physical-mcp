# First 10 Minutes Playbook (v1)

## Minute 0-2: Install
```bash
pip install physical-mcp
physical-mcp
```
Connect your camera before running setup.

## Minute 2-4: Verify health
```bash
physical-mcp --version
physical-mcp doctor
```
Confirm camera and environment checks pass.

## Minute 4-6: Confirm tool connectivity
Open your AI app and ask:
- `List available MCP tools.`
- `Capture a frame from camera 0.`

## Minute 6-8: Create first watch rule
Prompt:
- `Create a watch rule for package arrival at front door.`

## Minute 8-10: Trigger and verify alert path
- Simulate movement/package event
- Check alert/log output in your app
- If needed, tune rule wording for persistence/noise

## If something breaks
1. Re-run `physical-mcp`
2. Re-run `physical-mcp doctor`
3. Check quickstart for your app in `docs/`
4. Open a bug report with logs and environment details
