ARG OPEN_DESIGN_BASE=ghcr.io/nexu-io/od:latest
FROM ${OPEN_DESIGN_BASE}

USER root

# Match /app/.od ownership to your host user so named volumes don't hit EACCES
ARG UID=1000
ARG GID=1000
RUN chown -R ${UID}:${GID} /app/.od

# Install glibc compatibility + tools needed to fetch OpenCode on Alpine Linux
ARG OPENCODE_VERSION=1.18.32
RUN apk add --no-cache libc6-compat curl tar xz bash \
    && curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path -v ${OPENCODE_VERSION} \
    && ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode \
    && chmod -R a+rX /root/.opencode \
    && chmod a+x /root \
    && /usr/local/bin/opencode --version

# Create writable runtime directories for OpenCode cache/config
RUN mkdir -p /tmp/.config/opencode /tmp/.local/share/opencode \
    && chown -R ${UID}:${GID} /tmp/.config /tmp/.local

# Bind OpenDesign daemon to all network interfaces (0.0.0.0) on port 7456
ENV HOME=/tmp \
    OD_DATA_DIR=/app/.od \
    OD_HOST=0.0.0.0 \
    OD_PORT=7456

EXPOSE 7456
