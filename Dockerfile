FROM python:3.12-slim

# Install system deps for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Install physical-mcp with all optional providers
RUN pip install --no-cache-dir physical-mcp[all]

# Default config location
RUN mkdir -p /root/.physical-mcp

# Vision API port
EXPOSE 8462

# MCP stdio mode by default; override CMD for Vision API
ENTRYPOINT ["physical-mcp"]
