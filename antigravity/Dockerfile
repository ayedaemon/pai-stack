FROM python:3.12-slim

# System deps (git handy for the agent; curl/bash for the installer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl bash git ca-certificates && rm -rf /var/lib/apt/lists/*

# Install Antigravity CLI (agy) via the official script
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash \
 && AGY=$(command -v agy || find /root /usr/local -name agy -type f 2>/dev/null | head -1) \
 && ln -sf "$AGY" /usr/local/bin/agy

ENV PATH="/usr/local/bin:${PATH}"
ENV HOME="/home/agy"

# MCP SDK for the wrapper (v2 API: MCPServer from mcp.server.mcpserver)
RUN pip3 install --break-system-packages mcp

WORKDIR /app
COPY mcp_server.py /app/mcp_server.py
COPY seed_settings.json /opt/seed/settings.json

RUN mkdir -p /workspace /home/agy/.gemini/antigravity-cli
VOLUME ["/workspace", "/home/agy/.gemini"]

EXPOSE 8000
ENTRYPOINT []
CMD ["python3", "/app/mcp_server.py"]
