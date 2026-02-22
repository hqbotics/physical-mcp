# Hardware BOM — v1.0 Prototype Kits (20 units)

Bill of Materials for physical-mcp wireless camera prototype kits. For CEO sourcing in Huaqiangbei, Shenzhen.

## Design Goals

1. **Cost <$25 BOM** per unit (excl. assembly)
2. **WiFi-only** — no ethernet, no SDI
3. **USB or CSI camera** — flexible for different use cases
4. **3D-printable enclosure** — snap-fit, no screws
5. **SD card pre-flashed** — plug-and-play

## Component List

### Core Compute (Option A: Raspberry Pi)

| Component | Spec | Qty | Unit (CNY) | Subtotal | Source (Huaqiangbei) |
|-----------|------|-----|------------|----------|---------------------|
| Raspberry Pi Zero 2 W | 1GHz Quad-core, 512MB RAM, WiFi/BT | 20 | ¥120 | ¥2,400 | 赛格广场 3F ( stalls 3C15-3C20) |
| Camera Module v3 | Sony IMX708, 12MP, wide angle | 20 | ¥85 | ¥1,700 | Same stalls |
| Camera Cable | 15cm flex cable (Zero to Camera v3) | 20 | ¥8 | ¥160 | Bundle with camera |
| Micro SD Card 32GB | Class 10, A1-rated | 20 | ¥25 | ¥500 | 华强电子世界 1F |
| USB-C PSU 5V/2.5A | Wall adapter + cable | 20 | ¥22 | ¥440 | 赛格广场 2F power supplies |
| **Subtotal (Pi Option)** | | | **¥260/unit** | **¥5,200** | |

### Alternative Compute (Option B: Orange Pi / cheaper)

| Component | Spec | Qty | Unit (CNY) | Subtotal | Source |
|-----------|------|-----|------------|----------|--------|
| Orange Pi Zero 2 | 1.5GHz H616, 512MB, WiFi | 20 | ¥85 | ¥1,700 | 赛格广场 3F (Orange Pi dealer) |
| USB Camera 1080p | UVC-compliant, wide angle | 20 | ¥45 | ¥900 | 赛格广场 4F cameras |
| Same SD + PSU as above | | 20 | ¥47 | ¥940 | |
| **Subtotal (OPi Option)** | | | **¥177/unit** | **¥3,540** | |

### Enclosure (3D Printed)

| Component | Spec | Qty | Unit (CNY) | Subtotal | Source |
|-----------|------|-----|------------|----------|--------|
| PLA Filament | 1.75mm, 1kg roll | 2 | ¥60 | ¥120 | Taobao (eSUN, Hatchbox) |
| Printing cost | Outsourced to print shop | 20 | ¥15 | ¥300 | 华强北打印店 (Huaqiangbei print shops) |
| **Subtotal (Enclosure)** | | | **¥21/unit** | **¥420** | |

### Packaging / Shipping

| Component | Spec | Qty | Unit (CNY) | Subtotal | Source |
|-----------|------|-----|------------|----------|--------|
| Anti-static bag | 10x15cm | 20 | ¥0.50 | ¥10 | 赛格广场 1F packaging |
| Simple box | 10x10x5cm white box | 20 | ¥2 | ¥40 | Taobao packaging |
| Shipping to warehouse | | 20 | ¥5 | ¥100 | SF Express |
| **Subtotal (Packaging)** | | | **¥7.50/unit** | **¥150** | |

## Total Cost Summary

| Option | BOM per unit | Total 20 units | Notes |
|--------|--------------|----------------|-------|
| **Pi Zero 2 W (recommended)** | ¥288.50 (~$40 USD) | ¥5,770 (~$800 USD) | Better software support |
| **Orange Pi Zero 2** | ¥205.50 (~$28 USD) | ¥4,110 (~$570 USD) | Cheaper, more DIY |

**Target retail:** $49-79 USD per kit (2-3x BOM cost typical for hardware)

## Comparison: Wyze Cam v3 vs physical-mcp kit

| Feature | Wyze Cam v3 | physical-mcp v1 |
|---------|-------------|-----------------|
| Price | $35 retail | ~$40 BOM |
| Cloud dependency | Required for full features | None (local/self-hosted) |
| AI features | Cloud-based | Local + BYO AI key |
| Open source | No | Yes (MIT) |
| Hackable | Limited | Fully open |
| Integrations | Wyze ecosystem | Any MCP/REST client |

## Assembly Steps (per unit)

1. **Print enclosure** (or outsource) — 2 hours print time
2. **Flash SD card** — Use `scripts/rpi-setup.sh`
3. **Assemble** — Snap Pi into case, attach camera, close lid
4. **Test** — Power on, verify `physical-mcp.local` responds
5. **Package** — Anti-static bag + simple box

**Assuming 5 min/unit:** 20 units = 1.7 hours assembly time

## Pre-Flash SD Card Image

The `scripts/rpi-setup.sh` script handles:
1. Download Raspberry Pi OS Lite 64-bit
2. Enable SSH
3. Configure WiFi credentials
4. Install physical-mcp via uv
5. Enable auto-start systemd service
6. Configure mDNS advertisement

## Sourcing Strategy

### Same-Day Pickup (Huaqiangbei)
- Pi Zero 2 W: 赛格广场 3F — ask for "树莓派Zero 2 W 开发板"
- Camera modules: Same floor, stalls with orange Pi cases
- SD cards: 华强电子世界 1F (wholesale)
- Power supplies: 赛格广场 2F (avoid cheapest tier)

### Online (Taobao/1688) for bulk
- Better prices at 50+ units
- Pi Zero 2 W: ~¥110 at 50pcs
- Camera v3: ~¥75 at 50pcs
- 1688 for B2B: search "树莓派Zero2W套装"

### 3D Printing
- Taobao: ¥15-20 per print at print shops
- Self-print: Bambu Lab P1S at lab (if available)
- File: `hardware/enclosure/pi-zero-case.stl` (to be created)

## Risks & Mitigations

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Pi Zero 2 W stock shortage | Medium | Have Orange Pi Zero 2 backup option |
| Camera v3 unavailable | Low | Generic OV5640 USB cams ¥45 as fallback |
| 3D print quality issues | Low | Order 25 prints, keep 5 spares |
| SD card failures | Medium | Buy from reputable vendor (Samsung/Kingston) |
| WiFi range issues | Medium | Document extender/positioning guide |

## Next Revision (v1.1)

- Custom PCB integrating Pi CM4
- Built-in wide-angle lens (no module)
- PoE option for wired installs
- Metal enclosure for outdoor use

---

**Last Updated:** 2026-02-20  
**Sourcing Location:** Huaqiangbei, Shenzhen  
**Budget Allocated:** $5,000 NZD (~¥22,000 CNY, covers ~75 kits at Pi BOM)
