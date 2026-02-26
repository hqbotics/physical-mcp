# Physical MCP Setup Guide

Get AI-powered camera alerts on your phone in 10 minutes.

---

## What You'll Set Up

```
Your Camera → physical-mcp → AI Analysis → Phone Alert (with photo)
```

By the end of this guide, your AI will watch your camera 24/7 and send you
Telegram alerts with photos when something happens.

---

## Step 1: Install physical-mcp

**On Mac or Linux:**
```bash
pip install physical-mcp
```

**On Windows:**
```powershell
pip install physical-mcp
```

**Verify it works:**
```bash
physical-mcp --version
```
You should see `physical-mcp 1.1.0` or newer.

> **Trouble?** Run `physical-mcp doctor` to diagnose common issues.

---

## Step 2: Set Up Telegram Alerts

You'll get alerts as Telegram messages with camera photos attached.

### Create a Telegram Bot (2 minutes)

1. Open Telegram on your phone
2. Search for **@BotFather** and start a chat
3. Send `/newbot`
4. Choose a name (e.g., "My Home Camera")
5. Choose a username (e.g., "myhomecamera_bot")
6. BotFather gives you a **token** like `7905075025:AAG_sVhBnoL06yw...`
7. **Save this token** — you'll need it in Step 4

### Get Your Chat ID

1. Open your new bot in Telegram and send it any message (e.g., "hello")
2. Open this URL in your browser (replace YOUR_TOKEN):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Look for `"chat":{"id":123456789}` — that number is your **chat ID**
4. **Save this chat ID** — you'll need it in Step 4

---

## Step 3: Get an AI Vision Key

physical-mcp needs an AI provider to understand what the camera sees.

### Option A: Google Gemini (Recommended — Free tier available)

1. Go to [aistudio.google.com](https://aistudio.google.com/)
2. Click "Get API Key" → "Create API Key"
3. Copy your key (starts with `AIza...`)

### Option B: OpenRouter (Multiple models, pay-per-use)

1. Go to [openrouter.ai](https://openrouter.ai/)
2. Sign up → go to Keys → Create Key
3. Copy your key (starts with `sk-or-...`)

### Option C: OpenAI (GPT-4 Vision)

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create new secret key
3. Copy your key (starts with `sk-...`)

---

## Step 4: Configure physical-mcp

Run the setup wizard:
```bash
physical-mcp setup
```

The wizard will:
- Detect your camera automatically
- Ask for your AI provider key (from Step 3)
- Ask for your Telegram bot token and chat ID (from Step 2)
- Save everything to `~/.config/physical-mcp/config.yaml`

**Or configure manually** — create `~/.config/physical-mcp/config.yaml`:

```yaml
cameras:
  - type: usb
    device_index: 0
    name: "My Camera"

reasoning:
  provider: google          # or: openai, anthropic, openai-compatible
  api_key: "YOUR_API_KEY"

notifications:
  telegram_bot_token: "YOUR_BOT_TOKEN"
  telegram_chat_id: "YOUR_CHAT_ID"
```

---

## Step 5: Start physical-mcp

```bash
physical-mcp
```

You should see:
```
physical-mcp v1.1.0
Camera: My Camera (usb:0) — 1280x720
Vision: google/gemini-2.0-flash
Notifications: telegram
Ready. Waiting for MCP client connection...
```

---

## Step 6: Create Your First Watch Rule

### Using Claude Desktop, Cursor, or VS Code

Just ask your AI:
> "Watch for anyone at the front door and alert me on Telegram"

The AI will create a watch rule automatically.

### Using the REST API

```bash
curl -X POST http://localhost:8090/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Person at Door",
    "condition": "A person is visible at the door",
    "priority": "high"
  }'
```

### Using a Pre-Built Template

```bash
# List available templates
curl http://localhost:8090/templates

# Create from template
curl -X POST http://localhost:8090/templates/person-at-door/create
```

Available templates:
- `person-detection` — Alert when any person appears
- `person-at-door` — Alert when someone is at the door
- `package-delivered` — Alert when a package arrives
- `pet-on-furniture` — Alert when pet climbs on furniture
- `baby-monitor` — Alert when baby is in distress
- `motion-alert` — Alert on any movement

---

## Step 7: Test It

Walk in front of your camera. Within 30-60 seconds you should receive
a Telegram message with:
- The rule name that triggered
- A description of what was detected
- A photo from the camera

**That's it! Your AI now watches your camera 24/7.**

---

## Run in the Background

### Mac (launchd)
```bash
# Create a launch agent so physical-mcp starts automatically
cat > ~/Library/LaunchAgents/com.physical-mcp.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.physical-mcp</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/physical-mcp</string>
    <string>--headless</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.physical-mcp.plist
```

### Linux (systemd)
```bash
sudo tee /etc/systemd/system/physical-mcp.service << 'EOF'
[Unit]
Description=Physical MCP Camera Server
After=network.target

[Service]
ExecStart=/usr/local/bin/physical-mcp --headless
Restart=always
User=YOUR_USERNAME

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now physical-mcp
```

### Docker
```bash
docker run -d --device /dev/video0 \
  -e REASONING_PROVIDER=google \
  -e REASONING_API_KEY=your_key \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e TELEGRAM_CHAT_ID=your_chat_id \
  --name physical-mcp \
  ghcr.io/hqbotics/physical-mcp
```

---

## IP Camera Setup (RTSP/HTTP)

For IP cameras like WOSEE, Wyze, Reolink, Tapo:

### 1. Find Your Camera

```bash
physical-mcp discover
```

This scans your network for cameras and shows their URLs.

### 2. Add to Config

```yaml
cameras:
  - type: rtsp
    url: "rtsp://admin:password@192.168.1.100:554/ch0_0.h264"
    name: "Front Door Camera"
```

Or add at runtime via API:
```bash
curl -X POST http://localhost:8090/cameras \
  -H "Content-Type: application/json" \
  -d '{"url": "rtsp://192.168.1.100:554/stream", "type": "rtsp", "name": "Front Door"}'
```

---

## Cloud Deployment (Fly.io)

Run physical-mcp in the cloud for 24/7 monitoring without keeping your
computer on.

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Deploy
cd physical-mcp
fly launch
fly secrets set \
  REASONING_PROVIDER=google \
  REASONING_API_KEY=your_key \
  TELEGRAM_BOT_TOKEN=your_token \
  TELEGRAM_CHAT_ID=your_chat_id
fly deploy
```

Then add your IP camera:
```bash
curl -X POST https://your-app.fly.dev/cameras \
  -H "Authorization: Bearer YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "rtsp://your-public-ip:554/stream", "type": "rtsp", "name": "Home Camera"}'
```

---

## Troubleshooting

### Camera not found
- **USB camera**: Make sure it's plugged in. Try a different USB port.
- **Mac**: Go to System Settings > Privacy & Security > Camera and enable
  access for your terminal app.
- **Linux**: Add yourself to the video group: `sudo usermod -aG video $USER`
  then log out and back in.

### No alerts received
- Check Telegram: message your bot first (it needs at least one message).
- Check the chat ID: visit `api.telegram.org/botTOKEN/getUpdates`
- Check the rule: `curl http://localhost:8090/rules` — is it enabled?
- Check the scene: `curl http://localhost:8090/scene` — is the AI analyzing?

### AI not analyzing frames
- Run `physical-mcp doctor` for diagnostics
- Check your API key is valid and has credits
- Try a different provider (Google Gemini free tier is a good fallback)

### High API costs
- Increase `cooldown_seconds` on rules (default 60, try 300 for low-priority)
- Use fewer cameras
- Use a cheaper model (Gemini Flash is fast and affordable)

---

## Next Steps

- **Multiple cameras**: Add more cameras to your config for different rooms
- **Multiple rules**: Create rules for different scenarios (pets, packages, etc.)
- **Discord/Slack**: Change notification type to get alerts in Discord or Slack
- **Custom messages**: Use `custom_message` to get specific alert text
- **Templates**: Use `curl http://localhost:8090/templates` to see pre-built rules
