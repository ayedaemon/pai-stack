# pai-stack — Custom DSH Build (Official DSH Binary, Layer by Layer)
#
# This Dockerfile builds DSH from the official npm package @deepseek-ai/dsh
# instead of using the upstream dsh-docker-server image. It makes explicit
# architectural choices to avoid host/container mapping complications:
#
# 1. DSH program lives in the IMAGE (not a volume) — version-pinned, immutable
# 2. Workspace is a BIND MOUNT at a DIFFERENT PATH — no conflict with DSH_HOME
# 3. Toolchain caches on a NAMED VOLUME — not scattered in workspace
# 4. Host UID/GID mapping — not fixed uid 1000 (compose `user:` + baked
#    /data/dsh skeleton, so fresh volumes inherit the right owner)
# 5. Docker CLI for host-daemon reuse — socket mounted at runtime with
#    `group_add: [DOCKER_GID]`, no proxy socket, no extra caps
#
# Usage:
#   docker build -t pai-stack-dsh:custom \
#     --build-arg DSH_VERSION=0.2.0-rc.2 \
#     --build-arg TARGET_UID=1000 \
#     --build-arg TARGET_GID=1000 \
#     --build-arg WITH_DOCKER_SOCKET=true \
#     -f dsh/Dockerfile.custom ./dsh

ARG BASE_IMAGE=node:24-slim
FROM ${BASE_IMAGE} AS base

# ── Build arguments ──────────────────────────────────────────────────────
ARG DSH_VERSION=0.2.0-rc.2
ARG MNEMON_VERSION=0.2.10
ARG GO_VERSION=1.27.1
ARG GO_SHA256_AMD64=63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445
ARG GO_SHA256_ARM64=3450b45a3f9ee8568792736a5c5e70a1f2e9b36c35a8f74958c03e51d7d92bec
ARG UV_VERSION=0.12.23
ARG RUST_VERSION=1.99.0
ARG TARGET_UID=1000
ARG TARGET_GID=1000
ARG WITH_DOCKER_SOCKET=true
# Auth plugin (@xgone/dsh-remote) — matches upstream default
ARG WITH_REMOTE_PLUGIN=true
ARG REMOTE_PLUGIN_VERSION=0.3.5
ARG REMOTE_PLUGIN_NAME=@xgone/dsh-remote
# Memory plugin (dsh-mnemon) — tools surface as mnemon_* (no rename support
# upstream); shared skills keep calling Hermes-native mnemosyne_*
ARG WITH_MNEMON_PLUGIN=true
ARG MNEMON_PLUGIN_VERSION=0.5.24
ARG MNEMON_PLUGIN_NAME=dsh-mnemon

# ── Stage 1: Install system dependencies ────────────────────────────────
FROM base AS deps

USER root

# Install runtime dependencies in a single layer
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        build-essential \
        pkg-config \
        libssl-dev \
        gnupg \
        jq \
        socat \
        openssh-client \
    ; \
    rm -rf /var/lib/apt/lists/*

# ── Stage 2: Install DSH (official npm package) ─────────────────────────
FROM deps AS dsh-install

# Re-declare build args for this stage
ARG DSH_VERSION=0.2.0-rc.2

# Install DSH globally into the image (not a volume)
# NPM_CONFIG_PREFIX=/usr/local ensures it stays in the image layer
RUN set -eux; \
    NPM_CONFIG_PREFIX=/usr/local npm install -g @deepseek-ai/dsh@${DSH_VERSION} \
    && /usr/local/bin/dsh --version

# Verify DSH installation
RUN dsh --version && which dsh

# ── Stage 3: Install Mnemon CLI (for dsh-mnemon plugin) ─────────────────
FROM dsh-install AS mnemon

ARG MNEMON_VERSION=0.2.10

# Install pnpm via corepack (included in Node.js 24)
RUN corepack enable pnpm && corepack prepare pnpm@latest --activate

RUN set -eux; \
    NPM_CONFIG_PREFIX=/usr/local npm install -g @mnemon-dev/mnemon@${MNEMON_VERSION} \
    && /usr/local/bin/mnemon --version \
    && chmod -R a+rX /usr/local/lib/node_modules/@mnemon-dev/mnemon

# ── Stage 4: Prepare auth plugin seed (@xgone/dsh-remote) ─────────────────
# This replicates upstream's approach: pre-install plugin via pnpm into a seed
# directory, then entrypoint copies it to the web profile on first boot.
FROM mnemon AS remote-plugin-seed

ARG WITH_REMOTE_PLUGIN=true
ARG REMOTE_PLUGIN_VERSION=0.3.5
ARG REMOTE_PLUGIN_NAME=@xgone/dsh-remote

# pnpm is installed with DSH at /usr/local/bin/pnpm (from NPM_CONFIG_PREFIX=/usr/local)
RUN set -eux; \
    if [ "${WITH_REMOTE_PLUGIN}" = "true" ] && [ -n "${REMOTE_PLUGIN_VERSION}" ]; then \
        echo "[seed] Installing ${REMOTE_PLUGIN_NAME}@${REMOTE_PLUGIN_VERSION} via pnpm"; \
        staging=/opt/dsh-remote-seed; \
        tmp_profile=/tmp/remote-seed-profile; \
        pnpm_bin=/usr/local/bin/pnpm; \
        if [ ! -x "${pnpm_bin}" ]; then \
            echo "[seed] FATAL: ${pnpm_bin} not found" >&2; exit 1; \
        fi; \
        rm -rf "${staging}" "${tmp_profile}"; \
        mkdir -p "${staging}" "${tmp_profile}"; \
        printf '{\n  "name": "dsh-remote-seed",\n  "private": true,\n  "dependencies": {}\n}\n' > "${tmp_profile}/package.json"; \
        printf 'packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n' > "${tmp_profile}/pnpm-workspace.yaml"; \
        cd "${tmp_profile}"; \
        export NPM_CONFIG_CACHE=/root/.npm; \
        "${pnpm_bin}" add --store-dir /root/.pnpm-store --ignore-scripts "${REMOTE_PLUGIN_NAME}@${REMOTE_PLUGIN_VERSION}"; \
        cp -a "${tmp_profile}/node_modules" "${staging}/node_modules"; \
        cp -a "${tmp_profile}/package.json" "${staging}/package.json"; \
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do \
            if [ -f "${tmp_profile}/${f}" ]; then cp -a "${tmp_profile}/${f}" "${staging}/${f}"; fi; \
        done; \
        # Verify plugin structure
        test -f "${staging}/node_modules/${REMOTE_PLUGIN_NAME}/package.json"; \
        test -f "${staging}/node_modules/${REMOTE_PLUGIN_NAME}/cordis.patch.yml"; \
        node -e "const p=require('${staging}/node_modules/${REMOTE_PLUGIN_NAME}/package.json'); if(!p.dsh||!p.dsh.bundle||!p.dsh.bundle.patch) throw new Error('not a DSH bundle: '+p.name); console.log('[seed] auth plugin', p.name+'@'+p.version, 'bundle patch:', p.dsh.bundle.patch)"; \
        chmod -R a+rX "${staging}"; \
        rm -rf "${tmp_profile}"; \
        echo '[seed] auth plugin staged at /opt/dsh-remote-seed'; \
    else \
        echo "[seed] WITH_REMOTE_PLUGIN=false or version empty, skipping auth plugin seed"; \
        mkdir -p /opt/dsh-remote-seed; \
    fi

# ── Stage 4b: Prepare memory plugin seed (dsh-mnemon) ───────────────────
# Joint tree: starts as a copy of the auth seed (when enabled) so pnpm
# resolves BOTH plugins together — exactly what `dsh plugin add` does live
# (verified: remote 0.3.5 + mnemon 0.5.24 resolve cleanly). The entrypoint
# installs this tree wholesale, so no runtime merge conflicts are possible.
FROM remote-plugin-seed AS mnemon-plugin-seed

ARG WITH_REMOTE_PLUGIN=true
ARG WITH_MNEMON_PLUGIN=true
ARG MNEMON_PLUGIN_VERSION=0.5.24
ARG MNEMON_PLUGIN_NAME=dsh-mnemon

RUN set -eux; \
    if [ "${WITH_MNEMON_PLUGIN}" = "true" ] && [ -n "${MNEMON_PLUGIN_VERSION}" ]; then \
        echo "[seed] Installing ${MNEMON_PLUGIN_NAME}@${MNEMON_PLUGIN_VERSION} (joint with auth seed) via pnpm"; \
        staging=/opt/dsh-mnemon-seed; \
        tmp_profile=/tmp/mnemon-seed-profile; \
        pnpm_bin=/usr/local/bin/pnpm; \
        if [ ! -x "${pnpm_bin}" ]; then \
            echo "[seed] FATAL: ${pnpm_bin} not found" >&2; exit 1; \
        fi; \
        rm -rf "${staging}" "${tmp_profile}"; \
        mkdir -p "${staging}" "${tmp_profile}"; \
        if [ "${WITH_REMOTE_PLUGIN}" = "true" ] && [ -d /opt/dsh-remote-seed/node_modules ]; then \
            cp -a /opt/dsh-remote-seed/. "${tmp_profile}/"; \
            node -p "require('${tmp_profile}/package.json').name" | grep -q "seed" || exit 1; \
        else \
            printf '{\n  "name": "dsh-mnemon-seed",\n  "private": true,\n  "dependencies": {}\n}\n' > "${tmp_profile}/package.json"; \
            printf 'packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n' > "${tmp_profile}/pnpm-workspace.yaml"; \
        fi; \
        cd "${tmp_profile}"; \
        export NPM_CONFIG_CACHE=/root/.npm; \
        "${pnpm_bin}" add --store-dir /root/.pnpm-store --ignore-scripts "${MNEMON_PLUGIN_NAME}@${MNEMON_PLUGIN_VERSION}"; \
        cp -a "${tmp_profile}/node_modules" "${staging}/node_modules"; \
        cp -a "${tmp_profile}/package.json" "${staging}/package.json"; \
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do \
            if [ -f "${tmp_profile}/${f}" ]; then cp -a "${tmp_profile}/${f}" "${staging}/${f}"; fi; \
        done; \
        test -f "${staging}/node_modules/${MNEMON_PLUGIN_NAME}/package.json"; \
        test -f "${staging}/node_modules/${MNEMON_PLUGIN_NAME}/cordis.patch.yml"; \
        node -e "const p=require('${staging}/node_modules/${MNEMON_PLUGIN_NAME}/package.json'); if(!p.dsh||!p.dsh.bundle||!p.dsh.bundle.patch) throw new Error('not a DSH bundle: '+p.name); console.log('[seed] memory plugin', p.name+'@'+p.version, 'bundle patch:', p.dsh.bundle.patch)"; \
        chmod -R a+rX "${staging}"; \
        rm -rf "${tmp_profile}"; \
        echo '[seed] memory plugin staged at /opt/dsh-mnemon-seed (joint tree)'; \
    else \
        echo "[seed] WITH_MNEMON_PLUGIN=false or version empty, skipping memory plugin seed"; \
        mkdir -p /opt/dsh-mnemon-seed; \
    fi

# ── Stage 5: Install Go toolchain ───────────────────────────────────────
FROM mnemon-plugin-seed AS go-toolchain

ARG GO_VERSION=1.27.1
ARG GO_SHA256_AMD64=63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445
ARG GO_SHA256_ARM64=3450b45a3f9ee8568792736a5c5e70a1f2e9b36c35a8f74958c03e51d7d92bec

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) goarch=amd64; go_sha256="${GO_SHA256_AMD64}" ;; \
        arm64) goarch=arm64; go_sha256="${GO_SHA256_ARM64}" ;; \
        *) echo "Unsupported architecture for Go: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/go.tar.gz "https://go.dev/dl/go${GO_VERSION}.linux-${goarch}.tar.gz"; \
    echo "${go_sha256}  /tmp/go.tar.gz" | sha256sum -c -; \
    tar -C /usr/local -xzf /tmp/go.tar.gz; \
    rm -f /tmp/go.tar.gz

ENV GOROOT=/usr/local/go \
    PATH=/usr/local/go/bin:${PATH}

# ── Stage 5: Install uv (Python package manager) ────────────────────────
FROM go-toolchain AS uv-toolchain

ARG UV_VERSION=0.12.23

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) uvarch=x86_64 ;; \
        arm64) uvarch=aarch64 ;; \
        *) echo "Unsupported architecture for uv: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/uv.tar.gz \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${uvarch}-unknown-linux-gnu.tar.gz"; \
    tar -C /usr/local/bin -xzf /tmp/uv.tar.gz --strip-components=1 --wildcards '*/uv' '*/uvx'; \
    rm -f /tmp/uv.tar.gz

# ── Stage 6: Install Rust toolchain ─────────────────────────────────────
FROM uv-toolchain AS rust-toolchain

ARG RUST_VERSION=1.99.0

ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:${PATH}

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) triple=x86_64-unknown-linux-gnu ;; \
        arm64) triple=aarch64-unknown-linux-gnu ;; \
        *) echo "Unsupported architecture for Rust: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/rustup-init "https://static.rust-lang.org/rustup/dist/${triple}/rustup-init"; \
    chmod +x /tmp/rustup-init; \
    /tmp/rustup-init -y --no-modify-path --profile minimal \
        --component clippy,rustfmt \
        --default-toolchain "${RUST_VERSION}"; \
    rm -f /tmp/rustup-init

# ── Stage 7: Install Docker CLI (optional) ──────────────────────────────
FROM rust-toolchain AS docker-cli

# Only install Docker CLI if WITH_DOCKER_SOCKET=true
ARG WITH_DOCKER_SOCKET=true

RUN set -eux; \
    if [ "${WITH_DOCKER_SOCKET}" = "true" ]; then \
        apt-get update; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gnupg; \
        install -m 0755 -d /etc/apt/keyrings; \
        curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; \
        chmod a+r /etc/apt/keyrings/docker.gpg; \
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list; \
        apt-get update; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            docker-ce-cli docker-compose-plugin \
        ; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# ── Stage 8: Final image with user setup and entrypoint ─────────────────
FROM docker-cli AS final

ARG TARGET_UID=1000
ARG TARGET_GID=1000
ARG WITH_DOCKER_SOCKET=true
# Auth plugin seed args (passed through from earlier stage)
ARG WITH_REMOTE_PLUGIN=true
ARG REMOTE_PLUGIN_VERSION=0.3.5
ARG REMOTE_PLUGIN_NAME=@xgone/dsh-remote
# Memory plugin seed args (passed through from earlier stage)
ARG WITH_MNEMON_PLUGIN=true
ARG MNEMON_PLUGIN_VERSION=0.5.24
ARG MNEMON_PLUGIN_NAME=dsh-mnemon
# Durable automation plugin (joint tree built here, in final — placing it in
# an earlier stage would invalidate the cached Go/uv/Rust layers below)
ARG WITH_AUTOMATION_PLUGIN=true
ARG AUTOMATION_PLUGIN_VERSION=0.1.54
ARG AUTOMATION_PLUGIN_NAME=@michengai/dsh-automation
# First-party Telegram plugin (in-repo source at plugins/dsh-pai-telegram,
# joint tree built here in final alongside automation)
ARG WITH_TELEGRAM_PLUGIN=true
ARG TELEGRAM_PLUGIN_NAME=dsh-pai-telegram

# The /opt/dsh-remote-seed directory is already present from the remote-plugin-seed stage
# (which is an ancestor of docker-cli). Verify it exists.
RUN if [ "${WITH_REMOTE_PLUGIN}" = "true" ] && [ -n "${REMOTE_PLUGIN_VERSION}" ]; then \
        test -d /opt/dsh-remote-seed && test -f /opt/dsh-remote-seed/node_modules/${REMOTE_PLUGIN_NAME}/cordis.patch.yml \
        && echo "[final] Auth plugin seed verified at /opt/dsh-remote-seed"; \
    else \
        echo "[final] No auth plugin seed (WITH_REMOTE_PLUGIN=${WITH_REMOTE_PLUGIN})"; \
    fi

# Same for the memory plugin seed (ancestor mnemon-plugin-seed).
RUN if [ "${WITH_MNEMON_PLUGIN}" = "true" ] && [ -n "${MNEMON_PLUGIN_VERSION}" ]; then \
        test -d /opt/dsh-mnemon-seed && test -f /opt/dsh-mnemon-seed/node_modules/${MNEMON_PLUGIN_NAME}/cordis.patch.yml \
        && echo "[final] Memory plugin seed verified at /opt/dsh-mnemon-seed"; \
    else \
        echo "[final] No memory plugin seed (WITH_MNEMON_PLUGIN=${WITH_MNEMON_PLUGIN})"; \
    fi

# ── Durable automation seed (@michengai/dsh-automation, joint tree) ─────────
# Extends the mnemon joint tree (remote+mnemon) the same way the mnemon seed
# extended the auth seed: copy + `pnpm add`, so the entrypoint installs one
# superset tree with no runtime merge conflicts by construction. Built here in
# final (not as an earlier stage) so the cached toolchain layers above stay
# valid. Pinned exact in .env (AUTOMATION_PLUGIN_VERSION); peerDeps cover
# DSH 0.2.0-rc.2 explicitly (verified Oct-2026 — the alternatives only allow
# <0.2.0). `--ignore-scripts` blocks lifecycle scripts at seed time.
RUN set -eux; \
    if [ "${WITH_AUTOMATION_PLUGIN}" = "true" ] && [ -n "${AUTOMATION_PLUGIN_VERSION}" ]; then \
        echo "[seed] Installing ${AUTOMATION_PLUGIN_NAME}@${AUTOMATION_PLUGIN_VERSION} (joint with auth+memory seeds) via pnpm"; \
        staging=/opt/dsh-auto-seed; \
        tmp_profile=/tmp/auto-seed-profile; \
        pnpm_bin=/usr/local/bin/pnpm; \
        if [ ! -x "${pnpm_bin}" ]; then \
            echo "[seed] FATAL: ${pnpm_bin} not found" >&2; exit 1; \
        fi; \
        rm -rf "${staging}" "${tmp_profile}"; \
        mkdir -p "${staging}" "${tmp_profile}"; \
        cp -a /opt/dsh-mnemon-seed/. "${tmp_profile}/"; \
        node -p "require('${tmp_profile}/package.json').name" | grep -q "seed" || exit 1; \
        cd "${tmp_profile}"; \
        export NPM_CONFIG_CACHE=/root/.npm; \
        "${pnpm_bin}" add --store-dir /root/.pnpm-store --ignore-scripts "${AUTOMATION_PLUGIN_NAME}@${AUTOMATION_PLUGIN_VERSION}"; \
        cp -a "${tmp_profile}/node_modules" "${staging}/node_modules"; \
        cp -a "${tmp_profile}/package.json" "${staging}/package.json"; \
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do \
            if [ -f "${tmp_profile}/${f}" ]; then cp -a "${tmp_profile}/${f}" "${staging}/${f}"; fi; \
        done; \
        test -f "${staging}/node_modules/${AUTOMATION_PLUGIN_NAME}/package.json"; \
        test -f "${staging}/node_modules/${AUTOMATION_PLUGIN_NAME}/cordis.patch.yml"; \
        node -e "const p=require('${staging}/node_modules/${AUTOMATION_PLUGIN_NAME}/package.json'); if(!p.dsh||!p.dsh.bundle||!p.dsh.bundle.patch) throw new Error('not a DSH bundle: '+p.name); console.log('[seed] automation plugin', p.name+'@'+p.version, 'bundle patch:', p.dsh.bundle.patch)"; \
        chmod -R a+rX "${staging}"; \
        rm -rf "${tmp_profile}"; \
        echo '[seed] automation plugin staged at /opt/dsh-auto-seed (joint tree)'; \
    else \
        echo "[seed] WITH_AUTOMATION_PLUGIN=false or version empty, skipping automation seed"; \
        mkdir -p /opt/dsh-auto-seed; \
    fi

# ── First-party Telegram seed (dsh-pai-telegram, joint tree) ─────────────
# In-repo source (no registry): extends the automation joint tree the same
# way — copy + `pnpm add file:<src>`, `--ignore-scripts`, bundle-shape gate.
# Built here in final so toolchain layers stay cached. Phase 3 scaffold is
# host-only (inject:[]) so it cannot red-screen the web UI.
COPY plugins/dsh-pai-telegram /tmp/dsh-pai-telegram-src
RUN set -eux; \
    if [ "${WITH_TELEGRAM_PLUGIN:-true}" = "true" ]; then \
        echo "[seed] Installing dsh-pai-telegram (joint with auto seed) via pnpm file:"; \
        staging=/opt/dsh-telegram-seed; \
        tmp_profile=/tmp/telegram-seed-profile; \
        pnpm_bin=/usr/local/bin/pnpm; \
        if [ ! -x "${pnpm_bin}" ]; then \
            echo "[seed] FATAL: ${pnpm_bin} not found" >&2; exit 1; \
        fi; \
        rm -rf "${staging}" "${tmp_profile}"; \
        mkdir -p "${staging}" "${tmp_profile}"; \
        cp -a /opt/dsh-auto-seed/. "${tmp_profile}/"; \
        node -p "require('${tmp_profile}/package.json').name" | grep -q "seed" || exit 1; \
        cd "${tmp_profile}"; \
        export NPM_CONFIG_CACHE=/root/.npm; \
        "${pnpm_bin}" add --store-dir /root/.pnpm-store --ignore-scripts "file:/tmp/dsh-pai-telegram-src"; \
        cp -a "${tmp_profile}/node_modules" "${staging}/node_modules"; \
        cp -a "${tmp_profile}/package.json" "${staging}/package.json"; \
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do \
            if [ -f "${tmp_profile}/${f}" ]; then cp -a "${tmp_profile}/${f}" "${staging}/${f}"; fi; \
        done; \
        test -f "${staging}/node_modules/${TELEGRAM_PLUGIN_NAME}/package.json"; \
        test -f "${staging}/node_modules/${TELEGRAM_PLUGIN_NAME}/cordis.patch.yml"; \
        test -f "${staging}/node_modules/${TELEGRAM_PLUGIN_NAME}/lib/index.js"; \
        node -e "const p=require('${staging}/node_modules/${TELEGRAM_PLUGIN_NAME}/package.json'); if(!p.dsh||!p.dsh.bundle||!p.dsh.bundle.patch) throw new Error('not a DSH bundle: '+p.name); console.log('[seed] telegram plugin', p.name+'@'+p.version, 'bundle patch:', p.dsh.bundle.patch)"; \
        node --check "${staging}/node_modules/${TELEGRAM_PLUGIN_NAME}/lib/index.js"; \
        chmod -R a+rX "${staging}"; \
        rm -rf "${tmp_profile}" /tmp/dsh-pai-telegram-src; \
        echo '[seed] telegram plugin staged at /opt/dsh-telegram-seed (joint tree)'; \
    else \
        echo "[seed] WITH_TELEGRAM_PLUGIN=false, skipping telegram seed"; \
        mkdir -p /opt/dsh-telegram-seed; \
        rm -rf /tmp/dsh-pai-telegram-src; \
    fi

# Automation tasks (official experimental schedule bundle). Ships inside the
# @deepseek-ai/dsh package itself — no seed copy needed, the entrypoint only
# appends it to the web profile's bundles list. Gate fails the build if a
# DSH_VERSION bump ever drops or renames it.
RUN BUNDLE=/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-experimental-schedule-bundle; \
    test -f "${BUNDLE}/package.json" && test -f "${BUNDLE}/cordis.patch.yml" \
    && node -e "const p=require('${BUNDLE}/package.json'); if(!p.dsh||!p.dsh.bundle||!p.dsh.bundle.patch) throw new Error('not a DSH bundle: '+p.name); console.log('[final] schedule bundle', p.name+'@'+p.version)"

# Dedicated runtime user matching the host UID/GID (compose `user:` runs as
# this numeric id from PID 1 — no setpriv, no groupmod). Reuses an existing
# group id when taken (e.g. Debian `dialout` owns 20, macOS staff is 20):
# numeric ownership is what matters, not the name.
RUN set -eux; \
    if getent group "${TARGET_GID}" >/dev/null; then \
        echo "[final] GID ${TARGET_GID} exists ($(getent group "${TARGET_GID}" | cut -d: -f1)), reusing"; \
    else \
        groupadd -g "${TARGET_GID}" dsh; \
    fi; \
    if ! id dsh >/dev/null 2>&1; then \
        useradd -o -m -u "${TARGET_UID}" -g "${TARGET_GID}" -d /data/dsh/home -s /bin/bash dsh; \
    fi; \
    id dsh; \
    # Bake the data-volume skeleton so fresh named volumes inherit the right
    # owner on creation (Docker copies image ownership in). Pre-existing
    # volumes are covered once by `make dsh-perms`.
    mkdir -p /data/dsh/home/.cache /data/dsh/tmp /data/dsh/profiles/web \
        /data/dsh/storages /data/dsh/sessions /data/dsh/auth; \
    chown -R "${TARGET_UID}:${TARGET_GID}" /data/dsh; \
    # Docker access is via compose group_add on the mounted socket, not here.
    echo "[final] runtime user dsh ${TARGET_UID}:${TARGET_GID}"

# Ensure all installed toolchains are readable by the node user
RUN set -eux; \
    chmod -R a+rX /usr/local/go /usr/local/rustup /usr/local/cargo /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/dsh /usr/local/bin/mnemon 2>/dev/null || true; \
    # Also ensure auth plugin seed is readable
    if [ -d /opt/dsh-remote-seed ]; then chmod -R a+rX /opt/dsh-remote-seed; fi; \
    # Also ensure memory plugin seed is readable
    if [ -d /opt/dsh-mnemon-seed ]; then chmod -R a+rX /opt/dsh-mnemon-seed; fi; \
    # Also ensure automation plugin seed is readable
    if [ -d /opt/dsh-auto-seed ]; then chmod -R a+rX /opt/dsh-auto-seed; fi; \
    # Also ensure telegram plugin seed is readable
    if [ -d /opt/dsh-telegram-seed ]; then chmod -R a+rX /opt/dsh-telegram-seed; fi

# Single canonical home: /data/dsh/home lives on the data volume, so it is
# writable at runtime (the image layer is read_only:true). Session cwd comes
# from the container working_dir (/opt/data/workspace, set in compose), and
# every cache below must accept writes — paths under /home/node or
# /home/dshuser are dead on a read-only rootfs.
ENV DSH_HOME=/data/dsh \
    HOME=/data/dsh/home \
    PATH=/usr/local/go/bin:/usr/local/cargo/bin:/usr/local/bin:${PATH} \
    GOROOT=/usr/local/go \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    # Toolchain cache directories (on the dsh_toolchains volume via $HOME/.cache)
    GOCACHE=/data/dsh/home/.cache/go/build \
    GOMODCACHE=/data/dsh/home/.cache/go/mod \
    GOPATH=/data/dsh/home/.cache/go/path \
    CARGO_HOME=/data/dsh/home/.cache/cargo \
    UV_CACHE_DIR=/data/dsh/home/.cache/uv/cache \
    UV_PYTHON_INSTALL_DIR=/data/dsh/home/.cache/uv/python \
    UV_TOOL_DIR=/data/dsh/home/.cache/uv/tools \
    UV_TOOL_BIN_DIR=/data/dsh/home/.cache/uv/bin \
    PIP_CACHE_DIR=/data/dsh/home/.cache/pip \
    UV_LINK_MODE=copy \
    DOCKER_CONFIG=/data/dsh/home/.docker \
    # TMPDIR must point to data volume (not tmpfs) for large temp files
    TMPDIR=/data/dsh/tmp \
    # Native bindings must load from executable volume
    NARB_DISABLE_NATIVE_CACHE=1 \
    # Timezone
    TZ=Asia/Shanghai

# /tmp is tmpfs at runtime; image-layer home paths are unused
# (HOME=/data/dsh/home on the volume). Volume content above is the
# ownership seed for fresh named volumes.
RUN mkdir -p /tmp && chmod 1777 /tmp

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD node -e "require('net').connect(3081,'127.0.0.1').on('connect',()=>process.exit(0)).on('error',()=>process.exit(1))"

# Patch-segment tool for entrypoint profile maintenance (stdlib-only python3).
# NOTE: the entrypoint pre-seeds storages/workspace.json with the schema below
# (unit version 2, global/workspaceIds/defaultWorkspaceId, tables.workspaces).
# If DSH_VERSION is bumped, re-verify that schema against a live-written file.
COPY dsh-drop-patch-entry.py /usr/local/bin/dsh-drop-patch-entry
RUN chmod 755 /usr/local/bin/dsh-drop-patch-entry \
    && printf -- '- id: keep\n- insert:\n    - id: default-workspace\n' > /tmp/patch-smoke.yml \
    && python3 /usr/local/bin/dsh-drop-patch-entry /tmp/patch-smoke.yml default-workspace \
    && grep -q "id: keep" /tmp/patch-smoke.yml && ! grep -q "default-workspace" /tmp/patch-smoke.yml \
    && rm -f /tmp/patch-smoke.yml \
    && echo "[final] patch-segment tool installed and verified"

# Directory-picker start directory: stock DSH opens the "Select Workspace
# Directory" browse dialog at the server $HOME (homedir()) with no override.
# Read the container WORKSPACE_DIR first (falls back to home when unset) so
# the dialog opens at the shared mount. Parens are required: ?? and || must
# not mix unparenthesized. If DSH_VERSION is bumped, re-verify this line.
RUN BROWSE_LIB=/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-host-directory-picker-browse/lib/index.js \
    && grep -c "const target = resolve(path ?? home);" "${BROWSE_LIB}" | grep -qx "1" \
    && sed -i 's|const target = resolve(path ?? home);|const target = resolve(path ?? (process.env.WORKSPACE_DIR \|\| home));|' "${BROWSE_LIB}" \
    && grep -q "process.env.WORKSPACE_DIR" "${BROWSE_LIB}" \
    && echo "[final] directory-picker start dir patched to WORKSPACE_DIR"

# Entrypoint runs as the host user via compose `user:` (no setpriv).
# It only ensures dirs, seeds plugins + workspace registry, starts the
# 3080->3081 forwarder (non-root bind, port > 1024), and execs dsh web.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

USER root
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["dsh", "web"]