FROM python:3.12-slim

# System deps for headless OpenCV + health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 curl \
    && rm -rf /var/lib/apt/lists/*

# Install physical-mcp with all optional providers
RUN pip install --no-cache-dir physical-mcp[all]

# Config and data directories
RUN mkdir -p /root/.physical-mcp

# Environment variables for cloud deployment
ENV PHYSICAL_MCP_HOST=0.0.0.0 \
    PHYSICAL_MCP_PORT=8400 \
    VISION_API_HOST=0.0.0.0 \
    VISION_API_PORT=8090 \
    REASONING_PROVIDER="" \
    REASONING_API_KEY="" \
    REASONING_MODEL="" \
    REASONING_BASE_URL=""

# Expose Vision API (8090) + MCP server (8400)
EXPOSE 8090 8400

# Health check via Vision API
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8090/health || exit 1

# Run in HTTP mode (cloud-ready, not stdio)
ENTRYPOINT ["physical-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8400"]
