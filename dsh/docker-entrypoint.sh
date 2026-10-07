#!/bin/bash
# pai-stack — Minimal DSH Entrypoint
#
# Assumptions (see docker-compose.dsh.yaml):
# - PID 1 already runs as the host user via compose `user: "${UID}:${GID}"`.
#   No setpriv drop, no per-boot chown -R. Whatever this script creates is
#   owned correctly by creation.
# - Docker access is via the mounted /var/run/docker.sock + `group_add`
#   (no proxy socket). DOCKER_CONFIG lives on the data volume.
# - Workspace bind at /opt/data/workspace is never chowned.
#
# This script only: ensures writable dirs, seeds plugins + default workspace
# registry, starts the 3080->3081 forwarder, execs `dsh web`.

set -euo pipefail

elog() { printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

DSH_HOME="${DSH_HOME:-/data/dsh}"
PORT_INNER=3081
SOCAT_PORT="${SOCAT_PORT:-3080}"
SOCAT_MAX_CHILDREN="${SOCAT_MAX_CHILDREN:-64}"
RESCUE_PROFILE="${RESCUE_PROFILE:-web}"
TRUSTED_ARGS=""

elog "[entrypoint] Running as $(id)"

if [ -n "${DSH_TRUSTED_HOSTS:-}" ]; then
    elog "[entrypoint] trusted Host allowlist: ${DSH_TRUSTED_HOSTS}"
    IFS=',' read -ra HOSTS <<< "${DSH_TRUSTED_HOSTS}"
    for host in "${HOSTS[@]}"; do
        host=$(echo "$host" | xargs)
        if [ -n "$host" ]; then
            TRUSTED_ARGS="${TRUSTED_ARGS} --trusted-host ${host}"
        fi
    done
fi

if [ -S /var/run/docker.sock ]; then
    elog "[entrypoint] docker socket present, DOCKER_HOST=${DOCKER_HOST:-<default socket>}"
    if ! docker ps >/dev/null 2>&1; then
        elog "[entrypoint] WARN 'docker ps' failed — check group_add DOCKER_GID (Desktop=0, Linux=docker gid)"
    fi
else
    elog "[entrypoint] WARN no /var/run/docker.sock mounted — docker commands will fail"
fi

start_socat() {
    elog "[entrypoint] starting socat forward: 0.0.0.0:${SOCAT_PORT} -> 127.0.0.1:${PORT_INNER}"
    socat "TCP-LISTEN:${SOCAT_PORT},fork,reuseaddr,max-children=${SOCAT_MAX_CHILDREN}" \
          "TCP:127.0.0.1:${PORT_INNER},forever,interval=1" &
    SOCAT_PID=$!
    elog "[entrypoint] socat started with PID ${SOCAT_PID}"
}

# Default workspace = the shared mount root. DSH has no config for this:
# empty registry => stock first-use throws (no xdg-user-dir in image), so
# pre-seed storages/workspace.json iff absent. documentsDirectory row below
# is fallback only (it appends a fixed `deepseek-harness/default-workspace`
# suffix and can never yield the mount root itself).
seed_workspace_registry() {
    local store_dir="/data/dsh/storages"
    local ws_json="${store_dir}/workspace.json"
    if [ -f "${ws_json}" ]; then
        elog "[workspace-seed] registry present, skipping"
        return 0
    fi
    local ws_id ts
    ws_id="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "")"
    if [ -z "${ws_id}" ]; then
        elog "[workspace-seed] no uuid source, skipping"
        return 0
    fi
    mkdir -p "${store_dir}" 2>/dev/null || true
    ts="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
    elog "[workspace-seed] pre-seeding default workspace /opt/data/workspace"
    cat > "${ws_json}" <<EOF
{
  "unit": {
    "name": "workspace",
    "version": 2
  },
  "global": {
    "initialized": true,
    "workspaceIds": [
      "${ws_id}"
    ],
    "archivedSessionIds": [],
    "pinnedSessionIds": [],
    "defaultWorkspaceId": "${ws_id}"
  },
  "tables": {
    "workspaces": {
      "${ws_id}": {
        "path": "/opt/data/workspace",
        "title": "workspace",
        "sessionIds": [],
        "createdAt": "${ts}",
        "updatedAt": "${ts}"
      }
    }
  }
}
EOF
}

ensure_workspace_controller_row() {
    local web_dir="/data/dsh/profiles/web"
    local web_patch="${web_dir}/cordis.patch.yml"
    if [ ! -d "${web_dir}" ]; then
        elog "[workspace-seed] no web profile yet, skipping controller row"
        return 0
    fi
    if grep -q "documentsDirectory" "${web_patch}" 2>/dev/null; then
        elog "[workspace-seed] documentsDirectory already set, skipping"
        return 0
    fi
    elog "[workspace-seed] setting workspace-controller documentsDirectory"
    cat >> "${web_patch}" <<'EOF'
- id: workspace-controller
  config:
    documentsDirectory: /opt/data/workspace
EOF
}

retire_default_workspace_plugin() {
    local web_patch="/data/dsh/profiles/web/cordis.patch.yml"
    local dest_dir="/data/dsh/plugins/dsh-default-workspace"
    if [ -f "${web_patch}" ] && grep -Eq '^[[:space:]]+-[[:space:]]+id:[[:space:]]+default-workspace([[:space:]]|$)' "${web_patch}" 2>/dev/null; then
        elog "[workspace-seed] removing retired default-workspace plugin entry"
        /usr/local/bin/dsh-drop-patch-entry "${web_patch}" default-workspace 2>&1 | while IFS= read -r line; do elog "[workspace-seed] ${line}"; done || true
    fi
    if [ -f "${dest_dir}/package.json" ] && node -e "const p=require('${dest_dir}/package.json'); if(p.name!=='dsh-default-workspace') process.exit(1)" 2>/dev/null; then
        elog "[workspace-seed] removing stale plugin copy at ${dest_dir}"
        rm -rf "${dest_dir}" 2>/dev/null || true
    fi
}

# Writable dirs on the data volume (created as the runtime user — no chown).
mkdir -p "${HOME:-/data/dsh/home}" "${HOME:-/data/dsh/home}/.cache" 2>/dev/null || true
case "${TMPDIR:-/data/dsh/tmp}" in
    /data/dsh/*) mkdir -p "${TMPDIR}" 2>/dev/null || true ;;
esac
mkdir -p /data/dsh/home/.docker 2>/dev/null || true

# Auth plugin seed (@xgone/dsh-remote) into the web profile. Mirrors
# `dsh plugin --profile web add`: full seed tree + manifest merge, never
# overwrites cordis.patch.yml (user patch layer). cp --no-preserve because
# cap_drop:[ALL] lacks CAP_FOWNER.
SEED_DIR="/opt/dsh-remote-seed"
SEED_PLUGIN="${SEED_DIR}/node_modules/@xgone/dsh-remote/package.json"
WEB_DIR="/data/dsh/profiles/web"
if [ "${RESCUE_PROFILE}" = "web" ] && [ -f "${SEED_PLUGIN}" ]; then
    if node -e "const p=require('${WEB_DIR}/package.json'); if(!(p.dsh&&p.dsh.profile&&Array.isArray(p.dsh.profile.bundles)&&p.dsh.profile.bundles.includes('@xgone/dsh-remote'))) process.exit(1)" 2>/dev/null \
       && [ -f "${WEB_DIR}/node_modules/@xgone/dsh-remote/package.json" ]; then
        elog "[entrypoint] auth plugin seed already installed, skipping"
    else
        elog "[entrypoint] Installing auth plugin seed to web profile"
        mkdir -p "${WEB_DIR}/node_modules"
        CP="cp -r --no-preserve=mode,ownership,timestamps"
        rm -rf "${WEB_DIR}/node_modules"
        ${CP} "${SEED_DIR}/node_modules" "${WEB_DIR}/node_modules"
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do
            if [ -f "${SEED_DIR}/${f}" ]; then
                ${CP} "${SEED_DIR}/${f}" "${WEB_DIR}/${f}"
            fi
        done
        SEED_VER="$(node -p "require('${SEED_PLUGIN}').version")"
        node -e "
const fs=require('fs');
const pf='${WEB_DIR}/package.json';
let p={};
try { p=JSON.parse(fs.readFileSync(pf,'utf8')); } catch(e) { p={}; }
p.name='dsh-profile-web';
if (p.private!==false) p.private=true;
p.dependencies=Object.assign({},p.dependencies,{'@xgone/dsh-remote':'${SEED_VER}'});
p.dsh=p.dsh||{}; p.dsh.profile=p.dsh.profile||{};
const want=['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@xgone/dsh-remote'];
const have=Array.isArray(p.dsh.profile.bundles)?p.dsh.profile.bundles:[];
for (const b of want) if(!have.includes(b)) have.push(b);
p.dsh.profile.bundles=have;
fs.writeFileSync(pf,JSON.stringify(p,null,2)+'\n');
"
        if [ -f "${WEB_DIR}/cordis.patch.yml" ] \
           && cmp -s "${WEB_DIR}/cordis.patch.yml" "${SEED_DIR}/node_modules/@xgone/dsh-remote/cordis.patch.yml"; then
            cat > "${WEB_DIR}/cordis.patch.yml" <<'PPF'
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
[]
PPF
            elog "[entrypoint] restored user-layer cordis.patch.yml"
        fi
        elog "[entrypoint] Auth plugin seed installed"
    fi
fi

# Memory plugin seed (dsh-mnemon, joint tree). Same contract as above.
MNEMON_SEED_DIR="/opt/dsh-mnemon-seed"
MNEMON_SEED_PLUGIN="${MNEMON_SEED_DIR}/node_modules/dsh-mnemon/package.json"
if [ "${RESCUE_PROFILE}" = "web" ] && [ -f "${MNEMON_SEED_PLUGIN}" ]; then
    if node -e "const p=require('${WEB_DIR}/package.json'); if(!(p.dsh&&p.dsh.profile&&Array.isArray(p.dsh.profile.bundles)&&p.dsh.profile.bundles.includes('dsh-mnemon'))) process.exit(1)" 2>/dev/null \
       && [ -f "${WEB_DIR}/node_modules/dsh-mnemon/package.json" ]; then
        elog "[entrypoint] memory plugin seed already installed, skipping"
    else
        elog "[entrypoint] Installing memory plugin seed to web profile"
        mkdir -p "${WEB_DIR}/node_modules"
        CP="cp -r --no-preserve=mode,ownership,timestamps"
        rm -rf "${WEB_DIR}/node_modules"
        ${CP} "${MNEMON_SEED_DIR}/node_modules" "${WEB_DIR}/node_modules"
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do
            if [ -f "${MNEMON_SEED_DIR}/${f}" ]; then
                ${CP} "${MNEMON_SEED_DIR}/${f}" "${WEB_DIR}/${f}"
            fi
        done
        MNEMON_SEED_VER="$(node -p "require('${MNEMON_SEED_PLUGIN}').version")"
        node -e "
const fs=require('fs');
const pf='${WEB_DIR}/package.json';
let p={};
try { p=JSON.parse(fs.readFileSync(pf,'utf8')); } catch(e) { p={}; }
p.name='dsh-profile-web';
if (p.private!==false) p.private=true;
p.dependencies=Object.assign({},p.dependencies,{'dsh-mnemon':'${MNEMON_SEED_VER}'});
p.dsh=p.dsh||{}; p.dsh.profile=p.dsh.profile||{};
const want=['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','dsh-mnemon'];
const have=Array.isArray(p.dsh.profile.bundles)?p.dsh.profile.bundles:[];
for (const b of want) if(!have.includes(b)) have.push(b);
p.dsh.profile.bundles=have;
fs.writeFileSync(pf,JSON.stringify(p,null,2)+'\n');
"
        elog "[entrypoint] Memory plugin seed installed"
    fi
fi

# Durable automation seed (@michengai/dsh-automation, full joint tree with the
# auth+memory seeds). Same layout contract: installed wholesale (last copy
# wins on fresh volumes, all three blocks skip on steady state), manifest
# merge only ADDS the dep and bundle. cordis.patch.yml is NEVER overwritten.
# Gate with DSH_WITH_AUTOMATION=false to skip. Version pinned exact in .env.
AUTO_SEED_DIR="/opt/dsh-auto-seed"
AUTO_SEED_PLUGIN="${AUTO_SEED_DIR}/node_modules/@michengai/dsh-automation/package.json"
if [ "${DSH_WITH_AUTOMATION:-true}" = "true" ] && [ "${RESCUE_PROFILE}" = "web" ] && [ -f "${AUTO_SEED_PLUGIN}" ]; then
    if node -e "const p=require('${WEB_DIR}/package.json'); if(!(p.dsh&&p.dsh.profile&&Array.isArray(p.dsh.profile.bundles)&&p.dsh.profile.bundles.includes('@michengai/dsh-automation'))) process.exit(1)" 2>/dev/null \
       && [ -f "${WEB_DIR}/node_modules/@michengai/dsh-automation/package.json" ]; then
        elog "[entrypoint] automation plugin seed already installed, skipping"
    else
        elog "[entrypoint] Installing automation plugin seed to web profile"
        mkdir -p "${WEB_DIR}/node_modules"
        CP="cp -r --no-preserve=mode,ownership,timestamps"
        rm -rf "${WEB_DIR}/node_modules"
        ${CP} "${AUTO_SEED_DIR}/node_modules" "${WEB_DIR}/node_modules"
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do
            if [ -f "${AUTO_SEED_DIR}/${f}" ]; then
                ${CP} "${AUTO_SEED_DIR}/${f}" "${WEB_DIR}/${f}"
            fi
        done
        AUTO_SEED_VER="$(node -p "require('${AUTO_SEED_PLUGIN}').version")"
        node -e "
const fs=require('fs');
const pf='${WEB_DIR}/package.json';
let p={};
try { p=JSON.parse(fs.readFileSync(pf,'utf8')); } catch(e) { p={}; }
p.name='dsh-profile-web';
if (p.private!==false) p.private=true;
p.dependencies=Object.assign({},p.dependencies,{'@michengai/dsh-automation':'${AUTO_SEED_VER}'});
p.dsh=p.dsh||{}; p.dsh.profile=p.dsh.profile||{};
const want=['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@michengai/dsh-automation'];
const have=Array.isArray(p.dsh.profile.bundles)?p.dsh.profile.bundles:[];
for (const b of want) if(!have.includes(b)) have.push(b);
p.dsh.profile.bundles=have;
fs.writeFileSync(pf,JSON.stringify(p,null,2)+'\n');
"
        elog "[entrypoint] Automation plugin seed installed"
    fi
fi

# Automation tasks (official experimental schedule bundle). Manifest-only:
# the bundle ships inside the image and resolves from the dsh installation,
# so no node_modules copy is needed — selecting it in the plugin manager
# does exactly this append to dsh.profile.bundles. Gate with
# DSH_WITH_SCHEDULE=false to leave the shipped composition untouched.
if [ "${DSH_WITH_SCHEDULE:-true}" = "true" ] && [ "${RESCUE_PROFILE}" = "web" ]; then
    if node -e "const p=require('${WEB_DIR}/package.json'); if(!(p.dsh&&p.dsh.profile&&Array.isArray(p.dsh.profile.bundles)&&p.dsh.profile.bundles.includes('@deepseek-ai/dsh-experimental-schedule-bundle'))) process.exit(1)" 2>/dev/null; then
        elog "[entrypoint] schedule bundle already enabled, skipping"
    else
        elog "[entrypoint] Enabling Automation tasks (schedule bundle)"
        mkdir -p "${WEB_DIR}"
        node -e "
const fs=require('fs');
const pf='${WEB_DIR}/package.json';
let p={};
try { p=JSON.parse(fs.readFileSync(pf,'utf8')); } catch(e) { p={}; }
p.name='dsh-profile-web';
if (p.private!==false) p.private=true;
p.dsh=p.dsh||{}; p.dsh.profile=p.dsh.profile||{};
const want=['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@deepseek-ai/dsh-experimental-schedule-bundle'];
const have=Array.isArray(p.dsh.profile.bundles)?p.dsh.profile.bundles:[];
for (const b of want) if(!have.includes(b)) have.push(b);
p.dsh.profile.bundles=have;
fs.writeFileSync(pf,JSON.stringify(p,null,2)+'\n');
"
        elog "[entrypoint] Automation tasks enabled"
    fi
fi

retire_default_workspace_plugin
seed_workspace_registry
ensure_workspace_controller_row

start_socat

cleanup() {
    elog "[entrypoint] Received signal, shutting down..."
    if [ -n "${SOCAT_PID:-}" ] && kill -0 "${SOCAT_PID}" 2>/dev/null; then
        kill "${SOCAT_PID}" 2>/dev/null || true
        wait "${SOCAT_PID}" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup SIGTERM SIGINT SIGQUIT

elog "[entrypoint] starting dsh web (internal 127.0.0.1:${PORT_INNER})"
# shellcheck disable=SC2086
exec dsh --profile "${RESCUE_PROFILE}" --port "${PORT_INNER}" --no-open ${TRUSTED_ARGS}
