FROM python:3.12-slim

# System deps (git is handy for the agent; curl/bash for the installer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl bash git ca-certificates && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI (official script, no Node.js required)
RUN curl -fsSL https://opencode.ai/install | bash \
 && OP=$(command -v opencode || find /root /usr/local -name opencode -type f 2>/dev/null | head -1) \
 && ln -sf "$OP" /usr/local/bin/opencode

ENV PATH="/usr/local/bin:${PATH}"

# MCP SDK for the wrapper (v2 API: MCPServer from mcp.server.mcpserver)
RUN pip3 install --break-system-packages mcp

WORKDIR /app
COPY mcp_server.py /app/mcp_server.py

RUN mkdir -p /workspace
VOLUME ["/workspace"]

EXPOSE 8001
ENTRYPOINT []
CMD ["python3", "/app/mcp_server.py"]
