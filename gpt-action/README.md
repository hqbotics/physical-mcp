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
- Keep polling interval >= 10s to reduce load

## Notes

- This wrapper is read-only by design for safety.
- For full watch-rule automation, use MCP clients (Claude Desktop, Cursor, OpenClaw).
