#!/bin/bash
# pai-stack — Minimal DSH Entrypoint
#
# Assumptions (see docker-compose.dsh.yaml):
# - PID 1 already runs as the host user via compose `user: "${UID}:${GID}"`.
#   No setpriv drop, no per-boot chown -R. Whatever this script creates is
#   owned correctly by creation.
# - Docker access is via the mounted /var/run/docker.sock + `group_add`
#   (no proxy socket). DOCKER_CONFIG lives on the data volume.
# - Workspace bind at ${WORKSPACE_PATH} is never chowned.
#
# This script only: ensures writable dirs, seeds plugins + default workspace
# registry, starts the 3080->3081 forwarder, execs `dsh web`.

set -euo pipefail

elog() { printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

# Container-internal workspace path. NOTE this is the IN-CONTAINER path, not
# the host path: every pai-stack service binds its ${WORKSPACE_DIR} host
# directory to this one target (docker-compose.yaml — hermes, terrain, dsh and
# open-design all use target /opt/data/workspace), so hermes and dsh agree on
# it by construction and share filepaths. Changing it means changing every
# mount target, which is why it is derived here once instead of at each call
# site below. Compose passes WORKSPACE_DIR because the directory-picker patch
# in the Dockerfile resolves it inside the container.
WORKSPACE_PATH="${WORKSPACE_DIR:-/opt/data/workspace}"

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

# Docker socket probe: cap_drop:[ALL] means `docker ps` only reports the
# container's effective caps, not the group_add-mounted socket — it cannot
# fail meaningfully here. A cheap -S test covers the real abort case.
if [ -S /var/run/docker.sock ]; then
    elog "[entrypoint] docker socket present, DOCKER_HOST=${DOCKER_HOST:-<default socket>}"
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
# Both paths derive from WORKSPACE_PATH so the seeded registry and the
# documentsDirectory row can never drift apart.
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
    elog "[workspace-seed] pre-seeding default workspace ${WORKSPACE_PATH}"
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
        "path": "${WORKSPACE_PATH}",
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
    cat >> "${web_patch}" <<EOF
- id: workspace-controller
  config:
    documentsDirectory: ${WORKSPACE_PATH}
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

# Disable DeepSeek-hosted web search; force local browser surfing.
# DSH ships `web.searchProvider: deepseek-official` (an Anthropic-messages
# model turn per query via api.deepseek.com). That cost + external dependency
# is off by default here: the agent surfs with local Playwright/Chromium
# (dsh-pai-web, no remote search API) + local fetch-http + notebook/terrain/
# mnemon. `tool-web.search:false` unregisters model-facing `web_search`
# (keeps `web_fetch`); `web-search-deepseek.disabled` stops the provider;
# `web.fetchProvider:http` drops the search pin. Patch replaces whole
# `config`, so tool-web restates every default (fetch 30s, search 60s).
# Gate with DSH_DISABLE_WEB_SEARCH=false to keep upstream search.
ensure_no_deepseek_search() {
    if [ "${DSH_DISABLE_WEB_SEARCH:-true}" != "true" ]; then
        elog "[websearch-seed] DSH_DISABLE_WEB_SEARCH=false, keeping DeepSeek search"
        return 0
    fi
    local web_dir="/data/dsh/profiles/web"
    local web_patch="${web_dir}/cordis.patch.yml"
    if [ ! -d "${web_dir}" ]; then
        elog "[websearch-seed] no web profile yet, skipping (applied on next boot)"
        return 0
    fi
    if grep -q "pai-stack: disable-deepseek-search" "${web_patch}" 2>/dev/null; then
        elog "[websearch-seed] DeepSeek search already disabled, skipping"
        return 0
    fi
    elog "[websearch-seed] disabling DeepSeek search (local Playwright + fetch-http instead)"
    mkdir -p "${web_dir}" 2>/dev/null || true
    touch "${web_patch}" 2>/dev/null || true
    cat >> "${web_patch}" <<'EOF'
# pai-stack: disable-deepseek-search (DSH_DISABLE_WEB_SEARCH=true).
# DeepSeek search costs a model turn per query; DSH surfs with local
# Playwright/Chromium (dsh-pai-web) + web-fetch-http + notebook/terrain/mnemon.
- id: tool-web
  config:
    search: false
    fetch: true
    searchMaxResults: 8
    searchMaxQueries: 4
    fetchTimeoutMs: 30000
    searchTimeoutMs: 60000
    fetchMaxOutputChars: 200000
- id: web-search-deepseek
  disabled: true
- id: web
  config:
    fetchProvider: http
EOF
}

# NOTE: seed_locale_preference() (and the DSH_SEED_LOCALE gate) is removed.
# It wrote /data/dsh/storages/locale.json, but nothing in the DSH server reads
# that store — DSH resolves UI locale from the request's Accept-Language header
# and server-side-renders it:
#     Accept-Language: en-US  ->  <html lang="en">     <title>… · Sign in</title>
#     Accept-Language: zh-CN  ->  <html lang="zh-CN">  <title>… · 登录</title>
# So the seed logged success every boot while changing nothing. Set the
# browser/OS language to English to get an English UI.
# Read a package.json "version" field without spawning Node (~13ms each).
# grep/sed are shell builtins with no interpreter startup; this replaces the
# former `node -p "require(...).version"` probes (10 per boot) in the
# plugin sync loop. Prints the version, or nothing if absent/invalid.
extract_pkg_version() {
    [ -f "$1" ] || return 0
    sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}

# Writable dirs on the data volume (created as the runtime user — no chown).
mkdir -p "${HOME:-/data/dsh/home}" "${HOME:-/data/dsh/home}/.cache" 2>/dev/null || true
case "${TMPDIR:-/data/dsh/tmp}" in
    /data/dsh/*) mkdir -p "${TMPDIR}" 2>/dev/null || true ;;
esac
mkdir -p /data/dsh/home/.docker 2>/dev/null || true

# Plugin seeds: ONE joint tree in the image (/opt/dsh-seed — all plugins
# resolved together at build time). The entrypoint copies it once and
# enforces gates at manifest level: only enabled plugins are listed in
# dependencies + dsh.profile.bundles, so disabled plugin code sits on disk
# but never loads. cordis.patch.yml (the user patch layer) is NEVER
# overwritten. cp --no-preserve because cap_drop:[ALL] lacks CAP_FOWNER.
#
# Table columns (pipe-separated):
#   id | runtime gate ("" = always on) | probe (in-tree package.json)
#   | dep name | extra same-version deps (space-separated)
# Runtime gates are DSH_WITH_* (.env.example §8): "false" drops the plugin
# from the manifest (code stays on disk, unloaded — it never *deletes*
# installed files). Build-time WITH_* (Dockerfile) only controls what is
# baked into the image — a runtime gate cannot install what was never baked.
# NOTE: extras share the probe (primary dep) version — the pai plugins are
# versioned in lockstep (see make dsh-versions-check).
sync_plugin_tree() {
    if [ "${RESCUE_PROFILE}" != "web" ]; then
        return 0
    fi
    local web_dir="${WEB_DIR:-/data/dsh/profiles/web}"
    # DSH_SEED_DIR override exists for offline testing (default = image path).
    local seed_dir="${DSH_SEED_DIR:-/opt/dsh-seed}"
    if [ ! -d "${seed_dir}/node_modules" ]; then
        elog "[entrypoint] no joint seed tree in image, skipping plugin sync"
        return 0
    fi
    local need_copy=0
    local managed=""
    local id gate probe dep extras gate_val seed_ver live_ver d
    while IFS='|' read -r id gate probe dep extras; do
        [ -n "${id}" ] || continue
        gate_val="true"
        if [ -n "${gate}" ]; then
            gate_val="${!gate:-true}"
        fi
        if [ "${gate_val}" != "true" ]; then
            # shellcheck disable=SC2086 — intentional word splitting of the table field
            for d in "${dep}" ${extras}; do
                managed="${managed},'${d}':null"
            done
            continue
        fi
        seed_ver="$(extract_pkg_version "${seed_dir}/node_modules/${probe}")"
        if [ -z "${seed_ver}" ]; then
            elog "[entrypoint] ${id} plugin not baked into image, skipping"
            # shellcheck disable=SC2086 — intentional word splitting of the table field
            for d in "${dep}" ${extras}; do
                managed="${managed},'${d}':null"
            done
            continue
        fi
        live_ver="$(extract_pkg_version "${web_dir}/node_modules/${probe}")"
        if [ "${seed_ver}" != "${live_ver}" ]; then
            need_copy=1
        fi
        # shellcheck disable=SC2086 — intentional word splitting of the table field
        for d in "${dep}" ${extras}; do
            managed="${managed},'${d}':'${seed_ver}'"
        done
    done <<'PLUGIN_TABLE'
auth|DSH_WITH_AUTH|@xgone/dsh-remote/package.json|@xgone/dsh-remote|
memory|DSH_WITH_MNEMON|dsh-mnemon/package.json|dsh-mnemon|
automation|DSH_WITH_AUTOMATION|@michengai/dsh-automation/package.json|@michengai/dsh-automation|
rewind|DSH_WITH_REWIND|dsh-rewind-plugin/package.json|dsh-rewind-plugin|
auto-continue|DSH_WITH_AUTOCONTINUE|dsh-client-auto-continue/package.json|dsh-client-auto-continue|
suggest-prompt|DSH_WITH_SUGGEST_PROMPT|@studyzy/dsh-suggest-prompt/package.json|@studyzy/dsh-suggest-prompt|
prompt-library|DSH_WITH_PROMPT_LIBRARY|@sunjuntao/dsh-prompt-library/package.json|@sunjuntao/dsh-prompt-library|
telegram|DSH_WITH_TELEGRAM|dsh-pai-telegram/package.json|dsh-pai-telegram|
pai|DSH_WITH_PAI_PLUGINS|dsh-pai-notebook/package.json|dsh-pai-notebook|dsh-pai-adr dsh-pai-design dsh-pai-terrain dsh-pai-git dsh-pai-web
PLUGIN_TABLE
    if [ "${need_copy}" = 1 ] || [ ! -d "${web_dir}/node_modules" ]; then
        elog "[entrypoint] Installing joint plugin tree to web profile"
        mkdir -p "${web_dir}/node_modules"
        rm -rf "${web_dir}/node_modules"
        cp -r --no-preserve=mode,ownership,timestamps "${seed_dir}/node_modules" "${web_dir}/node_modules"
        local f
        for f in pnpm-lock.yaml pnpm-workspace.yaml; do
            if [ -f "${seed_dir}/${f}" ]; then
                cp -r --no-preserve=mode,ownership,timestamps "${seed_dir}/${f}" "${web_dir}/${f}"
            fi
        done
        elog "[entrypoint] Plugin tree installed"
    else
        elog "[entrypoint] Plugin tree already installed, skipping"
    fi
    # Reconcile the manifest: managed deps/bundles match the gates exactly;
    # anything else in the manifest (user-added via `dsh plugin add`) is
    # preserved. Writes only on change.
    node -e "
const fs=require('fs');
const pf='${web_dir}/package.json';
let p={};
try { p=JSON.parse(fs.readFileSync(pf,'utf8')); } catch(e) { p={}; }
p.name='dsh-profile-web';
if (p.private!==false) p.private=true;
if (!p.dependencies || typeof p.dependencies !== 'object') p.dependencies={};
const managed={${managed#,}};
let changed=false;
for (const name of Object.keys(managed)) {
    const want=managed[name];
    if (want == null) {
        if (name in p.dependencies) { delete p.dependencies[name]; changed=true; }
    } else if (p.dependencies[name] !== want) {
        p.dependencies[name]=want; changed=true;
    }
}
p.dsh=p.dsh||{}; p.dsh.profile=p.dsh.profile||{};
const base=['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'];
const wantBundles=base.concat(Object.keys(managed).filter((n)=>managed[n] != null));
const have=Array.isArray(p.dsh.profile.bundles)?p.dsh.profile.bundles:[];
const managedSet=new Set(Object.keys(managed));
const next=[];
for (const b of have) {
    if (managedSet.has(b) && !wantBundles.includes(b)) { changed=true; continue; }
    if (!next.includes(b)) next.push(b);
}
for (const b of wantBundles) {
    if (!next.includes(b)) { next.push(b); changed=true; }
}
if (JSON.stringify(next) !== JSON.stringify(have)) { p.dsh.profile.bundles=next; changed=true; }
if (changed) {
    fs.writeFileSync(pf,JSON.stringify(p,null,2)+'\n');
    console.log('[entrypoint] manifest reconciled to gates');
} else {
    console.log('[entrypoint] manifest in sync, skipping');
}
"
    # Auth only: if the live patch layer is byte-identical to the shipped
    # bundle patch, it was never personalized — restore the empty user layer.
    if [ -f "${web_dir}/cordis.patch.yml" ] \
       && cmp -s "${web_dir}/cordis.patch.yml" "${seed_dir}/node_modules/@xgone/dsh-remote/cordis.patch.yml"; then
        cat > "${web_dir}/cordis.patch.yml" <<'PPF'
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
[]
PPF
        elog "[entrypoint] restored user-layer cordis.patch.yml"
    fi
}

WEB_DIR="/data/dsh/profiles/web"
sync_plugin_tree

# Playwright library into the live web profile (for pre-existing volumes).
# The joint seed carries node_modules/playwright since the image build, but
# volumes synced before that lack it. Copy iff missing — never overwrites
# cordis.patch.yml.
if [ "${RESCUE_PROFILE}" = "web" ] && [ -d "/opt/dsh-seed/node_modules/playwright" ] && [ ! -f "${WEB_DIR}/node_modules/playwright/package.json" ]; then
    elog "[entrypoint] Installing playwright library into live web profile"
    mkdir -p "${WEB_DIR}/node_modules" 2>/dev/null || true
    CP="cp -r --no-preserve=mode,ownership,timestamps"
    rm -rf "${WEB_DIR}/node_modules/playwright"
    ${CP} "/opt/dsh-seed/node_modules/playwright" "${WEB_DIR}/node_modules/playwright"
    elog "[entrypoint] Playwright library installed"
fi

# Automation tasks (official experimental schedule bundle). Manifest-only:
# the bundle ships inside the image and resolves from the dsh installation,
# so no node_modules copy is needed — selecting it in the plugin manager
# does exactly this append to dsh.profile.bundles. Gate with
# DSH_WITH_SCHEDULE=false to leave the shipped composition untouched.
if [ "${RESCUE_PROFILE}" = "web" ]; then
    if [ "${DSH_WITH_SCHEDULE:-true}" = "true" ]; then
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
        fi
    else
        # DSH_WITH_SCHEDULE=false: remove the schedule bundle if present
        if node -e "const p=require('${WEB_DIR}/package.json'); if(!(p.dsh&&p.dsh.profile&&Array.isArray(p.dsh.profile.bundles)&&p.dsh.profile.bundles.includes('@deepseek-ai/dsh-experimental-schedule-bundle'))) process.exit(1)" 2>/dev/null; then
            elog "[entrypoint] Disabling Automation tasks (schedule bundle)"
            mkdir -p "${WEB_DIR}"
            node -e "
const fs=require('fs');
const pf='${WEB_DIR}/package.json';
let p=JSON.parse(fs.readFileSync(pf,'utf8'));
if (p.dsh && p.dsh.profile && Array.isArray(p.dsh.profile.bundles)) {
    p.dsh.profile.bundles = p.dsh.profile.bundles.filter(b => b !== '@deepseek-ai/dsh-experimental-schedule-bundle');
    fs.writeFileSync(pf,JSON.stringify(p,null,2)+'\n');
}
"
fi
    fi
fi

# English seed data for @sunjuntao/dsh-prompt-library. The plugin hardcodes a
# CHINESE first-run seed (welcome prompt, tag, three starter persona prompts
# and the default SOUL persona) into its SQLite db — it has no locale switch
# and seeds regardless of UI language, which reads oddly in an English-only
# stack (screenshots, Oct-2026). This patch rewrites ONLY rows that still
# match the exact Chinese seed text; anything the user edited or created is
# never touched, and translations stay idempotent across plugin updates.
# Gate with DSH_PROMPT_LIBRARY_ENGLISH=false to keep the upstream seed.
ensure_prompt_library_english() {
    if [ "${DSH_PROMPT_LIBRARY_ENGLISH:-true}" != "true" ]; then
        return 0
    fi
    local db="${DSH_HOME:-/data/dsh}/prompt-library/db/prompts.db"
    if [ ! -f "${db}" ]; then
        return 0
    fi
    local patch="/tmp/pl-english-patch.mjs"
    cat > "${patch}" <<'PLEOF'
// Guarded upsert: each UPDATE touches a row only when its body STILL equals
// the known Chinese seed fragment — user-modified rows fail the WHERE and are
// left alone. Uses the same node:sqlite the plugin itself runs on (Node 24).
import { DatabaseSync } from 'node:sqlite';
const db = new DatabaseSync(process.argv[2] ?? '/data/dsh/prompt-library/db/prompts.db');
const CH = {
  welcomeTitle: '欢迎使用词库',
  welcomeBodyFrag: '这是你保存的第一条提示词',
  personaKey: 'pl:default-persona-soul',
};
const updates = [];

// 1. Welcome prompt (only if seed-intact)
updates.push(
  db.prepare(`UPDATE prompts SET title=?, body=?, tags=? WHERE title=? AND body LIKE ?`)
    .run('Welcome to Prompt Library',
`This is your first saved prompt and the library's quick-start guide.

Ways to use this plugin:
- Open Data Management in the Library menu to browse, edit and search the whole library;
- Use the AI Polish button next to the chat input to refine selected text;
- Use Import/Export to back up or restore the entire library.

Edit this prompt directly to replace it with your own content, and tag it in settings.`,
      '["welcome"]',
      CH.welcomeTitle, `%${CH.welcomeBodyFrag}%`));

// 2. Seed tag (only if untouched)
updates.push(
  db.prepare(`UPDATE tags SET name=? WHERE name=? AND NOT EXISTS
    (SELECT 1 FROM tags WHERE name=?)`).run('welcome', '欢迎', 'welcome'));

// 3. Starter persona prompts (exact-body match each)
const starts = [
  ['Programming',
`You are a senior full-stack engineer versed in mainstream languages, frameworks and engineering practice. When answering programming questions:
1. Confirm requirements and constraints first, asking clarifying questions where needed;
2. Give runnable code examples and explain the key implementation idea;
3. Point out common pitfalls and edge cases, with defensive coding patterns;
4. When several approaches exist, compare trade-offs and give a clear recommendation.`,
    '编程', `["编程"]`, `["programming"]`,
    '你是一名资深全栈工程师'],
  ['Office writing',
`You are an experienced office administrator skilled in formal documents, meeting minutes, spreadsheets and daily admin work. For office tasks:
1. Use formal, precise written style — clear and concise;
2. Structure content with clear sub-headings and lists;
3. Provide templates or examples that can be used directly;
4. Mind formatting, wording and professional conventions.`,
    '文员', `["文员"]`, `["office"]`,
    '你是一名经验丰富的办公室文员'],
  ['Legal review',
`You are a rigorous professional lawyer skilled in legal advice, document drafting and compliance analysis. For legal questions:
1. Base analysis on current laws, regulations and judicial interpretations;
2. Flag potential legal risks and liability boundaries;
3. Use standard legal drafting conventions or model clauses;
4. Where individual circumstances matter, state the limits and advise consulting a licensed attorney.`,
    '律师', `["律师"]`, `["legal"]`,
    '你是一名严谨专业的律师'],
];
for (const [t, body, zhTitle, zhTags, enTags, frag] of starts) {
  updates.push(
    db.prepare(`UPDATE session_prompts SET title=?, body=?, tags=? WHERE title=? AND body LIKE ? AND usageCount=0`)
      .run(t, body, enTags, zhTitle, `%${frag}%`));
}

// 4. Default persona (drives AI-polish output language). Replaced only while
// it still IS the Chinese seed — user-maintained personas win.
const persona = db.prepare('SELECT value FROM meta WHERE key=?').get(CH.personaKey);
if (persona && persona.value.includes('人格')) {
  updates.push(
    db.prepare('UPDATE meta SET value=? WHERE key=? AND value=?').run(
`# SOUL · Persona

You are the Prompt Library assistant — the user's everyday tool for collecting, organizing, polishing and reusing prompts.

## Identity
- An expert in prompt writing across writing, coding, office and learning scenarios.
- Detail-oriented; output that is concise, generic and reusable.

## Working principles
- Understand the user's real intent before editing; keep the key details of the original text — never rewrite gratuitously.
- When classifying or distilling, keep prompts clear, compact and directly usable.
- Extract scenario-dependent content (roles, objects, topics, style) into variable placeholders for reuse.
- Preserve existing variables and tag structures; never break existing formats.

## Expression style
- Sincere, clear and organized; the conclusion first, then the necessary explanation.
- Respect the user's input; suggest only when genuinely needed.

## Language
- Respond in English by default; mirror the user's language only when they clearly write in another one.`,
      CH.personaKey, persona.value));
}

const n = updates.reduce((a, r) => a + r.changes, 0);
if (n) console.log(`[pl-english] localized ${n} seeded row(s)`);
else console.log('[pl-english] seed already localized or user-modified, skipping');
PLEOF
    local out
    if out="$(node "${patch}" "${db}" 2>&1)"; then
        # `node | while read` would eat node's exit status (read returns 1 at
        # EOF), so capture first and stream after — the `if` must test node.
        printf '%s\n' "${out}" | while IFS= read -r line; do elog "${line}"; done
        rm -f "${patch}"
    else
        printf '%s\n' "${out}" | while IFS= read -r line; do elog "${line}"; done
        elog "[pl-english] WARN patch failed (plugin update changed the schema?) — keeping Chinese seed"
        rm -f "${patch}"
    fi
}

retire_default_workspace_plugin
seed_workspace_registry
ensure_workspace_controller_row
ensure_no_deepseek_search
ensure_prompt_library_english

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
