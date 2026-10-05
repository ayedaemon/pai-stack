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

# Install pai_tools backend: web extraction for pai_notebook_ops.
# `pai_code_intel` (and its mcp-server-tree-sitter dep) was removed 2026-10-04 —
# code intelligence is now provided by a dedicated lightweight tool.
RUN uv pip install --python /opt/hermes/.venv/bin/python "trafilatura>=2.0"

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

# Install hermes-memory-ui (read-only memory inspector dashboard tab, Mnemosyne-aware)
# Pinned to catalog-reviewed commit 9472bed (v0.6.0, Sep-15-2026)
RUN git clone https://github.com/xraysight/hermes-memory-ui.git /opt/hermes/plugins/hermes-memory-ui && \
    cd /opt/hermes/plugins/hermes-memory-ui && \
    git checkout 9472bed7e20a51ac4f6c48f882bd9f80ea54d4ee && \
    chown -R 1000:1000 /opt/hermes/plugins/hermes-memory-ui

# Install prompt-optimizer (model-aware prompt rewriting + /prompt-insights)
# Pinned to catalog-reviewed commit e83eba9 (v1.0.0, Sep-19-2026)
# NOTE: upstream defaults to mode=auto (extra LLM call per turn). We patch the
# baked default to "off" so the plugin loads but stays inert until the user
# opts in via `/prompt-optimizer auto` (see user decision Sep-30-2026).
RUN git clone https://github.com/Sahil-SS9/hermes-multichannel-prompt-optimizer.git /opt/hermes/plugins/prompt-optimizer && \
    cd /opt/hermes/plugins/prompt-optimizer && \
    git checkout e83eba9a8e102ed255a5bfd20cc88ea50e3af28f && \
    sed -i 's/^_DEFAULT_MODE = "auto"/_DEFAULT_MODE = "off"/' __init__.py && \
    grep -q '^_DEFAULT_MODE = "off"' __init__.py && \
    chown -R 1000:1000 /opt/hermes/plugins/prompt-optimizer

# Install next-prompt (Desktop composer suggestion pill, 1x max_tokens=100 call/turn)
# Pinned to catalog-reviewed commit eff647b (v0.3.0, Sep-28-2026); HEAD has
# moved on (ec58f9b) but only eff647b is catalog-reviewed.
RUN git clone https://github.com/soymarketing/hermes-plugin-next-prompt.git /opt/hermes/plugins/next-prompt && \
    cd /opt/hermes/plugins/next-prompt && \
    git checkout eff647b44fc81153f5220d505e5f8a5c642330e8 && \
    chown -R 1000:1000 /opt/hermes/plugins/next-prompt

# Optional prompt-optimizer dependency: accurate 97-language detection.
# Without it the plugin falls back to a Unicode-range heuristic.
RUN uv pip install --python /opt/hermes/.venv/bin/python langid

# Install Compressor plugin (heuristic pre-pass for context compression)
COPY plugins/compressor /opt/hermes/plugins/compressor
RUN chown -R 1000:1000 /opt/hermes/plugins/compressor

# Install pai_tools plugin (native research vault, ADR, docker ops, OpenDesign bridge)
COPY plugins/pai_tools /opt/hermes/plugins/pai_tools
RUN chown -R 1000:1000 /opt/hermes/plugins/pai_tools

# Install pai_terrain_ops plugin (code intel via the optional `terrain` profile).
# Its check_fn probes http://terrain:7878/healthz and hides the tool when that
# service is not running, so it is safe to bake in unconditionally.
COPY plugins/pai_terrain_ops /opt/hermes/plugins/pai_terrain_ops
RUN chown -R 1000:1000 /opt/hermes/plugins/pai_terrain_ops

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

# Fetch the default pet sprite at build time (gallery download, no volume
# interaction — HERMES_HOME points at throwaway staging). Seeded into
# HERMES_HOME at runtime by entrypoint.sh (same volume-shadowing reason).
RUN HERMES_HOME=/tmp/petseed /opt/hermes/bin/hermes pets install pixel-black-cat && \
    mkdir -p /opt/hermes/pets-seed && \
    cp -r /tmp/petseed/pets/pixel-black-cat /opt/hermes/pets-seed/ && \
    rm -rf /tmp/petseed && \
    chown -R 1000:1000 /opt/hermes/pets-seed

COPY entrypoint.sh /hermes-entrypoint.sh
RUN chmod +x /hermes-entrypoint.sh

