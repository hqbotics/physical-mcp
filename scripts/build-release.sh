#!/bin/bash
# Build a complete Physical MCP release for macOS.
#
# This script:
# 1. Builds the PyInstaller backend binary
# 2. Builds the Flutter macOS release app
# 3. Injects the backend binary into the .app bundle
# 4. Code signs everything (ad-hoc)
# 5. Creates a DMG for distribution
#
# Usage: ./scripts/build-release.sh
# Output: dist/PhysicalMCP-YYYYMMDD.dmg

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$PROJECT_ROOT/app"
DIST_DIR="$PROJECT_ROOT/dist"

echo "============================================"
echo "  Physical MCP — macOS Release Build"
echo "============================================"
echo ""

# ── Step 1: Build backend binary ──────────────────────
echo "=== Step 1/6: Building backend binary ==="
"$PROJECT_ROOT/scripts/build-backend.sh"

BACKEND_BIN="$DIST_DIR/physical-mcp-server"
if [ ! -f "$BACKEND_BIN" ]; then
    echo "ERROR: Backend binary not found"
    exit 1
fi
echo ""

# ── Step 2: Build Flutter macOS release ───────────────
echo "=== Step 2/6: Building Flutter macOS release ==="
cd "$APP_DIR"
flutter build macos --release
echo ""

# ── Step 3: Inject backend binary into .app bundle ────
echo "=== Step 3/6: Injecting backend binary ==="
APP_BUNDLE="$APP_DIR/build/macos/Build/Products/Release/Physical MCP.app"

if [ ! -d "$APP_BUNDLE" ]; then
    echo "ERROR: App bundle not found at: $APP_BUNDLE"
    exit 1
fi

cp "$BACKEND_BIN" "$APP_BUNDLE/Contents/Resources/physical-mcp-server"
chmod +x "$APP_BUNDLE/Contents/Resources/physical-mcp-server"
echo "Injected backend binary into: $APP_BUNDLE/Contents/Resources/"
echo ""

# ── Step 4: Code sign (ad-hoc, with entitlements) ─────
echo "=== Step 4/6: Code signing ==="

# Create entitlements for the embedded backend binary (camera + network)
BACKEND_ENTITLEMENTS=$(mktemp)
cat > "$BACKEND_ENTITLEMENTS" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>com.apple.security.device.camera</key>
	<true/>
	<key>com.apple.security.network.server</key>
	<true/>
	<key>com.apple.security.network.client</key>
	<true/>
</dict>
</plist>
PLIST

# Sign the embedded binary with camera entitlements
codesign --force --sign - --entitlements "$BACKEND_ENTITLEMENTS" "$APP_BUNDLE/Contents/Resources/physical-mcp-server"
echo "  Signed backend binary with camera entitlements"

# Sign the whole app with release entitlements
codesign --force --deep --sign - --entitlements "$APP_DIR/macos/Runner/Release.entitlements" "$APP_BUNDLE"
echo "  Signed app bundle with release entitlements"

rm -f "$BACKEND_ENTITLEMENTS"
echo ""

# ── Step 5: Create DMG ───────────────────────────────
echo "=== Step 5/6: Creating DMG ==="
mkdir -p "$DIST_DIR"
DATE=$(date +%Y%m%d)
DMG_NAME="PhysicalMCP-${DATE}.dmg"
DMG_PATH="$DIST_DIR/$DMG_NAME"

# Remove old DMG if exists
rm -f "$DMG_PATH"

# Create DMG
hdiutil create \
    -volname "Physical MCP" \
    -srcfolder "$APP_BUNDLE" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

echo ""

# ── Step 6: Summary ──────────────────────────────────
echo "=== Step 6/6: Build complete! ==="
echo ""

APP_SIZE=$(du -sh "$APP_BUNDLE" | cut -f1)
DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
BACKEND_SIZE=$(du -sh "$APP_BUNDLE/Contents/Resources/physical-mcp-server" | cut -f1)

echo "  App bundle:     $APP_SIZE"
echo "  Backend binary: $BACKEND_SIZE"
echo "  DMG:            $DMG_SIZE"
echo ""
echo "  DMG path: $DMG_PATH"
echo ""
echo "  To test:"
echo "    open \"$DMG_PATH\""
echo "    # Drag to Applications, then open"
echo ""
echo "  For GitHub release:"
echo "    gh release create v1.0.0 \"$DMG_PATH\" --title 'v1.0.0'"
echo ""
echo "============================================"
echo "  Done!"
echo "============================================"
