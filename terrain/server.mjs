#!/usr/bin/env node
/**
 * Terrain service shim — HTTP front end for the `terrain` CLI.
 *
 * Terrain ships as a CLI only (no serve/daemon subcommand). pai-stack agents
 * need a network endpoint, so this process owns the binary and exposes it:
 *
 *   POST /call   { action, params }   → Hermes (pai_terrain_ops), DSH (dsh-pai-terrain)
 *   GET  /healthz                    → compose healthcheck + both clients' probes
 *
 * One transport, two consumers. Both plugins already speak POST /call.
 *
 * LLM PATH — `init` and `ask` do NOT use llm-gateway. Terrain spawns
 * `opencode acp` as a subprocess, and opencode runs on its own keyless Zen
 * models. The model is RESOLVED AT BOOT (largest keyless context window, see
 * listKeylessModels) from the template in terrain/opencode.json. This
 * container therefore holds no gateway link and no provider credential. See
 * PROVIDER_KEYS below for why that is enforced rather than assumed.
 *
 * SAFETY — three invariants this file exists to enforce:
 *   1. Subcommand allowlist. `terrain env apply` rewrites AGENTS.md and installs
 *      preset skills from `.agents/skills`, overwriting files pai-stack owns, so
 *      the whole `env` tree is unreachable. Same for `sdd`, `settings`, `usage`
 *      and the raw `tools` agent surface.
 *   2. Path confinement. Index targets must resolve inside TERRAIN_WORKSPACE.
 *      Without this, any agent holding this tool could ask terrain to walk
 *      /var/lib/terrain or the container image itself.
 *   3. Credential stripping. See PROVIDER_KEYS.
 */

import { createServer } from 'node:http'
import { spawn, execFile } from 'node:child_process'
import { realpathSync, existsSync, lstatSync, unlinkSync } from 'node:fs'
import { readFileSync, writeFileSync, renameSync, mkdirSync, statSync } from 'node:fs'
import { resolve, join, dirname, isAbsolute } from 'node:path'

const PORT = Number(process.env.TERRAIN_PORT ?? 7878)
const WORKSPACE = resolve(process.env.TERRAIN_WORKSPACE ?? '/opt/data/workspace')
const TOKEN = process.env.TERRAIN_TOKEN || null

/**
 * The ACP agent's config TEMPLATE, as shipped in the image. The shim resolves
 * the final model at boot (listKeylessModels / resolveAcpModel) and WRITES the
 * resolved config into the volume — this image copy stays the source of truth
 * for everything else in the file (the litho agent definition, permissions)
 * and the fallback model when live selection is impossible.
 */
const ACP_CONFIG_SRC = '/opt/terrain/opencode.json'

/**
 * Boot-time model resolution.
 *
 * A pinned keyless Zen slug is a liability: the pool changes under us, slugs
 * get retired upstream with no notice, and `opencode models` is the only
 * ground truth. So at every boot the shim:
 *
 *   1. Seeds $XDG_CONFIG_HOME/opencode/opencode.json from the template
 *      immediately (non-fatal — only init/ask are affected).
 *   2. In the background, lists the LIVE keyless pool (`opencode models`,
 *      retried — see below) and, when models.dev is reachable, picks the model
 *      with the LARGEST context window (Litho has to fit a whole repo) and
 *      rewrites the config.
 *
 * The ranking is identical to scripts/opencode-free-models.py, which remains
 * the host-side tool for inspecting the same pool (`make free-models`). The
 * same two-source rule applies here: availability comes ONLY from
 * `opencode models`; models.dev is a catalog — it listed retired slugs at
 * cost 0 for weeks. It is used only for context/output windows, and a model is
 * picked only on a KNOWN window. When models.dev is unreachable every window
 * is 0, "largest" is meaningless, and the template fallback is kept rather
 * than picking alphabetically.
 *
 * `TERRAIN_ACP_MODEL` pins the choice explicitly and skips selection (still
 * verified live; an unverifiable pin only warns — never fatal: scan/search/
 * read/source are all offline and must keep working when models are gone).
 */
const ACP_MODEL_OVERRIDE = process.env.TERRAIN_ACP_MODEL || null

/** Alias whose backing model can change without the slug changing (docs/terrain.md). */
const UNSTABLE_ALIASES = new Set(['big-pickle'])

function acpConfigPath() {
  return process.env.XDG_CONFIG_HOME
    ? join(process.env.XDG_CONFIG_HOME, 'opencode', 'opencode.json')
    : null
}

function readTemplateModel() {
  try {
    return JSON.parse(readFileSync(ACP_CONFIG_SRC, 'utf8')).model ?? 'unset'
  } catch {
    return 'unreadable'
  }
}

/**
 * Write opencode's config into XDG with `model` set to what we resolved.
 *
 * Rewritten from the template on EVERY boot rather than seeded only when
 * absent: "write only if missing" is exactly how a hand-edited or stale copy
 * outlives the image and pins a dead model forever. Atomic write (tmp +
 * rename) so an `opencode acp` subprocess racing it reads either the old or
 * the new file, never a partial one.
 */
function writeAcpConfig(model = null) {
  const dst = acpConfigPath()
  if (!dst || !existsSync(ACP_CONFIG_SRC)) return
  try {
    const cfg = JSON.parse(readFileSync(ACP_CONFIG_SRC, 'utf8'))
    if (model) cfg.model = model
    const dir = dirname(dst)
    mkdirSync(dir, { recursive: true })
    const tmp = join(dir, `.opencode.json.${process.pid}.tmp`)
    writeFileSync(tmp, JSON.stringify(cfg, null, 2) + '\n')
    // A boot from the pre-resolution shim left a SYMLINK here (to the image
    // copy); lstat it deliberately — existsSync follows links, so a broken one
    // reads as absent and rename would then refuse to replace it.
    try { if (lstatSync(dst).isSymbolicLink()) unlinkSync(dst) } catch { /* absent */ }
    renameSync(tmp, dst)
  } catch (e) {
    console.error(`[terrain] could not write ACP config: ${e.message} (init/ask may be unavailable)`)
  }
}

/**
 * Read the model the ACP agent will actually use, for the banner and
 * /healthz — the RESOLVED config first, template as fallback.
 *
 * Worth logging because these keyless Zen models get retired upstream with no
 * deprecation here: a retired model makes `init`/`ask` fail while `terrain
 * settings check-acp` still reports `available: true`, because that only
 * proves the BINARY exists. The banner is the one place that shows which
 * model is actually wired up.
 */
function acpModel() {
  const dst = acpConfigPath()
  for (const f of [dst, ACP_CONFIG_SRC]) {
    if (!f) continue
    try {
      const m = JSON.parse(readFileSync(f, 'utf8')).model
      if (m) return m
    } catch { /* try the next source */ }
  }
  return 'unreadable'
}

const MODELS_DEV = 'https://models.dev/api.json'
const CATALOG_TTL_MS = 6 * 3600 * 1000

/**
 * context/output windows from models.dev, cached ~6h (same policy as
 * scripts/opencode-free-models.py). Returns {} on any failure: a machine with
 * no network still gets a usable fallback (the template pin), it just loses
 * the ranking. Advisory only — never authoritative on availability.
 */
async function readCatalog() {
  const cache = process.env.OPENCODE_MODEL_CACHE
    ? resolve(process.env.OPENCODE_MODEL_CACHE)
    : join(process.env.HOME ?? '/var/lib/terrain', '.cache', 'opencode-models.json')
  try {
    if (Date.now() - statSync(cache).mtimeMs < CATALOG_TTL_MS) {
      return JSON.parse(readFileSync(cache, 'utf8'))
    }
  } catch { /* cache miss */ }
  try {
    // models.dev 403s a missing User-Agent; identify honestly.
    const body = await fetch(MODELS_DEV, {
      headers: { 'User-Agent': 'pai-stack/terrain-shim' },
      signal: AbortSignal.timeout(15000),
    }).then((r) => r.json())
    const limits = {}
    for (const [mid, mm] of Object.entries(body?.opencode?.models ?? {})) {
      // Keys here are BARE model ids (no "opencode/" prefix), even though
      // `opencode models` prints them prefixed — same normalisation as the
      // Python sibling script.
      const id = mid.startsWith('opencode/') ? mid.slice('opencode/'.length) : mid
      limits[id] = {
        context: mm?.limit?.context ?? 0,
        output: mm?.limit?.output ?? 0,
        status: mm?.status ?? '',
      }
    }
    mkdirSync(dirname(cache), { recursive: true })
    writeFileSync(cache, JSON.stringify(limits))
    return limits
  } catch {
    return {}
  }
}

/**
 * Rank the live pool: context first (Litho has to fit a whole repo), output
 * second, name last so the choice is stable across boots when the catalog is
 * unreachable. Mirrors scripts/opencode-free-models.py exactly.
 */
function rankModels(live, limits) {
  return live
    .map((id) => {
      const short = id.startsWith('opencode/') ? id.slice('opencode/'.length) : id
      const lim = limits[short] ?? {}
      return {
        id,
        short,
        context: lim.context ?? 0,
        output: lim.output ?? 0,
        status: lim.status ?? '',
      }
    })
    .sort((a, b) => (b.context - a.context) || (b.output - a.output) || a.short.localeCompare(b.short))
}

function pickBestModel(rows) {
  // Upstream-deprecated slugs and the big-pickle alias are poor choices for a
  // knowledge corpus, but advisory only: skip them ONLY while some other live
  // model remains — an all-warned pool still gets one.
  const stable = rows.filter((r) => r.status !== 'deprecated' && !UNSTABLE_ALIASES.has(r.short))
  const pool = stable.length ? stable : rows
  // Pick on a KNOWN window only — see the two-source rule at the top.
  if (!pool.length || !pool[0].context) return null
  return pool[0]
}

/**
 * List the live keyless pool, then resolve + apply the ACP model.
 *
 * `opencode models` fails falsely cold: it exits 0 with EMPTY stdout while its
 * background server (opencode.db + WAL) is still coming up. An empty answer is
 * INCONCLUSIVE, not a verdict — retry before concluding anything. Never fatal:
 * scan/search/read/source are all offline and must keep working when the model
 * is gone.
 */
function listKeylessModels(attempt = 1) {
  const ATTEMPTS = 3
  execFile('opencode', ['models'], { timeout: 15000, env: process.env }, (err, stdout) => {
    const live = (stdout || '').split('\n').map((l) => l.trim()).filter(Boolean)

    if (err || live.length === 0) {
      if (attempt < ATTEMPTS) {
        setTimeout(() => listKeylessModels(attempt + 1), 1500)
        return
      }
      console.error(
        `[terrain] could not list keyless models (${err ? err.message : '`opencode models` returned nothing'}) — ` +
        `keeping template-pinned ACP model ${acpModel()}`
      )
      return
    }
    resolveAcpModel(live)
  })
}

async function resolveAcpModel(live) {
  const fallback = readTemplateModel()

  if (ACP_MODEL_OVERRIDE) {
    if (live.includes(ACP_MODEL_OVERRIDE)) {
      writeAcpConfig(ACP_MODEL_OVERRIDE)
      console.error(`[terrain] ACP model ${ACP_MODEL_OVERRIDE} pinned via TERRAIN_ACP_MODEL, verified against ${live.length} keyless model(s)`)
    } else {
      console.error(
        `[terrain] ERROR: TERRAIN_ACP_MODEL ${ACP_MODEL_OVERRIDE} is NOT available keylessly — init and ask WILL FAIL.\n` +
        `           Live alternatives:\n` +
        live.slice(0, 5).map((m) => `             ${m}`).join('\n') +
        `\n           Falling back to the template pin (${fallback}). Unset TERRAIN_ACP_MODEL to re-enable boot-time selection.`
      )
    }
    return
  }

  const limits = await readCatalog()
  const pick = pickBestModel(rankModels(live, limits))
  if (!pick) {
    // No ranking info (models.dev unreachable or empty contexts). The
    // template pin is the fallback — report whether it is still alive.
    if (live.includes(fallback)) {
      console.error(`[terrain] ACP model ${fallback} verified keyless — no catalog to rank by context window, keeping the template pin`)
    } else {
      console.error(
        `[terrain] ERROR: template ACP model ${fallback} is NOT available keylessly and no context data arrived to rank with — init and ask WILL FAIL.\n` +
        `           Live alternatives:\n` +
        live.slice(0, 5).map((m) => `             ${m}`).join('\n') +
        `\n           Set TERRAIN_ACP_MODEL to one of these, or fix network access to models.dev.`
      )
    }
    return
  }

  if (pick.id === fallback) {
    console.error(`[terrain] ACP model ${pick.id} verified keyless — already the largest keyless context window (${pick.context.toLocaleString()})`)
    return
  }
  writeAcpConfig(pick.id)
  console.error(
    `[terrain] ACP model auto-selected: ${pick.id} (context ${pick.context.toLocaleString()}) — ` +
    `template pin ${fallback} retired or smaller`
  )
}

/** Actions exposed to agents. Anything not listed here is unreachable. */
const FORBIDDEN = new Set(['env', 'sdd', 'settings', 'usage', 'tools'])

/**
 * Provider credentials that must never reach terrain's ACP agent.
 *
 * `init` and `ask` work ONLY while these are absent. Terrain does not write its
 * knowledge assets through an OpenAI-compatible endpoint — it spawns `opencode
 * acp`, and if opencode finds a provider credential it resolves the ACP session
 * to a catalog model instead of keyless Zen. Both actions then die with no
 * useful error.
 *
 * Compose already guarantees this: the terrain service declares an explicit
 * `environment:` map with no `env_file:` and no `- VAR` passthrough, so nothing
 * in .env reaches the container. This is belt-and-braces for `docker run -e`, a
 * future `env_file:`, or a hand-edit of the compose block.
 *
 * Deleted, not blanked. `ENV FOO=""` leaves FOO *defined*, and provider
 * selection branches on presence rather than truthiness — blanking would trade a
 * guaranteed-absent variable for an ambiguous one.
 */
const PROVIDER_KEYS = [
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
  'OPENROUTER_API_KEY',
  'NVIDIA_API_KEY',
]

/** action → { bin: [argv prefix], repoFlag?: boolean } */
const ACTIONS = {
  index: { bin: ['scan'] },
  init: { bin: ['init'] },
  refresh: { bin: ['refresh'] },
  search: { bin: ['search'] },
  read: { bin: ['read'] },
  overview: { bin: ['project', 'overview'] },
  projects: { bin: ['project', 'list'] },
  unregister: { bin: ['project', 'remove'] },
  // `source` is the one action whose two path params have DIFFERENT bases, and
  // both clients got this wrong independently. `path` → --repo-path,
  // repo-relative; `file` → --file, workspace-relative, so a bare "README.md"
  // resolves to /opt/data/workspace/README.md and fails. repoFlag switches
  // buildArgv to the --repo-path convention.
  source: { bin: ['source', 'read'], repoFlag: true },
  ask: { bin: ['ask', 'query'] },
}

// ── per-repo serialisation ───────────────────────────────────────────────────
// Two concurrent mutating runs against one repo interleave writes into .terrain/
// and corrupt it. Terrain tracks git HEAD itself, so we cannot lean on
// that. See run(): the chain key is the repo, not the action.
const chains = new Map()
function serialise(key, fn) {
  const prev = chains.get(key) ?? Promise.resolve()
  const next = prev.then(fn, fn)
  chains.set(key, next.catch(() => {}))
  return next
}

// ── path confinement ─────────────────────────────────────────────────────────
// `what` only labels the error — the check is identical for files and dirs.
function confine(p, what = 'directory') {
  if (!p) return WORKSPACE
  const abs = isAbsolute(p) ? resolve(p) : resolve(WORKSPACE, p)
  if (abs !== WORKSPACE && !abs.startsWith(WORKSPACE + '/')) {
    throw Object.assign(new Error(`path escapes workspace: ${p}`), { status: 403 })
  }
  if (!existsSync(abs)) {
    throw Object.assign(new Error(`no such ${what}: ${abs}`), { status: 400 })
  }
  try {
    const real = realpathSync(abs)
    if (real !== WORKSPACE && !real.startsWith(WORKSPACE + '/')) {
      throw Object.assign(new Error(`path resolves outside workspace: ${p}`), { status: 403 })
    }
  } catch (e) {
    if (e.status) throw e
  }
  return abs
}

// ── argv construction ────────────────────────────────────────────────────────
// spawn() with an argv array — never a shell string, so params cannot inject.
function buildArgv(action, params = {}) {
  const spec = ACTIONS[action]
  if (!spec) throw Object.assign(new Error(`unknown action: ${action}`), { status: 400 })
  if (spec.bin.some((a) => FORBIDDEN.has(a))) {
    throw Object.assign(new Error(`action ${action} is blocked`), { status: 403 })
  }

  const argv = [...spec.bin]

  // Two different repo-targeting conventions. Registry-based commands
  // (search/overview/ask) take `--project <slug>`; `source read` takes
  // `--repo-path <abs>` and rejects --project outright. Emitting the wrong one
  // fails the whole call, so branch on the spec rather than guessing.
  if (spec.repoFlag) {
    const rp = params.repo_path ?? params.path
    if (rp) argv.push('--repo-path', confine(rp))
  } else {
    for (const k of ['path', 'repo_path']) {
      if (params[k]) argv.push(confine(params[k]))
    }
  }

  // `terrain source read` is a SUBCOMMAND taking --file/--start-line/--end-line.
  // This used to push a bare positional, so every call died with
  // "unrecognized subcommand '<file>'" and the action was unusable.
  // `--file` is a caller-supplied path, so it is confined like every
  // other path — otherwise `source` could read outside the workspace.
  if (params.file) argv.push('--file', confine(params.file, 'file'))
  if (params.start_line != null) argv.push('--start-line', String(Math.max(1, Number(params.start_line) || 1)))
  if (params.end_line != null) argv.push('--end-line', String(Math.max(1, Number(params.end_line) || 1)))
  if (params.query) argv.push(String(params.query))
  if (params.project && !spec.repoFlag) argv.push('--project', String(params.project))
  if (params.slug) argv.push('--slug', String(params.slug))
  if (params.limit != null) argv.push('--limit', String(Math.max(1, Number(params.limit) || 20)))

  return argv
}

function run(action, params) {
  const argv = buildArgv(action, params)
  // Key on the TARGET for mutating actions, not on the action.
  // `index` and `refresh` both write the same .terrain/ directory, so
  // they must not run concurrently even though they are different actions.
  // Read-only actions carry an empty key, which never collides with a
  // mutating one, so they stay concurrent.
  const mutating = ['index', 'refresh', 'init'].includes(action)
  const key = (mutating ? 'write|' : 'read|') + (params.path ?? '')

  // Terrain's registry must stay off the shared workspace mount, and no
  // provider key may reach the ACP grandchild. Built once per call rather than
  // mutating process.env, so the shim's own view is never altered.
  const childEnv = { ...process.env, HOME: process.env.HOME ?? '/var/lib/terrain' }
  for (const k of PROVIDER_KEYS) delete childEnv[k]

  // Terrain's `git` collector (declared in .terrain/.meta/sync.json) runs inside
  // this container, where the bind-mounted repo is owned by the host UID while we
  // run as uid 1000. Git 2.35.2+ refuses every command in that situation
  // ("detected dubious ownership"), and terrain does not surface the failure —
  // it records the consequence instead. The drift ledger then claims
  // commits_since_baseline=0 (i.e. "the index is current") no matter how far
  // the repo has actually advanced, stale_reason comes out as
  // "baseline_unreachable", and tech-stack detection silently yields nothing.
  //
  // Passed as environment rather than written to $HOME/.gitconfig: per-spawn,
  // no persisted state to go stale, and no secret or config baked into a layer.
  // `*` is scoped to this container's filesystem view, which is the read-only
  // image plus the workspace bind. A static path list would break on the next
  // project — the workspace is multi-project by design.
  childEnv.GIT_CONFIG_COUNT = '1'
  childEnv.GIT_CONFIG_KEY_0 = 'safe.directory'
  childEnv.GIT_CONFIG_VALUE_0 = '*'

  return serialise(key, () => new Promise((res) => {
    const child = spawn('terrain', argv, {
      cwd: WORKSPACE,
      env: childEnv,
      timeout: 10 * 60 * 1000,
    })
    let out = '', err = ''
    child.stdout.on('data', (d) => { out += d })
    child.stderr.on('data', (d) => { err += d })
    child.on('error', (e) => res({ ok: false, action, error: String(e.message) }))
    child.on('close', (code) => {
      if (code === 0) res({ ok: true, action, output: out.trim() })
      else res({ ok: false, action, exit: code, error: (err || out).trim().slice(0, 4000) })
    })
  }))
}

// ── HTTP ─────────────────────────────────────────────────────────────────────
function json(res, status, body, extra = {}) {
  const s = JSON.stringify(body)
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(s),
    ...extra,
  })
  res.end(s)
}

async function readBody(req) {
  const chunks = []
  for await (const c of req) chunks.push(c)
  const raw = Buffer.concat(chunks).toString('utf8')
  if (!raw.trim()) return null
  try {
    return JSON.parse(raw)
  } catch {
    throw Object.assign(new Error('invalid JSON body'), { status: 400 })
  }
}

function commitRef() {
  try { return readFileSync('/etc/terrain-commit', 'utf8').trim().slice(0, 12) } catch { return 'unknown' }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`)

  try {
    if (url.pathname === '/healthz') {
      return json(res, 200, { ok: true, terrain: commitRef(), workspace: WORKSPACE, acpModel: acpModel() })
    }
    if (TOKEN && req.headers['x-terrain-token'] !== TOKEN) {
      return json(res, 401, { error: 'bad or missing x-terrain-token' })
    }

    if (url.pathname === '/call' && req.method === 'POST') {
      const body = await readBody(req)
      if (!body?.action) throw Object.assign(new Error('missing "action"'), { status: 400 })
      return json(res, 200, await run(body.action, body.params ?? {}))
    }

    return json(res, 404, { error: 'not found', routes: ['/healthz', '/call'] })
  } catch (e) {
    return json(res, e.status ?? 500, { error: e.message })
  }
})

server.listen(PORT, '0.0.0.0', () => {
  console.error(`[terrain] listening on ${PORT} · workspace=${WORKSPACE} · ref=${commitRef()}`)
  // Seed the config from the template immediately; the resolved model lands in
  // the background pass moments later and rewrites it.
  writeAcpConfig()
  console.error(`[terrain] LLM actions (init, ask): opencode acp · template fallback model=${readTemplateModel()} · best keyless model resolved at boot · NOT llm-gateway`)
  listKeylessModels()
  // A leaked key is stripped before every spawn, so init/ask keep working — but
  // say so loudly rather than letting a stray credential sit in the env until
  // someone debugs a mysterious provider-billing line. The source is the bug.
  const leaked = PROVIDER_KEYS.filter((k) => process.env[k])
  if (leaked.length) {
    console.error(`[terrain] WARNING: ${leaked.join(', ')} present in container env — stripped before every spawn, but fix the source. Compose passes these only if the environment: map or env_file: is edited.`)
  }
})