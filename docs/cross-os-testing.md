# Cross-OS Testing Guide — physical-mcp v1.0

This document provides verification steps for physical-mcp across all supported platforms for the family room scenario (multi-user, multi-device, multi-OS).

## Supported Platforms

| Platform | Status | Priority |
|----------|--------|----------|
| macOS | Primary dev platform | HIGHEST |
| Linux | Ubuntu/Debian tested | HIGH |
| Windows | Windows 10/11 | HIGH |
| iOS Safari | Dashboard viewing | HIGH |
| Android Chrome | Dashboard viewing | HIGH |

---

## Test Matrix

### Server-Side Platforms (Runs physical-mcp)

#### macOS
```bash
# Install
pip install physical-mcp

# Setup
physical-mcp setup

# Start server
physical-mcp

# Verify mDNS advertising
dns-sd -B _physical-mcp._tcp local

# Expected: physical-mcp._physical-mcp._tcp.local
```

#### Linux
```bash
# Install dependencies
sudo apt-get install avahi-daemon  # For mDNS support

# Install
pip install physical-mcp

# Setup
physical-mcp setup

# Start server
physical-mcp

# Verify mDNS advertising
avahi-browse -r _physical-mcp._tcp

# Expected: physical-mcp._physical-mcp._tcp.local
```

#### Windows
```powershell
# Install (requires Python 3.10+)
pip install physical-mcp

# Setup
physical-mcp setup

# Start server
physical-mcp

# Note: Bonjour/Apple Print Services recommended for mDNS
```

---

### Client-Side Platforms (Access dashboard)

#### iOS Safari (iPhone/iPad)

1. **mDNS Discovery (when on same WiFi):**
   - Open Safari
   - Navigate to: `http://physical-mcp.local:8090/dashboard`
   - Should load dashboard without typing IP

2. **QR Code Access:**
   - Scan QR code from terminal output
   - Opens dashboard directly

3. **PWA Installation:**
   - Tap Share button → "Add to Home Screen"
   - Verify app icon appears on home screen
   - Launch from icon (should be fullscreen)

4. **Test Features:**
   - Live MJPEG stream (should display without stutter)
   - Scene summary updates
   - Rule toggling

#### Android Chrome

1. **mDNS Discovery (when on same WiFi):**
   - Open Chrome
   - Navigate to: `http://physical-mcp.local:8090/dashboard`
   - Should load dashboard without typing IP

2. **QR Code Access:**
   - Scan QR code from Android camera or Google Lens
   - Opens dashboard directly

3. **PWA Installation:**
   - Chrome menu → "Add to Home screen"
   - Verify icon appears on launcher
   - Launch from icon

4. **Test Features:**
   - Live MJPEG stream (should display without stutter)
   - Scene summary updates
   - Rule toggling

#### macOS Chrome/Safari

1. **Browser Access:**
   - Should support both mDNS (`physical-mcp.local:8090`) and IP
   - MJPEG stream works with anti-buffering headers

2. **Multi-client test:**
   - Open 3+ browser tabs simultaneously
   - All should show live stream

#### Windows Edge/Chrome

1. **Browser Access:**
   - Should support both mDNS and IP access
   - MJPEG stream works with `X-Accel-Buffering: no` header

---

## Family Room Scenario Test Protocol

### Setup (One "Server" Device)
1. physical-mcp installed on macOS/Linux/Windows device
2. Server connected to home WiFi
3. At least one USB or IP camera configured

### Multi-User Access Test

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Server: `physical-mcp` | Starts Vision API at `:8090` |
| 2 | Server: Check terminal | Shows `mDNS: http://physical-mcp.local:8090` |
| 3 | Client A (iPhone): Open Safari → `physical-mcp.local:8090/dashboard` | Loads dashboard |
| 4 | Client B (Android): Open Chrome → same URL | Loads dashboard |
| 5 | Client C (Windows): Open Edge → same URL | Loads dashboard |
| 6 | Server: Check health endpoint | All 3 clients should show in metrics |

### Concurrent Stream Test

```bash
# Server: Run stream concurrency test
.venv/bin/pytest tests/test_vision_api.py::test_stream_supports_three_concurrent_clients -v
```

Expected: All 3 simulated clients receive MJPEG frames.

---

## mDNS/Bonjour Verification Per Platform

### macOS (Built-in Bonjour)

```bash
# Discover services
dns-sd -B _physical-mcp._tcp local

# Resolve specific service
dns-sd -L "physical-mcp" _physical-mcp._tcp local

# Expected output:
# My Awesome MacBook Air.local. can be reached at physical-mcp.local.:8090
```

### Linux (Avahi)

```bash
# Install
sudo apt-get install avahi-utils

# Browse services
avahi-browse -r _physical-mcp._tcp

# Exepected output:
# = eth0 IPv4 physical-mcp _physical-mcp._tcp local
#    hostname = [physical-mcp.local]
#    address = [192.168.x.x]
#    port = [8090]
```

### Windows

```powershell
# Option 1: Bonjour Browser (free download from Apple)
# http://www.tildesoft.com/BonjourBrowser.html

# Option 2: PowerShell with DnsClient (may show mDNS)
Resolve-DnsName -Name "physical-mcp.local" -Type A

# Option 3: Use physical-mcp's built-in doctor command
physical-mcp doctor
```

### iOS/Android

Use Bonjour Discovery apps:
- iOS: "Discovery - DNS-SD Browser" (free)
- Android: "Service Browser" or "Bonjour Browser"

Search for `_physical-mcp._tcp` service type.

---

## Known Platform Differences

| Feature | macOS | Linux | Windows | iOS | Android |
|---------|-------|-------|---------|-----|---------|
| mDNS native | ✓ | needs avahi | needs Bonjour | ✓ | needs app |
| PWA install | ✓ | ✓ | ✓ | ✓ | ✓ |
| MJPEG stream | ✓ | ✓ | ✓ | ✓ | ✓ |
| Clipboard snap | ✓ | ✓ | WSL only | N/A | N/A |

---

## Troubleshooting

### mDNS not working on Linux
```bash
# Check if avahi-daemon is running
sudo systemctl status avahi-daemon

# Start if needed
sudo systemctl start avahi-daemon
sudo systemctl enable avahi-daemon
```

### mDNS not working on Windows
- Install [Bonjour Print Services](https://support.apple.com/kb/DL999) from Apple

### iOS/Android can't access `.local` domain
- Ensure both devices are on same WiFi network (no guest network isolation)
- Check router has mDNS/Bonjour forwarding enabled (many routers do this by default)
- Use IP address as fallback: `http://192.168.x.x:8090`

### MJPEG stream stutters on mobile
- Check `X-Accel-Buffering: no` header is present (verified by automated tests)
- Lower quality/fps in dashboard settings
- Ensure server has sufficient WiFi bandwidth

---

## Automated Cross-OS Tests

Run from repository:

```bash
cd camera-project/physical-mcp

# Platform detection tests
.venv/bin/pytest tests/test_platform.py -v

# Concurrent stream tests  
.venv/bin/pytest tests/test_vision_api.py::test_stream_supports_three_concurrent_clients -v
.venv/bin/pytest tests/test_vision_api.py::test_stream_sets_low_latency_headers -v

# mDNS tests
.venv/bin/pytest tests/test_mdns.py -v
```

---

## Sign-Off Checklist

Before v1.0 release, verify:

- [ ] macOS server → iOS client stream works
- [ ] macOS server → Android client stream works
- [ ] Linux server → iOS client stream works
- [ ] Linux server → Android client stream works
- [ ] Windows server → iOS client stream works
- [ ] Windows server → Android client stream works
- [ ] 3+ concurrent clients on different OS/devices
- [ ] mDNS discovery works on all client platforms
- [ ] PWA installation works on mobile

---

*Document version: v1.0 — 2026-02-20*
