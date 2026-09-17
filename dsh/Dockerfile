FROM node:22-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl python3 python3-pip git build-essential socat && \
    rm -rf /var/lib/apt/lists/*

# Install uv for python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install mnemosyne CLI
RUN uv tool install mnemosyne-memory

WORKDIR /app

# Initialize npm and install DeepSeek Harness
RUN npm init -y && \
    npm install -g pnpm && \
    npm install @deepseek-ai/dsh @deepseek-ai/dsh-mcp-client

COPY settings.yaml /root/.dsh/settings.yaml

# Install the plugins into the web profile at build time
RUN npx @deepseek-ai/dsh plugin --profile web add @deepseek-ai/dsh-mcp-client && \
    npx @deepseek-ai/dsh plugin --profile web add github:rebron1900/dsh-mnemosyne

# Data directory for Mnemosyne SQLite
ENV MNEMOSYNE_DATA_DIR=/opt/dsh/data/mnemosyne/data

CMD ["sh", "-c", "socat TCP-LISTEN:9119,fork,bind=0.0.0.0 TCP:127.0.0.1:9121 & exec npx @deepseek-ai/dsh web --host 127.0.0.1 --port 9121"]
