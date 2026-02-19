# Recommended Cameras (v1.0 Software-Only Launch)

This page lists camera compatibility guidance for physical-mcp v1.0.

## Evidence labels
- **Lab-tested (macOS):** directly tested with OpenCV in this repo runtime.
- **Vendor-claimed:** explicit OS/protocol claim from vendor page.
- **Framework-inferred:** UVC + OpenCV portability is likely, but not directly bench-tested in this lab on every OS.

## USB recommendations

| Camera / Path | Price (CNY) | Evidence label | Observed profile behavior | Notes |
|---|---:|---|---|---|
| Device index 1 (external UVC in lab) | N/A | Lab-tested (macOS) | 1280x720 stable, 1920x1080 stable; 0% fallback in recent profile-fidelity run | Best default path in current lab |
| Device index 0 (integrated camera in lab) | N/A | Lab-tested (macOS) | 1280x720 mostly stable (minor fallback), 1920x1080 not reliable in this host path | Use 1280x720 with caveat |
| OV2710 2MP USB Camera (A) | ¥174.73 | Vendor-claimed (Windows/Linux) + Framework-inferred (macOS) | Vendor advertises UVC + MJPEG/YUY2, 1080p class | https://www.waveshare.net/shop/OV2710-2MP-USB-Camera-A.htm |
| IMX335 5MP USB Camera (A) | ¥199.98 | Framework-inferred + Vendor UVC 1.0 claim | Vendor page: UVC 1.0, 2592x1944 up to 20fps, 1080p30 support | https://www.waveshare.net/shop/IMX335-5MP-USB-Camera-A.htm |
| OV5640 5MP USB Camera (B) | ¥144.43 | Framework-inferred (pending format alias validation) | Vendor uses `YUV422` wording; use with format caveat until alias confirmation | https://www.waveshare.net/shop/OV5640-5MP-USB-Camera-B.htm |

## RTSP/IP guidance (for OpenCV URL capture)

### Reolink
- URL pattern: `rtsp://<user>:<pass>@<ip>/Preview_<channel>_<main|sub>`
- Default port: 554
- Source: https://support.reolink.com/hc/en-us/articles/900000630706-Introduction-to-RTSP/

### TP-Link Tapo
- URL pattern examples: `rtsp://<ip>/stream1`, `rtsp://<ip>/stream2`
- Ports: RTSP 554, ONVIF 2020
- Important caveat: most battery models do not support continuous RTSP unless hardwired/always-on conditions are met.
- Source: https://www.tp-link.com/us/support/faq/2680/

### Hikvision / Dahua / Amcrest (common patterns)
- Hikvision: `/streaming/channels/101` (main), `/102` (sub)
- Dahua/Amcrest: `/cam/realmonitor?channel=1&subtype=0` (main), subtype 1/2/3 for lower streams
- Source: https://docs.frigate.video/configuration/camera_specific/

## Current known limitations
1. macOS AVFoundation backend may not expose reliable FOURCC metadata (`CAP_PROP_FOURCC` can return 0x00000000).
2. Use **observed profile stats** (actual resolution/fallback rate) as source of truth, not only requested profile settings.
3. RTSP external smoke-test in this runtime failed to open; still need one in-lab IP camera success row for full launch docs confidence.
