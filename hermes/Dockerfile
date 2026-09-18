FROM nousresearch/hermes-agent:latest

USER root

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Mnemosyne memory provider and langfuse SDK
RUN uv pip install --python /opt/hermes/.venv/bin/python mnemosyne-hermes langfuse

# Install Hermes Labyrinth dashboard plugin (pinned to v0.1.3)
RUN git clone https://github.com/stainlu/hermes-labyrinth.git /opt/hermes/plugins/hermes-labyrinth && \
    cd /opt/hermes/plugins/hermes-labyrinth && \
    git checkout v0.1.3 && \
    chown -R 1000:1000 /opt/hermes/plugins/hermes-labyrinth

COPY entrypoint.sh /hermes-entrypoint.sh
RUN chmod +x /hermes-entrypoint.sh

