# Cross-OS Testing Guide — Family Room Scenario

**Goal:** Verify physical-mcp works across all family devices simultaneously.

## Test Matrix

| Device | OS | Browser | mDNS Discovery | Dashboard | MJPEG Stream | Concurrent |
|--------|----|---------|----------------|-----------|--------------|------------|
| iPhone | iOS 17+ | Safari | ✓ | ✓ | ✓ | ✓ |
| iPad | iPadOS | Safari | ✓ | ✓ | ✓ | ✓ |
| Android Phone | Android 12+ | Chrome | ✓ | ✓ | ✓ | ✓ |
| MacBook | macOS 14+ | Safari/Chrome | ✓ | ✓ | ✓ | ✓ |
| Windows PC | Windows 11 | Chrome/Edge | ✓ | ✓ | ✓ | ✓ |
| Linux | Ubuntu 22+ | Firefox/Chrome | ✓ | ✓ | ✓ | ✓ |

## Quick Verification Commands

### 1. Server-Side (run on physical-mcp host)

```bash
# Start server with mDNS announcement
physical-mcp start

# Or run directly (boots Vision API + MCP server)
physical-mcp

# Verify mDNS is advertising
physical-mcp doctor | grep -A2 "mDNS/Bonjour"
# Expected: PASS mDNS/Bonjour: zeroconf installed

# Check LAN IP detection
physical-mcp doctor | grep "LAN IP"
# Expected: Your local IP (e.g., 192.168.1.x)
```

### 2. Client-Side (run on each client device)

#### iOS / iPadOS (Safari)

1. Open Safari
2. Type: `http://physical-mcp.local:8090/dashboard`
3. Expected: Dashboard loads, live video stream appears
4. Add to Home Screen for PWA support

#### Android (Chrome)

1. Open Chrome
2. Type: `http://physical-mcp.local:8090/dashboard`
3. Expected: Dashboard loads, "Add to Home screen" prompt appears

#### macOS (Safari/Chrome)

```bash
# Test mDNS resolution
ping physical-mcp.local
# Expected: Resolves to LAN IP (e.g., 192.168.1.x)

# Test dashboard via mDNS
open http://physical-mcp.local:8090/dashboard

# Test dashboard via IP (fallback)
open http://$(dig +short physical-mcp.local):8090/dashboard
```

#### Windows (Chrome/Edge)

```powershell
# Test mDNS resolution
ping physical-mcp.local

# Open dashboard
start http://physical-mcp.local:8090/dashboard
```

#### Linux

```bash
# Test mDNS resolution (requires avahi/zeroconf)
resolvectl query physical-mcp.local
# or
avahi-resolve -n physical-mcp.local

# Open dashboard
xdg-open http://physical-mcp.local:8090/dashboard
```

## Concurrent Streaming Test

**Scenario:** 3+ family members viewing the same camera simultaneously.

### Server-Side Monitoring

```bash
# Watch active connections (macOS/Linux)
netstat -an | grep 8090 | grep ESTABLISHED | wc -l

# Or using lsof (macOS)
lsof -i :8090 | grep ESTABLISHED | wc -l
```

### Client-Side Test Script

Save and open this HTML on 3+ devices simultaneously:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Concurrent Stream Test</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <h1>Concurrent Stream Test</h1>
    <p>Device: <span id="device"></span></p>
    <p>Start time: <span id="start"></span></p>
    <p>Frames received: <span id="frames">0</span></p>
    <p>Errors: <span id="errors">0</span></p>
    <img src="http://physical-mcp.local:8090/stream" 
         style="width:100%; max-width:640px; border:1px solid #ccc;"
         onload="frameLoaded()" onerror="frameError()">
    <script>
        document.getElementById('device').textContent = navigator.userAgent;
        document.getElementById('start').textContent = new Date().toISOString();
        let frames = 0, errors = 0;
        function frameLoaded() { frames++; document.getElementById('frames').textContent = frames; }
        function frameError() { errors++; document.getElementById('errors').textContent = errors; }
    </script>
</body>
</html>
```

## mDNS Troubleshooting

### Issue: Can't resolve `physical-mcp.local`

**macOS/iOS:**
- mDNS/Bonjour is built-in, should work automatically
- Check: `dns-sd -q physical-mcp.local`

**Windows:**
- Install Bonjour Print Services from Apple
- Or enable mDNS in Chrome (flags: `#enable-mdns`)

**Android:**
- mDNS browser apps available (Discovery, ZeroConf Browser)
- Some Android versions need 3rd-party mDNS resolver

**Linux:**
```bash
# Ubuntu/Debian
sudo apt install avahi-daemon libnss-mdns

# Verify
avahi-resolve -n physical-mcp.local
```

### Issue: Dashboard loads but no video

1. Check auth token (if enabled):
   ```bash
   # URL with token
   http://physical-mcp.local:8090/dashboard?token=YOUR_TOKEN
   ```

2. Check direct stream URL:
   ```
   http://physical-mcp.local:8090/stream?fps=5&quality=60
   ```

3. Verify CORS headers (for cross-origin requests)

### Issue: High latency / buffering

The server sets these anti-buffering headers:
- `Cache-Control: no-cache, no-store`
- `Pragma: no-cache`
- `X-Accel-Buffering: no`

If using a reverse proxy (nginx), verify:
```nginx
location /stream {
    proxy_pass http://localhost:8090;
    proxy_buffering off;
    proxy_cache off;
}
```

## Performance Baseline

With concurrent clients on typical home WiFi:

| Clients | CPU Usage | Memory | Latency |
|---------|-----------|--------|---------|
| 1 | 15% | 80MB | <100ms |
| 3 | 25% | 120MB | <200ms |
| 5 | 40% | 200MB | <500ms |
| 10+ | 70%+ | 350MB+ | 1-2s |

**Note:** MJPEG streams generate ~5-15 Mbps per client at 720p/5fps.

## Automated Cross-OS Test

Run the doctor command to verify cross-OS readiness:

```bash
physical-mcp doctor
```

This outputs a verification checklist including:
- Platform detection (macOS, Windows, Linux)
- LAN IP detection (for cross-device access)
- mDNS/Bonjour service readiness
- Cross-device LAN binding (iOS/Android compatibility)
