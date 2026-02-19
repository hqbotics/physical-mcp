# Common Install Failures (v1)

## Top 10 failures and fixes

1. **`physical-mcp: command not found`**
   - Re-open terminal after install.
   - Use `python -m pip install physical-mcp` then retry.

2. **No camera found**
   - Check USB connection and permissions.
   - Close other apps holding camera lock.

3. **Tools not appearing in app**
   - Re-run `physical-mcp` setup.
   - Restart the AI app completely.

4. **Tunnel URL not working**
   - Keep `physical-mcp tunnel` running.
   - Regenerate URL and update client config.

5. **Permission denied on camera access**
   - Grant camera permissions to terminal/app.
   - Retry `physical-mcp doctor`.

6. **Python version incompatibility**
   - Use Python 3.10+.
   - Reinstall in a clean virtual environment.

7. **Port conflict**
   - Stop conflicting local services.
   - Re-run setup and verify endpoint.

8. **MCP client cannot connect**
   - Confirm physical-mcp process is active.
   - Verify host/port/firewall path.

9. **Watch rules trigger too often**
   - Add persistence wording.
   - Improve camera placement and lighting consistency.

10. **Setup succeeds but commands fail later**
   - Run `physical-mcp doctor`.
   - Re-run setup to refresh config after app updates.

## If unresolved
Open a bug report with logs, OS/Python versions, app name, and exact repro steps.
