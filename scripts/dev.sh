#!/bin/bash
# Physical MCP — Debug development build
#
# Builds Flutter debug app, injects backend binary, code signs
# with proper entitlements (camera permission), and launches.
#
# Usage:
#   ./scripts/dev.sh                    # Build and launch
#   ./scripts/dev.sh --rebuild-backend  # Force rebuild backend binary
#   ./scripts/dev.sh --clean            # Clean build everything
#   ./scripts/dev.sh --no-launch        # Build only, don't launch
#
# The app launches as a standalone .app — no terminal needed for the end user.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$PROJECT_ROOT/app"
DIST_DIR="$PROJECT_ROOT/dist"
BACKEND_BIN="$DIST_DIR/physical-mcp-server"
APP_BUNDLE="$APP_DIR/build/macos/Build/Products/Debug/Physical MCP.app"
ENTITLEMENTS="$APP_DIR/macos/Runner/DebugProfile.entitlements"

# Parse flags
REBUILD_BACKEND=false
CLEAN=false
NO_LAUNCH=false
for arg in "$@"; do
  case $arg in
    --rebuild-backend) REBUILD_BACKEND=true ;;
    --clean) CLEAN=true ;;
    --no-launch) NO_LAUNCH=true ;;
  esac
done

echo "======================================"
echo "  Physical MCP — Debug Build"
echo "======================================"
echo ""

# Step 0: Clean if requested
if $CLEAN; then
  echo "=== Cleaning previous builds ==="
  rm -rf "$APP_DIR/build/macos"
  echo "  Cleaned Flutter build cache"
  echo ""
fi

# Step 1: Build backend binary if missing or requested
if [ ! -f "$BACKEND_BIN" ] || $REBUILD_BACKEND; then
  echo "=== Step 1/5: Building backend binary ==="
  "$PROJECT_ROOT/scripts/build-backend.sh"
  echo ""
else
  BSIZE=$(du -sh "$BACKEND_BIN" | cut -f1)
  echo "=== Step 1/5: Backend binary exists ($BSIZE), skipping ==="
  echo "    Use --rebuild-backend to force rebuild"
  echo ""
fi

# Step 2: Build Flutter debug
echo "=== Step 2/5: Building Flutter macOS debug ==="
cd "$APP_DIR"
flutter build macos --debug
echo ""

# Step 3: Kill any previous instance
echo "=== Step 3/5: Stopping previous instances ==="
pkill -f "Physical MCP" 2>/dev/null || true
pkill -f "physical-mcp-server" 2>/dev/null || true
sleep 1
echo "  Done"
echo ""

# Step 4: Inject backend binary into .app Resources
echo "=== Step 4/5: Injecting backend + code signing ==="

if [ ! -d "$APP_BUNDLE" ]; then
  echo "ERROR: App bundle not found at: $APP_BUNDLE"
  exit 1
fi

cp "$BACKEND_BIN" "$APP_BUNDLE/Contents/Resources/physical-mcp-server"
chmod +x "$APP_BUNDLE/Contents/Resources/physical-mcp-server"
echo "  Copied backend binary to Resources/"

# Create entitlements for the embedded backend binary
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

# Sign the whole app with debug entitlements
codesign --force --deep --sign - --entitlements "$ENTITLEMENTS" "$APP_BUNDLE"
echo "  Signed app bundle with debug entitlements"

rm -f "$BACKEND_ENTITLEMENTS"

# Show sizes
APP_SIZE=$(du -sh "$APP_BUNDLE" | cut -f1)
echo "  App bundle: $APP_SIZE"
echo ""

# Step 5: Launch
if $NO_LAUNCH; then
  echo "=== Step 5/5: Build complete (no launch) ==="
  echo "  To launch: open \"$APP_BUNDLE\""
else
  echo "=== Step 5/5: Launching ==="
  open "$APP_BUNDLE"
  echo "  Launched: Physical MCP (Debug)"
  echo ""
  echo "  Logs: Check Console.app or run:"
  echo "    log stream --process 'Physical MCP' --level debug"
fi

echo ""
echo "======================================"
echo "  Done!"
echo "======================================"
