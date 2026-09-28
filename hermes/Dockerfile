FROM nousresearch/hermes-agent:latest

USER root

# Install runtime dependencies (curl + Docker CLI for pai_docker_ops)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin jq && \
    rm -rf /var/lib/apt/lists/*

# Install Mnemosyne memory provider and langfuse SDK
RUN uv pip install --python /opt/hermes/.venv/bin/python mnemosyne-hermes langfuse

# Install pai_tools backends: tree-sitter code intelligence + web extraction.
# tree-sitter is pinned: pai_code_intel targets the 0.7.0 API exactly.
RUN uv pip install --python /opt/hermes/.venv/bin/python "mcp-server-tree-sitter==0.7.0" "trafilatura>=2.0"

# Install Playwright (on-demand browser automation ONLY — Hermes uses it only when
# the user explicitly asks; nothing auto-loads it). Upstream image already sets
# PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright, so install into that path.
RUN uv pip install --python /opt/hermes/.venv/bin/python playwright && \
    /opt/hermes/.venv/bin/python -m playwright install --with-deps chromium && \
    chmod -R a+rX /opt/hermes/.playwright && \
    rm -rf /var/lib/apt/lists/*

# Install Hermes Labyrinth dashboard plugin (pinned to v0.1.3)
RUN git clone https://github.com/stainlu/hermes-labyrinth.git /opt/hermes/plugins/hermes-labyrinth && \
    cd /opt/hermes/plugins/hermes-labyrinth && \
    git checkout v0.1.3 && \
    chown -R 1000:1000 /opt/hermes/plugins/hermes-labyrinth

# Install Compressor plugin (heuristic pre-pass for context compression)
COPY plugins/compressor /opt/hermes/plugins/compressor
RUN chown -R 1000:1000 /opt/hermes/plugins/compressor

# Install pai_tools plugin (native code-intel, research vault, ADR, docker ops)
COPY plugins/pai_tools /opt/hermes/plugins/pai_tools
RUN chown -R 1000:1000 /opt/hermes/plugins/pai_tools

# Install OpenCode v2 (pinned, keyless free-model delegation to Hermes projects)
# Stock installer needs only tar+npm; --no-modify-path keeps shell configs untouched.
ARG OPENCODE_VERSION=2.0.16
RUN curl -fsSL https://opencode.ai/v2/install | bash -s -- --no-modify-path -v ${OPENCODE_VERSION} && \
    /root/.opencode/bin/opencode --version && \
    ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode && \
    chown -R 1000:1000 /root/.opencode

# Delegation assets: global keyless config + allowlist wrapper (no secrets anywhere)
COPY opencode/opencode.json /root/.config/opencode/opencode.json
COPY opencode/opencode-delegate /usr/local/bin/opencode-delegate
RUN chmod +x /usr/local/bin/opencode-delegate && \
    chown 1000:1000 /root/.config/opencode/opencode.json /usr/local/bin/opencode-delegate

# Persist opencode sessions/provider cache on the hermes-data volume (HOME is ephemeral)
ENV XDG_DATA_HOME=/opt/hermes/data/opencode

# Stage bundled dashboard themes + TUI skins (seeded into HERMES_HOME at runtime
# by entrypoint.sh, since the hermes-data volume shadows anything baked
# directly into /opt/hermes/data)
COPY dashboard-themes /opt/hermes/dashboard-themes
RUN chown -R 1000:1000 /opt/hermes/dashboard-themes
COPY skins /opt/hermes/skins
RUN chown -R 1000:1000 /opt/hermes/skins

COPY entrypoint.sh /hermes-entrypoint.sh
RUN chmod +x /hermes-entrypoint.sh

