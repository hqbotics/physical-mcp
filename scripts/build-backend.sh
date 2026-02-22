#!/bin/bash
# Build standalone backend binary for embedding in Flutter app.
#
# Compiles physical_mcp.embedded into a single-file PyInstaller binary
# that can be bundled inside the macOS .app (Contents/Resources/).
#
# Usage: ./scripts/build-backend.sh
# Output: dist/physical-mcp-server

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Building Physical MCP embedded backend ==="
echo "Project root: $PROJECT_ROOT"

# Ensure virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
fi

# Activate venv
source .venv/bin/activate

# Install PyInstaller if not present
if ! command -v pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    uv pip install pyinstaller
fi

# Install project in editable mode (if not already)
uv pip install -e "." 2>/dev/null || true

# Use opencv-python-headless for smaller binary (no GUI deps needed)
uv pip install opencv-python-headless 2>/dev/null || true

echo ""
echo "Running PyInstaller..."
echo ""

pyinstaller \
    --onefile \
    --name physical-mcp-server \
    --hidden-import=cv2 \
    --hidden-import=numpy \
    --hidden-import=PIL \
    --hidden-import=PIL.Image \
    --hidden-import=imagehash \
    --hidden-import=aiohttp \
    --hidden-import=aiohttp.web \
    --hidden-import=zeroconf \
    --hidden-import=pydantic \
    --hidden-import=yaml \
    --hidden-import=qrcode \
    --hidden-import=mcp \
    --hidden-import=mcp.server.fastmcp \
    --hidden-import=mcp.server.streamable_http \
    --hidden-import=mcp.types \
    --hidden-import=uvicorn \
    --hidden-import=uvicorn.config \
    --hidden-import=uvicorn.server \
    --hidden-import=starlette \
    --hidden-import=starlette.applications \
    --hidden-import=starlette.routing \
    --hidden-import=starlette.responses \
    --hidden-import=starlette.requests \
    --hidden-import=sse_starlette \
    --hidden-import=anyio \
    --hidden-import=anyio._backends._asyncio \
    --hidden-import=click \
    --hidden-import=httpx \
    --collect-submodules=physical_mcp \
    --collect-submodules=cv2 \
    --collect-submodules=pydantic \
    --collect-submodules=mcp.server \
    --collect-submodules=mcp.shared \
    --collect-submodules=mcp.types \
    --collect-submodules=uvicorn \
    --collect-submodules=starlette \
    --collect-submodules=sse_starlette \
    --collect-submodules=anyio \
    --collect-submodules=httpx \
    --exclude-module=anthropic \
    --exclude-module=openai \
    --exclude-module=google \
    --exclude-module=pyngrok \
    --exclude-module=pynput \
    --exclude-module=tkinter \
    --exclude-module=matplotlib \
    --exclude-module=scipy \
    --exclude-module=pandas \
    --strip \
    --distpath "$PROJECT_ROOT/dist" \
    --workpath "$PROJECT_ROOT/build/pyinstaller" \
    --specpath "$PROJECT_ROOT/build/pyinstaller" \
    src/physical_mcp/embedded.py

BINARY="$PROJECT_ROOT/dist/physical-mcp-server"

if [ -f "$BINARY" ]; then
    chmod +x "$BINARY"
    SIZE=$(du -sh "$BINARY" | cut -f1)
    echo ""
    echo "=== Build successful ==="
    echo "Binary: $BINARY"
    echo "Size:   $SIZE"
    echo ""
    echo "Test with: $BINARY --port 8090 --mcp-port 8400"
else
    echo "ERROR: Binary not found at $BINARY"
    exit 1
fi
