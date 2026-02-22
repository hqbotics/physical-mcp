# Family Room Quickstart Guide

Set up physical-mcp for multiple family members on different devices and operating systems.

## What This Covers

- One physical-mcp server on a Raspberry Pi or dedicated machine
- Multiple family members accessing from different devices (iOS, Android, Windows, macOS)
- Zero-config discovery via mDNS (physical-mcp.local)
- Concurrent access for 3+ users without performance degradation

## Hardware Requirements

### Server (One per household)
- **Raspberry Pi Zero 2 W** ($15) — minimum viable
- **Raspberry Pi 4/5** ($35-55) — recommended for 3+ concurrent users
- Power supply + SD card (32GB) + Camera module

### Family Devices (Each user)
- iPhone/iPad (Safari)
- Android phone/tablet (Chrome)
- Windows laptop
- macOS laptop
- Any browser with camera access

## 5-Minute Setup

### Step 1: Flash SD Card

```bash
git clone https://github.com/idnaaa/physical-mcp.git
cd physical-mcp/scripts
sudo ./rpi-setup.sh --ssid "YourWiFi" --password "WiFiPassword" --sd-device /dev/disk2
```

Insert the SD card into your Pi and power on.

### Step 2: Access the Dashboard

After ~2 minutes, any family member can access:

```
http://physical-mcp.local:8090/dashboard
```

No IP address needed — mDNS handles discovery automatically.

**Note:** Some Android devices need the [Bonjour Browser app](https://play.google.com/store/apps/details?id=de.wellenvogel.bonjourbrowser) for mDNS support, OR use the IP address directly.

### Step 3: Share Access

Each family member gets the same URL. The server handles concurrent connections.

For iOS/Android home screen shortcuts:
1. Open `http://physical-mcp.local:8090/dashboard` in Safari/Chrome
2. Tap Share → "Add to Home Screen"
3. Now it's a " native app" on their phone

## Multi-User Access Patterns

### View-Only Mode (default)
All family members can:
- View live camera feed
- Browse recent captures
- See scene summaries
- Receive alerts

### Admin Mode (auth token)
The setup generates an auth token for privileged operations:

```bash
# On the Pi
physical-mcp status  # shows the auth token (masked)
```

Use `?token=YOUR_TOKEN` in the URL for admin access.

## Cross-Device Compatibility

| Device | Browser | Features | Notes |
|--------|---------|----------|-------|
| iPhone | Safari | Full PWA support | Add to Home Screen works |
| iPad | Safari | Full PWA support | Dashboard scales to tablet |
| Android | Chrome | Full support | mDNS may need app helper |
| Windows | Edge/Chrome | Full support | Can pin to taskbar |
| macOS | Safari/Chrome | Full support | Native Bonjour mDNS |
| Smart TV | Browser | View only | MJPEG stream compatible |

## Performance Expectations

| Pi Model | Concurrent Users | CPU Load | Notes |
|----------|----------------|----------|-------|
| Zero 2 W | 2-3 | 60-80% | OK for small families |
| Pi 4 (2GB) | 3-5 | 40-60% | Recommended |
| Pi 5 (4GB) | 5-10 | 30-50% | Power user setup |

## Troubleshooting

### "Cannot connect to physical-mcp.local"

**Fix:** Use IP address instead:
```bash
# On your Pi
hostname -I  # shows IP like 192.168.1.45
# Use: http://192.168.1.45:8090/dashboard
```

### "Stream lags with multiple viewers"

**Fix:** Reduce frame rate on the server:
```bash
# Edit config
nano ~/.physical-mcp/config.yaml
# Change: capture_fps: 1  (from 2)
# Restart: sudo systemctl restart physical-mcp
```

### "Android doesn't find .local address"

**Fix:** Install Fing app or use IP directly.

## Security Considerations

1. **LAN-only by default** — The server binds to your local network
2. **No cloud dependency** — All processing stays local
3. **Auth token** — Keep the dashboard token private (admin only)
4. **HTTPS tunnel** — Only needed for ChatGPT; family room uses HTTP on LAN

## Advanced: Per-User Limits

To add basic per-user rate limiting (optional):

```yaml
# ~/.physical-mcp/config.yaml
vision_api:
  rate_limit:
    enabled: true
    requests_per_minute: 60
    burst: 10
```

## Next Steps

- Set up [ChatGPT integration](quickstart-chatgpt.md) for voice commands
- Enable [mobile notifications](../README.md) via ntfy.sh
- Add [watch rules](quickstart-60-second-checklist-v1.md) for motion alerts

## Huaqiangbei Shopping List (Shenzhen)

| Component | Store | Est. Price (CNY) |
|-----------|-------|-----------------|
| Pi Zero 2 W | 赛格广场 3F | ¥120 |
| Camera Module v3 | 赛格广场 3F | ¥85 |
| 32GB SD Card | 华强电子世界 1F | ¥35 |
| 5V/2.5A USB-C PSU | 赛格广场 2F | ¥25 |
| 3D-printed case | Taobao/1688 | ¥15-30 |
| **Total** | | **~¥280-300** |

Ask for "树莓派 Zero 2 W 全套" (full Raspberry Pi Zero 2 W kit).
