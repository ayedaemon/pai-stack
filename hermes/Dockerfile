FROM nousresearch/hermes-agent:latest

USER root

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Mnemosyne memory provider and langfuse SDK
RUN uv pip install --python /opt/hermes/.venv/bin/python mnemosyne-hermes langfuse

COPY entrypoint.sh /hermes-entrypoint.sh
RUN chmod +x /hermes-entrypoint.sh
