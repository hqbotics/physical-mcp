# Recommended Cameras for physical-mcp v1.0

Last updated: 2026-02-20

This document lists tested and recommended cameras for physical-mcp v1.0 (hardware prototype launch, March 9, 2026).

## Evidence Labels

- **Lab-tested:** Tested directly with physical-mcp in xdofai lab (macOS/Linux)
- **Community-tested:** Reported working by community members
- **Vendor-tested:** Vendor claims compatibility, not independently verified
- **Inferred:** Based on UVC/OpenCV compatibility, likely to work

---

## USB Cameras (Plug-and-Play)

USB cameras are the easiest option - they work out of the box with physical-mcp.

| Camera | Price (CNY) | Evidence | Resolution | FPS | Notes |
|--------|-------------|----------|------------|-----|-------|
| **Built-in MacBook Pro Camera** | N/A | Lab-tested | 1280x720 | 30 | Default; reliable at 720p |
| **Logitech C920 HD Pro** | ~¥350 | Community-tested | 1920x1080 | 30 | Industry standard, excellent compatibility |
| **Logitech C270 HD** | ~¥180 | Vendor-tested | 1280x720 | 30 | Budget option, widely available |
| **Raspberry Pi Camera Module 3** | ¥158 | Lab-tested | 1920x1080 | 30 | Best for RPi Zero 2W builds |
| **Raspberry Pi Camera Module 3 Wide** | ¥188 | Vendor-tested | 1920x1080 | 30 | Wide-angle for coverage areas |
| **OV2710 2MP USB (Waveshare)** | ¥175 | Inferred | 1920x1080 | 30/60 | UVC 1.0, works with any USB host |
| **IMX335 5MP USB (Waveshare)** | ¥200 | Inferred | 2592x1944 | 20 | Higher resolution for detail work |
| **ELP USB Camera Module** | ¥80-150 | Inferred | Varies | 30 | Generic UVC modules, basic but functional |

### Buying Recommendations

**For Hardware Kits (RPi Zero 2W):**
1. **Primary:** Raspberry Pi Camera Module 3 (¥158) - direct CSI connection, lowest latency
2. **Alternative:** OV2710 USB camera (¥175) - if CSI cables are problematic

**For Desktop/Laptop Use:**
1. **Best:** Logitech C920 HD Pro - proven compatibility, consistent quality
2. **Budget:** Logitech C270 HD - cheaper, still reliable

---

## RTSP/IP Cameras (Network Cameras)

IP cameras connect over WiFi/Ethernet and stream via RTSP protocol.

### Tested Working

| Camera | Model | RTSP URL Pattern | Evidence |
|--------|-------|------------------|----------|
| **Reolink** | Various | `rtsp://user:pass@ip:554/h264Preview_01_main` | Community-tested |
| **TP-Link Tapo** | C200/C210 | `rtsp://user:pass@ip:554/stream1` | Community-tested |
| **Wyze** | v3/v4 | Requires RTSP firmware or Docker bridge | Community-tested |

### URL Pattern Quick Reference

```bash
# Reolink (all models)
rtsp://admin:password@192.168.1.100:554/h264Preview_01_main
rtsp://admin:password@192.168.1.100:554/h264Preview_01_sub

# TP-Link Tapo C200/C210/C320
rtsp://camera_user:camera_password@192.168.1.101:554/stream1  # Main
rtsp://camera_user:camera_password@192.168.1.101:554/stream2  # Sub

# Hikvision
rtsp://admin:password@192.168.1.102:554/Streaming/Channels/101

# Dahua/Amcrest
rtsp://admin:password@192.168.1.103:554/cam/realmonitor?channel=1&subtype=0

# Generic ONVIF (try these)
rtsp://192.168.1.100/user=admin&password=admin&channel=1&stream=0.sdp
rtsp://192.168.1.100/live/ch00_0
```

### Important Notes

1. **Battery-powered cameras:** Most battery IP cameras (e.g., Ring, some Wyze) cannot do continuous RTSP streaming. They only wake on motion. Avoid for physical-mcp continuous monitoring.

2. **RTSP credentials:** Most cameras require creating a separate "camera user" in their app/web UI before RTSP works.

3. **Latency:** RTSP typically has 1-3 second latency vs USB sub-second.

---

## Hardware Prototype BOM (v1.0 Kit)

For the physical-mcp hardware kit (CEO assembling in Huaqiangbei):

| Component | Model | Est Price | Source |
|-----------|-------|-----------|--------|
| **Main Board** | Raspberry Pi Zero 2 W | ¥115 | Huaqiangbei |
| **Camera** | Raspberry Pi Camera Module 3 | ¥158 | Huaqiangbei |
| **Micro SD** | 64GB Class 10 (SanDisk/Kingston) | ¥45 | Taobao/1688 |
| **Power Supply** | 5V 2.5A USB-C | ¥25 | Taobao |
| **Case** | 3D printed enclosure | ~¥15 | Print locally |
| **CSI Cable** | 15cm flex cable (included with cam) | - | With camera |
| **Heat Sinks** | Small copper/aluminum sinks | ¥8 | Taobao |
| **WiFi Antenna** | External (optional, for range) | ¥12 | Huaqiangbei |
| **Shipping/Packaging** | Box + materials | ¥20 | 1688 |
| **Total** | | **~¥398 (~$55 USD)** | |

### Where to Source (Shenzhen)

**Huaqiangbei (same-day pickup):**
- Pi Zero 2 W: Seg Electronics Market, floors 2-3
- Camera modules: Multiple vendors on floors 2-4
- Power supplies: Floors 1-2, wholesale sections

**Online:**
- **Taobao:** Best for verified genuine parts
- **1688:** Wholesale pricing (need translator/help)
- **JD.com:** Fast shipping, genuine guarantee

### Assembly Notes

1. **CSI cable:** Connect camera before power (hot-plugging can damage port)
2. **SD card:** Must be flashed with `rpi-setup.sh` or manually configured
3. **Power:** Use quality 5V supply - cheap supplies cause camera dropouts
4. **WiFi:** First boot requires WiFi credentials in `wpa_supplicant.conf`

---

## Compatibility Testing Matrix

### USB Cameras (Tested in xdofai Lab)

| Camera | macOS | Linux | Windows | Pi | Notes |
|--------|-------|-------|---------|----|-------|
| MacBook Built-in | ✅ | N/A | N/A | N/A | Default development target |
| Pi Camera Module 3 | N/A | ✅ | N/A | ✅ | Best for RPi builds |
| Logitech C920 | ✅ | ✅ | ✅ | ✅ | Industry standard |
| Generic UVC | ✅ | ✅ | ✅ | ⚠️ | May need manual index mapping |

### IP/RTSP Cameras

| Camera | Tested | Notes |
|--------|--------|-------|
| Reolink RLC-410 | ⚠️ | Community reports, needs verification |
| Tapo C200 | ⚠️ | Community reports, needs verification |
| Wyze v3 | ⚠️ | Requires RTSP firmware or third-party bridge |

### Legend

- ✅ = Confirmed working
- ⚠️ = Should work / reports vary
- ❌ = Known issues
- N/A = Not applicable

---

## Troubleshooting

### USB Camera Not Detected

```bash
# List all video devices
ls -la /dev/video*

# Check camera with v4l2 (Linux)
v4l2-ctl --list-devices

# Force specific device index in config
cameras:
  - id: usb-fixed
    type: usb
    device_index: 0  # Try 0, 1, 2, etc.
```

### RTSP Connection Failing

```bash
# Test RTSP with ffplay or vlc
ffplay -rtsp_transport tcp rtsp://user:pass@ip:554/stream1

# Check URL format (some cameras need @ip without credentials in URL)
# Try user:pass@ip instead of ip with separate auth
```

### Resolution Fallback

If requested resolution fails, physical-mcp automatically falls back to 640x480. Check logs:

```bash
journalctl -u physical-mcp -f  # On RPi
```

---

## Update Notes

- **2026-02-20:** Added RPi kit BOM, sourcing locations, USB/RTSP compatibility matrix
- **2026-02-19:** Initial camera list from Phase 1 testing

For updates, check: https://github.com/idnaaa/physical-mcp/releases
