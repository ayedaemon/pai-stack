FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    bash \
    jq \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install opencode cli
RUN npm install -g @opencode/cli

# Set workspace as default directory
WORKDIR /opt/data/workspace

# Keep container alive for delegating tasks via docker exec
CMD ["sleep", "infinity"]
