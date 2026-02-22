# Quickstart: Google Gemini + physical-mcp

physical-mcp supports **Google Gemini as a server-side vision provider** (your API key, your account). Gemini is NOT a native MCP client like Claude Desktop — you interact with it via other MCP clients or use the Vision API directly.

## What This Means

- **Gemini ≠ MCP client**: Use Claude Desktop, Cursor, VS Code, or ChatGPT as your MCP client
- **Gemini = AI vision provider**: physical-mcp can call Gemini API for scene analysis (optional)

## Two Ways to Use Gemini

### Option A: Use Gemini API for Vision Analysis (Server-Side)

Enable automatic scene analysis with Gemini's vision models:

```bash
pip install physical-mcp physical-mcp setup --advanced
```

During setup (advanced mode), select:
```
2. Google Gemini (FREE tier: 15 req/min, 1M tokens/day)
```

Enter your API key from [Google AI Studio](https://aistudio.google.com/apikey).

Then use any MCP client (Claude, Cursor, etc.) — they'll get automatic scene descriptions.

### Option B: Use Gemini API Key in Any MCP Client (Client-Side)

If your MCP client supports tools, just run physical-mcp without a provider:

```bash
pip install physical-mcp
physical-mcp setup  # Simple mode, no API key
```

The MCP client (Claude, ChatGPT, etc.) will receive frames and can analyze them with its own Gemini integration.

## Verify Setup

```bash
physical-mcp doctor
```

Expected output if using Gemini provider:
```
Vision provider: google / gemini-2.0-flash
```

## Configuration Reference

```yaml
# ~/.physical-mcp/config.yaml
reasoning:
  provider: google
  api_key: "YOUR_API_KEY"
  model: "gemini-2.0-flash"  # or gemini-2.5-pro-preview-06-05
```

## Supported Models

| Model | Speed | Cost | Best For |
|-------|-------|------|----------|
| `gemini-2.0-flash` | Fast | Free tier | Real-time monitoring |
| `gemini-2.5-pro-preview-06-05` | Medium | Limited free | Complex analysis |
| `gemini-2.0-flash-lite` | Fastest | Lowest | High-frequency scenes |

## Troubleshooting

**"Vision provider: none" in doctor output**
- Re-run setup with `--advanced` flag
- Check your API key at https://aistudio.google.com/app/apikey

**Rate limit errors**
- Gemini free tier: 15 requests/minute, 1M tokens/day
- Use `gemini-2.0-flash-lite` for lowest cost

**See also:**
- [Migration guide: Client-side to server-side reasoning](migration-client-to-server-side.md)
