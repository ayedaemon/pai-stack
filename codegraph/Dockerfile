FROM debian:12-slim

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Download codegraph binary for host arch (graph-only mode, no ONNX needed)
# Supports amd64 -> linux-x64 and arm64 -> linux-arm64 (RPi aarch64)
ARG CODEGRAPH_VERSION=v0.20.1
ARG TARGETARCH
RUN set -e; \
    ARCH="${TARGETARCH}"; \
    if [ -z "$ARCH" ]; then ARCH="$(dpkg --print-architecture)"; fi; \
    case "$ARCH" in \
      amd64|x86_64|x64) CG_ARCH="x64" ;; \
      arm64|aarch64) CG_ARCH="arm64" ;; \
      *) echo "unsupported arch $ARCH" && exit 1 ;; \
    esac; \
    echo "codegraph arch $ARCH -> $CG_ARCH"; \
    curl -fLO "https://github.com/codegraph-ai/CodeGraph/releases/download/${CODEGRAPH_VERSION}/codegraph-server-linux-${CG_ARCH}" && \
    chmod +x "codegraph-server-linux-${CG_ARCH}" && \
    mv "codegraph-server-linux-${CG_ARCH}" /usr/local/bin/codegraph-server && \
    codegraph-server --version 2>&1 | head -n 5 || true

# Node.js 22 for the HTTP wrapper
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json server.js ./
RUN npm install --production

EXPOSE 20128

# HTTP wrapper only — each /query spawns one-shot codegraph-server --run-tool (no daemon, no lock contention)
CMD ["node", "server.js"]
