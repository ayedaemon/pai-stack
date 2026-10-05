# pai-stack — DSH with bundled Mnemon CLI (memory backend for dsh-mnemon).
#
# Why a custom build: the upstream dsh-docker-server image ships node + dsh
# only. dsh-mnemon (our chosen memory plugin) shells out to the `mnemon`
# binary, which is NOT in the upstream image and cannot be installed at
# runtime (read-only root FS). So we install it here at build time.
#
# Why npm and NOT go install: the base is node:24-slim (no Go toolchain).
# The @mnemon-dev/mnemon npm package installs the matching native Go
# executable for the image OS/CPU — no compiler needed. The engine stays a
# single native binary; Node is only the launcher.
#
# Why prefix /usr/local and NOT the default: upstream sets
# NPM_CONFIG_PREFIX=/opt/dsh, which is the runtime volume mount — anything
# installed there at build time is shadowed by the volume at runtime.
# /usr/local lives in the image layer: the binary survives volume wipes and
# stays executable under read-only root FS (a+rX for uid 1000).
#
# To pin a different base: docker compose build --build-arg DSH_BASE=<ref>
#
# ── Multi-language toolchain (python3 + uv, go, rust + cargo) ──
# Added so agents can actually *run* the suites of the projects they edit,
# not just read them. Upstream ships node + dsh only, and the container is
# `read_only: true` with `cap_drop: [ALL]` — so, exactly like mnemon, all of
# this has to be baked in at build time. Nothing can be `apt install`ed later.
#
# The C toolchain (build-essential) is not for Go or Rust, which compile
# natively. It is here because Python C extensions do NOT: `uv sync` on any
# project depending on pydantic-core, numpy, cryptography or orjson needs a
# compiler + python3-dev at install time. Without it the install dies halfway.
#
# Caches are NOT left on the default paths. HOME is the shared
# /opt/data/workspace bind mount, so a default GOCACHE/GOMODCACHE/CARGO_HOME
# would scatter build caches into the host workspace that Hermes also reads.
# docker-compose.dsh.yaml redirects them onto the dsh_data volume instead;
# only the read-only toolchains themselves live here, under /usr/local.

ARG DSH_BASE=ghcr.io/steven-stack-s/dsh-docker-server:v0.6.0-dsh-0.2.0-rc.2
FROM ${DSH_BASE}

USER root

ARG MNEMON_VERSION=0.2.10
RUN NPM_CONFIG_PREFIX=/usr/local npm install -g @mnemon-dev/mnemon@${MNEMON_VERSION} \
    && /usr/local/bin/mnemon --version \
    && chmod -R a+rX /usr/local/lib/node_modules/@mnemon-dev/mnemon

# ── Pinned toolchain versions ──
# GO_SHA256_* are the values published by https://go.dev/dl/?mode=json for
# GO_VERSION. Both arches are listed because this image builds on amd64 and
# arm64 hosts alike; the build picks via dpkg --print-architecture. To bump
# Go, read the new sha256 out of that endpoint and update both.
#
# RUST_VERSION is a pinned rustc channel number, not the `stable` alias, so a
# surprise toolchain bump can't change build results under a running stack.
# Careful when refreshing this: the first `version =` line in
# channel-rust-stable.toml is *cargo's*, not rustc's — cargo reads 0.100.0
# while rustc reads 1.99.0. Take the value from the [pkg.rust] block, or just
# confirm with https://static.rust-lang.org/dist/channel-rust-<v>.toml → 200.
ARG GO_VERSION=1.27.1
ARG GO_SHA256_AMD64=63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445
ARG GO_SHA256_ARM64=3450b45a3f9ee8568792736a5c5e70a1f2e9b36c35a8f74958c03e51d7d92bec
ARG UV_VERSION=0.12.23
ARG RUST_VERSION=1.99.0

# curl is not in the upstream base — install it (with the Python/C toolchain)
# in a single RUN so the apt lists never survive into their own layer.
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        build-essential \
        pkg-config \
        libssl-dev \
    ; \
    rm -rf /var/lib/apt/lists/*

# GOROOT/RUSTUP_HOME/CARGO_HOME are set before the installs so the toolchains
# land in the image layer under /usr/local instead of in root's HOME. Same
# reasoning as the mnemon install above: /usr/local survives a volume wipe and
# stays readable by uid 1000 under a read-only root FS.
#
# CARGO_HOME is deliberately overridden *again* at runtime by the compose
# file. The rustup proxies in /usr/local/cargo/bin dispatch through
# RUSTUP_HOME (stays here, read-only, which is fine), while the crates
# registry and `cargo install` output follow CARGO_HOME onto the writable
# volume. That override is what makes `cargo build` work at all here.
ENV GOROOT=/usr/local/go \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/go/bin:/usr/local/cargo/bin:/usr/local/bin:${PATH}

# Go — official tarball, checksum-verified. Deliberately not the apt package:
# Debian 12 ships go1.19, and testing projects against a stale toolchain is
# worse than carrying a larger image.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) goarch=amd64; go_sha256="${GO_SHA256_AMD64}" ;; \
        arm64) goarch=arm64; go_sha256="${GO_SHA256_ARM64}" ;; \
        *) echo "dsh: unsupported architecture for the go toolchain: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/go.tar.gz "https://go.dev/dl/go${GO_VERSION}.linux-${goarch}.tar.gz"; \
    echo "${go_sha256}  /tmp/go.tar.gz" | sha256sum -c -; \
    tar -C /usr/local -xzf /tmp/go.tar.gz; \
    rm -f /tmp/go.tar.gz

# uv — upstream release tarball. Both flags below are load-bearing: the archive
# wraps the binaries in a uv-<arch>-unknown-linux-gnu/ directory, and GNU tar
# matches member names *before* stripping, so the patterns must name the
# directory. Plain `... --strip-components=1 uv uvx` fails with
# "uv: Not found in archive" — verified against the real 0.12.23 tarball.
# The patterns also keep the extraction to the two binaries if a future
# release starts shipping docs or licenses alongside them.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) uvarch=x86_64 ;; \
        arm64) uvarch=aarch64 ;; \
        *) echo "dsh: unsupported architecture for uv: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/uv.tar.gz \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${uvarch}-unknown-linux-gnu.tar.gz"; \
    tar -C /usr/local/bin -xzf /tmp/uv.tar.gz --strip-components=1 --wildcards '*/uv' '*/uvx'; \
    rm -f /tmp/uv.tar.gz

# Rust + cargo — rustup-init, minimal profile (rustc/cargo/rust-std) plus
# clippy and rustfmt, which is exactly what a project's `cargo fmt --check`
# and `cargo clippy` CI steps invoke.
# --no-modify-path because PATH is managed explicitly above.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) triple=x86_64-unknown-linux-gnu ;; \
        arm64) triple=aarch64-unknown-linux-gnu ;; \
        *) echo "dsh: unsupported architecture for rust: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/rustup-init "https://static.rust-lang.org/rustup/dist/${triple}/rustup-init"; \
    chmod +x /tmp/rustup-init; \
    /tmp/rustup-init -y --no-modify-path --profile minimal \
        --component clippy,rustfmt \
        --default-toolchain "${RUST_VERSION}"; \
    rm -f /tmp/rustup-init

# Docker CLI + compose plugin — the client side of the socket that
# docker-compose.dsh.yaml mounts. Mirrors hermes/Dockerfile exactly (same
# keyring, same repo, same packages) so both containers drive docker the same
# way.
# `docker-ce-cli` only, never `docker-ce`: the daemon is the host's, this
# image needs no engine of its own. `jq` comes along for the same reason it
# does in hermes — it's what makes `docker inspect` output readable.
# `gnupg` is NOT optional here: the base ships `gpgv` (verify-only, cannot
# dearmor) but no `gpg`, so the keyring step below would fail without it.
# Same package list as hermes/Dockerfile, deliberately.
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gnupg; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; \
    chmod a+r /etc/apt/keyrings/docker.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        docker-ce-cli docker-compose-plugin jq \
    ; \
    rm -rf /var/lib/apt/lists/*

# Make the `node` user (the runtime uid) a member of the host's docker group.
# compose passes the detected value in as DOCKER_GID (see docker-compose.dsh.yaml).
#
# This is required even though compose also sets `group_add`. The base
# entrypoint finishes with:
#     exec setpriv --reuid=1000 --regid=1000 --init-groups "$0" "$@"
# and `--init-groups` calls initgroups(3), which calls setgroups(2) — and
# setgroups REPLACES the supplementary group list rather than adding to it.
# So anything Docker put there via group_add is discarded at the privilege
# drop, and the socket becomes EACCES. Writing the membership into /etc/group
# here is what survives: initgroups rebuilds the list from that file. There is
# no runtime alternative — the root FS is read_only:true.
ARG DOCKER_GID=999
RUN set -eux; \
    # Reuse whatever group already holds this GID (gid 0 is `root`, the node
    # primary is 1000, etc.); only mint one when nothing does.
    docker_group="$(getent group "${DOCKER_GID}" | cut -d: -f1 || true)"; \
    if [ -z "$docker_group" ]; then \
        docker_group=docker; \
        groupadd -g "${DOCKER_GID}" "$docker_group"; \
    fi; \
    # Skip if it IS the primary group — usermod rejects/needlessly re-adds that.
    if [ "${DOCKER_GID}" != "$(id -g node)" ]; then \
        usermod -aG "$docker_group" node; \
    fi; \
    id node

# a+rX mirrors the mnemon rule: all of the above was installed as root, but
# the runtime uid is 1000 under cap_drop:[ALL], so nothing may depend on
# root-only bits. The version prints then double as a build log — if one is
# missing the build fails here rather than shipping an image where an agent
# only discovers it mid-test-run.
# `docker version` is deliberately NOT asserted here: it contacts the daemon,
# and no socket exists at build time. The `docker --version` client check is
# the whole of what can be proven without a running host daemon.
RUN set -eux; \
    chmod -R a+rX /usr/local/go /usr/local/rustup /usr/local/cargo /usr/local/bin/uv /usr/local/bin/uvx; \
    python3 --version; \
    uv --version; \
    uvx --version; \
    go version; \
    cargo --version; \
    rustc --version; \
    cargo fmt --version; \
    cargo clippy --version; \
    cc --version | head -n1; \
    docker --version; \
    docker compose version
