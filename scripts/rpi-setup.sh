#!/usr/bin/env bash
#
# rpi-setup.sh - Raspberry Pi SD Card Auto-Flash Script for physical-mcp
#
# Sets up Raspberry Pi OS Lite + physical-mcp for headless WiFi camera operation
# Usage: sudo ./rpi-setup.sh --ssid "YourWiFi" --password "secret"
#
set -euo pipefail

RPI_OS_URL="https://downloads.raspberrypi.org/raspios_lite_arm64_latest"
WIFI_SSID=""
WIFI_PASSWORD=""
SD_CARD=""
SKIP_DOWNLOAD=false
PI_MODEL="zero2w"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
  echo "Physical MCP - Raspberry Pi SD Card Auto-Flash"
  echo ""
  echo "USAGE: sudo ./rpi-setup.sh --ssid \"SSID\" --password \"PASS\" [--sd-device PATH]"
  echo ""
  echo "OPTIONS:"
  echo "  --ssid SSID          WiFi network name (required)"
  echo "  --password PASS      WiFi password (required)"
  echo "  --sd-device PATH     SD card device (auto-detect if not set)"
  echo "  --skip-download      Use existing OS image in /tmp"
  echo ""
  exit 0
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --ssid) WIFI_SSID="$2"; shift 2;;
    --password) WIFI_PASSWORD="$2"; shift 2;;
    --sd-device) SD_CARD="$2"; shift 2;;
    --skip-download) SKIP_DOWNLOAD=true; shift;;
    -h|--help) usage;;
    *) log_error "Unknown option: $1"; exit 1;;
  esac
done

check_deps() {
  for dep in curl unzip dd; do
    if ! command -v "$dep" &>/dev/null; then
      log_error "Missing: $dep"; exit 1
    fi
  done
}

find_sd_card() {
  if [[ "$OSTYPE" == "darwin"* ]]; then
    diskutil list | grep -E "external"
  else
    lsblk -d -o NAME,SIZE,TYPE | grep disk
  fi
}

select_sd_card() {
  if [[ -n "$SD_CARD" ]] && [[ -e "$SD_CARD" ]]; then
    log_ok "SD card: $SD_CARD"; return 0
  fi
  log_warn "Available drives:"; find_sd_card
  read -rp "SD card device (e.g., /dev/disk2): " SD_CARD
  [[ -e "$SD_CARD" ]] || { log_error "Not found: $SD_CARD"; exit 1; }
  read -rp "Type YES to ERASE $SD_CARD: " confirm
  [[ "$confirm" == "YES" ]] || { log_error "Aborted"; exit 1; }
}

download_os() {
  if [[ "$SKIP_DOWNLOAD" == true ]] && [[ -f /tmp/rpios.img ]]; then return 0; fi
  log_info "Downloading Raspberry Pi OS (~500MB)..."
  curl -L -o /tmp/rpios.zip "$RPI_OS_URL"
  unzip -o /tmp/rpios.zip -d /tmp/
  mv /tmp/*-raspios-*.img /tmp/rpios.img
  log_ok "OS ready"
}

flash_sd() {
  log_info "Flashing $SD_CARD..."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    diskutil unmountDisk "$SD_CARD" 2>/dev/null || true
  else
    umount "${SD_CARD}"* 2>/dev/null || true
  fi
  dd if=/tmp/rpios.img of="$SD_CARD" bs=4m status=progress || \
    dd if=/tmp/rpios.img of="$SD_CARD" bs=4m
  sync
  log_ok "Flash complete"
  sleep 2
}

configure_boot() {
  local boot_part=""
  if [[ "$OSTYPE" == "darwin"* ]]; then
    diskutil mount "${SD_CARD}s1" 2>/dev/null || diskutil mount "$SD_CARD" 2>/dev/null || true
    sleep 1
    boot_part="/Volumes/bootfs"
    [[ -d "$boot_part" ]] || boot_part="/Volumes/boot"
  else
    mkdir -p /mnt/rpi-boot
    mount "${SD_CARD}1" /mnt/rpi-boot 2>/dev/null || mount "${SD_CARD}p1" /mnt/rpi-boot
    boot_part="/mnt/rpi-boot"
  fi

  [[ -d "$boot_part" ]] || { log_error "Boot partition not found"; exit 1; }

  log_info "Enabling SSH..."
  touch "${boot_part}/ssh"

  log_info "Configuring WiFi..."
  cat > "${boot_part}/wpa_supplicant.conf" << EOF
country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
  ssid="$WIFI_SSID"
  psk="$WIFI_PASSWORD"
  key_mgmt=WPA-PSK
}
EOF
  log_ok "WiFi: $WIFI_SSID"

  # Calculate token display (last 8 chars for reference)
  TOKEN_SUFFIX=$(openssl rand -base64 16 | tr -d '=+/' | cut -c1-12)

  log_info "Creating auto-install script..."
  # Create user-data file for cloud-init style first boot ( simpler systemd approach)
  cat > "${boot_part}/user-data" << EOFCLOUD
#cloud-config
package_update: true
packages:
  - python3-pip
  - python3-opencv
runcmd:
  - pip3 install --break-system-packages physical-mcp
  - mkdir -p /home/pi/.physical-mcp
  - |
    cat > /home/pi/.physical-mcp/config.yaml << EOF
server:
  transport: streamable-http
  host: 0.0.0.0
  port: 8400
cameras:
  - id: picam
    name: Raspberry Pi Camera
    enabled: true
    type: usb
    device_index: 0
    width: 1280
    height: 720
vision_api:
  enabled: true
  host: 0.0.0.0
  port: 8090
  auth_token: $(openssl rand -base64 32 | tr -d '=+/' | cut -c1-32)
perception:
  enabled: true
  change_detection:
    enabled: true
    hash_threshold: 8
notifications:
  desktop_enabled: false
EOF
  - chown -R pi:pi /home/pi/.physical-mcp
  - |
    cat > /etc/systemd/system/physical-mcp.service << EOF
[Unit]
Description=Physical MCP AI Vision Provider
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/usr/local/bin/physical-mcp --config /home/pi/.physical-mcp/config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  - systemctl daemon-reload
  - systemctl enable physical-mcp.service
  - systemctl start physical-mcp.service
EOFCLOUD

  log_ok "First-boot installer configured (auth-token-suffix: ${TOKEN_SUFFIX})"
}

main() {
  [[ -z "$WIFI_SSID" || -z "$WIFI_PASSWORD" ]] && usage
  check_deps
  select_sd_card
  download_os
  flash_sd
  configure_boot

  log_ok "\n=== SD card ready! ==="
  log_info "Insert into Pi and power on."
  log_info "After boot (~3min), access at:"
  log_info "  http://physical-mcp.local:8090/dashboard"
}

main
