FROM python:3.12-slim

# System deps for headless OpenCV + health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy source and install from local (not PyPI — not published yet)
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir '.[all]'

# Config and data directories
RUN mkdir -p /root/.physical-mcp

# Environment variables for cloud deployment
# Config is built from env vars when no config.yaml exists (see config.py)
ENV PHYSICAL_MCP_HEADLESS=1 \
    PHYSICAL_MCP_HOST=0.0.0.0 \
    PHYSICAL_MCP_PORT=8400 \
    VISION_API_HOST=0.0.0.0 \
    VISION_API_PORT=8090 \
    REASONING_PROVIDER="" \
    REASONING_API_KEY="" \
    REASONING_MODEL="" \
    REASONING_BASE_URL="" \
    # Cloud mode: cameras register via POST /push/register
    CLOUD_MODE="" \
    # Telegram bot for consumer chat interface
    TELEGRAM_BOT_TOKEN="" \
    TELEGRAM_CHAT_ID=""

# Expose Vision API (8090) + MCP server (8400)
EXPOSE 8090 8400

# Health check via Vision API
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8090/health || exit 1

# Run in headless HTTP mode (cloud-ready, no interactive setup)
ENTRYPOINT ["physical-mcp"]
CMD ["--headless", "--transport", "streamable-http", "--port", "8400"]
