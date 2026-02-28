#!/bin/bash
# Install Physical MCP relay agent as a systemd service.
# Run on the LuckFox Pico Mini (or any Linux board).
#
# Usage:
#   sudo bash install.sh

set -e

RELAY_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="physical-mcp-relay"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Physical MCP Relay Agent Installer"
echo "==================================="
echo "Relay dir: ${RELAY_DIR}"

# Install Python dependencies
echo "Installing dependencies..."
pip3 install -r "${RELAY_DIR}/requirements.txt" --break-system-packages 2>/dev/null \
    || pip3 install -r "${RELAY_DIR}/requirements.txt"

# Create systemd service
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=Physical MCP Relay Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${RELAY_DIR}
ExecStart=/usr/bin/python3 ${RELAY_DIR}/relay_agent.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Resource limits for embedded boards
MemoryMax=128M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
EOF

# Create provisioning service (runs once on first boot)
PROVISION_SERVICE="/etc/systemd/system/${SERVICE_NAME}-provision.service"
cat > "${PROVISION_SERVICE}" << EOF
[Unit]
Description=Physical MCP WiFi Provisioning
Before=${SERVICE_NAME}.service
ConditionPathExists=!${RELAY_DIR}/config.json

[Service]
Type=oneshot
WorkingDirectory=${RELAY_DIR}
ExecStart=/usr/bin/python3 ${RELAY_DIR}/wifi_provision.py
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl enable "${SERVICE_NAME}-provision"

echo ""
echo "Installed! Services:"
echo "  ${SERVICE_NAME}            — relay agent (auto-start after provisioning)"
echo "  ${SERVICE_NAME}-provision  — WiFi setup (first boot only)"
echo ""

# Check if already provisioned
if [ -f "${RELAY_DIR}/config.json" ]; then
    echo "Config found — starting relay agent..."
    systemctl start "${SERVICE_NAME}"
    echo "Status: $(systemctl is-active ${SERVICE_NAME})"
else
    echo "No config.json found — starting WiFi provisioning..."
    echo "Connect to the PhysicalMCP-XXXX WiFi and open http://192.168.4.1"
    systemctl start "${SERVICE_NAME}-provision"
fi
