#!/usr/bin/env bash
# E2E Local Camera Test — HQB-17
# Run from Terminal.app (needs camera permission)
#
# Tests: USB camera → physical-mcp → Gemini Flash → Rule eval → Telegram alert
#
# Usage: cd ~/Desktop/physical-mcp && bash scripts/e2e-local-test.sh

set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".venv/bin"
API="http://127.0.0.1:8090"
TIMEOUT=120

echo "=== Physical-MCP Local E2E Test ==="
echo "Camera: USB Decxin (usb:0)"
echo "Provider: Gemini Flash via OpenRouter"
echo "Notification: Telegram"
echo ""

# 1. Quick camera check
echo "[1/6] Checking camera access..."
$VENV/python -c "
import cv2
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print('FAIL: Camera not accessible. Grant Terminal camera permission.')
    exit(1)
ret, frame = cap.read()
cap.release()
if not ret:
    print('FAIL: Camera opened but no frame')
    exit(1)
h, w = frame.shape[:2]
print(f'OK: Camera 0 = {w}x{h}')
"

# 2. Start server in background (config.yaml has transport/host/port)
echo "[2/6] Starting physical-mcp server..."
$VENV/python -m physical_mcp > /tmp/physical-mcp-e2e.log 2>&1 &
SERVER_PID=$!
echo "  PID: $SERVER_PID (log: /tmp/physical-mcp-e2e.log)"
sleep 5

# Wait for Vision API
echo "[3/6] Waiting for Vision API..."
READY=0
for i in $(seq 1 30); do
    if curl -s "$API/health" > /dev/null 2>&1; then
        echo "  Vision API ready"
        READY=1
        break
    fi
    sleep 1
    printf "  waiting... (%ds)\n" "$i"
done
if [ "$READY" = "0" ]; then
    echo "FAIL: Vision API never came up. Server log:"
    tail -20 /tmp/physical-mcp-e2e.log
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

# 3. Check camera is streaming
echo "[4/6] Verifying camera feed..."
HEALTH=$(curl -s "$API/health")
echo "  Health: $HEALTH"

# Grab a frame
HTTP_CODE=$(curl -s -o /tmp/e2e-frame.jpg -w "%{http_code}" "$API/frame")
if [ "$HTTP_CODE" = "200" ]; then
    SIZE=$(wc -c < /tmp/e2e-frame.jpg)
    echo "  Frame captured: ${SIZE} bytes"
else
    echo "  WARN: Frame endpoint returned $HTTP_CODE"
fi

# 4. Create a watch rule
echo "[5/6] Creating watch rule: 'Person at Desk'..."
RULE_RESP=$(curl -s -X POST "$API/rules" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Person at Desk",
        "condition": "A person is visible sitting at or near a desk or table",
        "priority": "high",
        "notification_type": "telegram",
        "cooldown_seconds": 30
    }')
echo "  Rule: $RULE_RESP"

# 5. Wait for analysis + alert
echo "[6/6] Waiting for Gemini analysis + Telegram alert (up to ${TIMEOUT}s)..."
echo "  (Sit in front of the camera so the AI detects you)"
echo ""

START=$(date +%s)
while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    if [ $ELAPSED -gt $TIMEOUT ]; then
        echo "TIMEOUT: No alert after ${TIMEOUT}s"
        break
    fi

    # Check scene
    SCENE=$(curl -s "$API/scene")
    SUMMARY=$(echo "$SCENE" | python3 -c "import sys,json; d=json.load(sys.stdin); cams=d.get('cameras',{}); print(list(cams.values())[0].get('summary','') if cams else '')" 2>/dev/null || echo "")
    if [ -n "$SUMMARY" ]; then
        echo "  [${ELAPSED}s] Scene: $SUMMARY"
    fi

    # Check alerts
    ALERTS=$(curl -s "$API/alerts")
    ALERT_COUNT=$(echo "$ALERTS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else len(d.get('alerts',[])))" 2>/dev/null || echo "0")
    if [ "$ALERT_COUNT" != "0" ] && [ "$ALERT_COUNT" != "" ]; then
        echo ""
        echo "=== ALERT FIRED! ==="
        echo "$ALERTS" | python3 -m json.tool 2>/dev/null || echo "$ALERTS"
        echo ""
        echo "SUCCESS: Full E2E pipeline working!"
        echo "  Camera → physical-mcp → Gemini Flash → Rule eval → Telegram"
        break
    fi

    sleep 5
done

# Cleanup
echo ""
echo "Stopping server (PID $SERVER_PID)..."
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true
echo "Done."
