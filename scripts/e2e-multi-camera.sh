#!/usr/bin/env bash
# Multi-Camera E2E Test — HQB-33
# Run from Terminal.app (needs camera permission)
#
# Tests: Decxin USB (index 0) + MacBook FaceTime (index 1) simultaneously
#
# Usage: cd ~/Desktop/physical-mcp && bash scripts/e2e-multi-camera.sh

set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".venv/bin"
API="http://127.0.0.1:8090"

echo "=== Physical-MCP Multi-Camera Test ==="
echo ""

# 1. Detect both cameras
echo "[1/5] Detecting cameras..."
$VENV/python -c "
import cv2
found = 0
for i in range(4):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        ret, frame = cap.read()
        if ret:
            h, w = frame.shape[:2]
            print(f'  Camera index {i}: {w}x{h} — OK')
            found += 1
        cap.release()
if found < 2:
    print(f'WARNING: Only {found} camera(s) found. Need 2 for multi-camera test.')
    print('Make sure USB camera is plugged in.')
else:
    print(f'  {found} cameras detected')
"

# 2. Enable both cameras in config
echo "[2/5] Enabling both cameras in config..."
$VENV/python -c "
import yaml
with open('$HOME/.physical-mcp/config.yaml') as f:
    cfg = yaml.safe_load(f)
for cam in cfg.get('cameras', []):
    cam['enabled'] = True
    print(f'  Enabled: {cam[\"id\"]} ({cam.get(\"name\", \"\")})')
with open('$HOME/.physical-mcp/config.yaml', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('  Config updated')
"

# 3. Start server
echo "[3/5] Starting physical-mcp server..."
$VENV/python -m physical_mcp > /tmp/physical-mcp-multi.log 2>&1 &
SERVER_PID=$!
echo "  PID: $SERVER_PID (log: /tmp/physical-mcp-multi.log)"
sleep 5

# Wait for API
READY=0
for i in $(seq 1 30); do
    if curl -s "$API/health" > /dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done
if [ "$READY" = "0" ]; then
    echo "FAIL: Vision API never came up."
    tail -20 /tmp/physical-mcp-multi.log
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi
echo "  Vision API ready"

# 4. Check both cameras are streaming
echo "[4/5] Checking camera health..."
HEALTH=$(curl -s "$API/health")
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

# Check cameras endpoint
echo ""
echo "  Cameras list:"
CAMERAS=$(curl -s "$API/cameras")
echo "$CAMERAS" | python3 -m json.tool 2>/dev/null || echo "$CAMERAS"

# Grab frames from each camera
echo ""
for cam_id in "usb:0" "usb:1"; do
    HTTP_CODE=$(curl -s -o "/tmp/e2e-${cam_id//:/}.jpg" -w "%{http_code}" "$API/frame/${cam_id}")
    if [ "$HTTP_CODE" = "200" ]; then
        SIZE=$(wc -c < "/tmp/e2e-${cam_id//:/}.jpg")
        echo "  Frame ${cam_id}: ${SIZE} bytes — OK"
    else
        echo "  Frame ${cam_id}: HTTP ${HTTP_CODE} — FAIL"
    fi
done

# 5. Create rules and test
echo "[5/5] Creating rules for both cameras..."
for cam_id in "usb:0" "usb:1"; do
    RULE=$(curl -s -X POST "$API/rules" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"Person on ${cam_id}\",
            \"condition\": \"A person is visible\",
            \"camera_id\": \"${cam_id}\",
            \"priority\": \"high\",
            \"notification_type\": \"local\",
            \"cooldown_seconds\": 60
        }")
    echo "  Rule for ${cam_id}: $(echo "$RULE" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("name","?"))' 2>/dev/null)"
done

cleanup() {
    echo ""
    echo "Cleaning up..."
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    # Restore MacBook camera to disabled
    $VENV/python -c "
import yaml
with open('$HOME/.physical-mcp/config.yaml') as f:
    cfg = yaml.safe_load(f)
for cam in cfg.get('cameras', []):
    if cam.get('id') == 'usb:1':
        cam['enabled'] = False
with open('$HOME/.physical-mcp/config.yaml', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('  MacBook camera disabled in config')
" 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

echo ""
echo "Server running with both cameras. Check:"
echo "  Dashboard: http://127.0.0.1:8090/dashboard"
echo "  Health:    curl $API/health"
echo "  Scene:     curl $API/scene"
echo "  Log:       tail -f /tmp/physical-mcp-multi.log"
echo ""
echo "Press Ctrl+C to stop..."
wait $SERVER_PID
