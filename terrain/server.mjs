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
 * models (see terrain/opencode.json). This container therefore holds no gateway
 * link and no provider credential. See PROVIDER_KEYS below for why that is
 * enforced rather than assumed.
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
import { realpathSync, existsSync, lstatSync, readlinkSync, unlinkSync, symlinkSync } from 'node:fs'
import { readFileSync, mkdirSync } from 'node:fs'
import { resolve, join, dirname, isAbsolute } from 'node:path'

const PORT = Number(process.env.TERRAIN_PORT ?? 7878)
const WORKSPACE = resolve(process.env.TERRAIN_WORKSPACE ?? '/opt/data/workspace')
const TOKEN = process.env.TERRAIN_TOKEN || null

/** The ACP agent's config, as shipped in the image. Linked into XDG at boot. */
const ACP_CONFIG_SRC = '/opt/terrain/opencode.json'

/**
 * Point opencode's config at the image copy of terrain/opencode.json.
 *
 * XDG_CONFIG_HOME has to be writable: opencode mkdirs `$XDG_CONFIG_HOME/opencode/`
 * on startup, which fails under this container's `read_only: true` if it points
 * into the image layer. So the DIRECTORY lives on the terrain_data volume.
 *
 * The FILE is a symlink back to the image rather than a copy. A copy has to be
 * refreshed on every boot, and "refresh only if absent" silently pins a stale
 * config forever — a hand-edited copy outlives the image it came from, so
 * bumping TERRAIN_REF stops changing the model and nobody notices until an LLM
 * action fails. The symlink makes /opt/terrain/opencode.json the single source
 * of truth: edit it, rebuild, done. Any pre-existing regular file here (from the
 * old copy-based seed) is replaced.
 *
 * Failure is non-fatal: terrain still indexes and searches; only init/ask lose
 * their agent.
 */
function linkAcpConfig() {
  const xdg = process.env.XDG_CONFIG_HOME
  if (!xdg || !existsSync(ACP_CONFIG_SRC)) return
  const dir = join(xdg, 'opencode')
  const dst = join(dir, 'opencode.json')
  try {
    mkdirSync(dir, { recursive: true })
    // existsSync follows symlinks, so a BROKEN link reads as absent — test
    // lstat too, or symlinkSync throws EEXIST on it.
    let st = null
    try { st = lstatSync(dst) } catch { /* nothing there */ }
    if (st?.isSymbolicLink()) {
      // Compare the RAW target, not realpathSync: normalising would defeat the
      // comparison whenever either side traverses a symlink (/tmp -> /private/tmp
      // on macOS, a symlinked /opt, ...) and re-link on every boot.
      try { if (readlinkSync(dst) === ACP_CONFIG_SRC) return } catch { /* unreadable */ }
      unlinkSync(dst)
    } else if (st) {
      unlinkSync(dst) // a regular file left by the old copy-based seed
    }
    symlinkSync(ACP_CONFIG_SRC, dst)
    console.error(`[terrain] ACP agent config -> ${dst} -> ${ACP_CONFIG_SRC}`)
  } catch (e) {
    console.error(`[terrain] could not link ACP config: ${e.message} (init/ask may be unavailable)`)
  }
}

/**
 * Read the model the ACP agent will use, for the boot banner.
 *
 * Worth logging because these keyless Zen models get retired upstream with no
 * deprecation here: a retired model makes `init`/`ask` fail while
 * `terrain settings check-acp` still reports `available: true`, because that
 * only proves the BINARY exists. The banner is the one place that shows which
 * model is actually wired up.
 */
function acpModel() {
  try {
    return JSON.parse(readFileSync(ACP_CONFIG_SRC, 'utf8')).model ?? 'unset'
  } catch {
    return 'unreadable'
  }
}

/**
 * Verify the pinned ACP model is still reachable keylessly, and say so loudly if
 * not. Costs ~50ms warm.
 *
 * This exists because the failure is otherwise invisible. When
 * muse-spark-1.3-contributor-free was retired upstream, `terrain settings
 * check-acp` kept reporting {"available": true} — it only proves the BINARY
 * exists — so `ask` and `init` just hung until the 10-minute spawn timeout, with
 * no error anywhere pointing at the model. One `opencode models` call at boot
 * turns that into a line in the banner.
 *
 * `opencode models` is ITSELF unreliable cold: it exits 0 with EMPTY stdout while
 * its background server (opencode.db + WAL) is still coming up, then works. So an
 * empty answer is INCONCLUSIVE, not a verdict — retry, and if it never resolves,
 * say "unverified" rather than screaming that the model is dead. Reporting a
 * false alarm here would be worse than not checking: the next reader learns to
 * ignore the line that is supposed to matter.
 *
 * Never fatal: scan/search/read/source are all offline and must keep working
 * when the model is gone. Failure here only means init/ask will not.
 */
function verifyAcpModel(attempt = 1) {
  const want = acpModel()
  const ATTEMPTS = 3
  execFile('opencode', ['models'], { timeout: 15000, env: process.env }, (err, stdout) => {
    const live = (stdout || '').split('\n').map((l) => l.trim()).filter(Boolean)

    if (err || live.length === 0) {
      if (attempt < ATTEMPTS) {
        setTimeout(() => verifyAcpModel(attempt + 1), 1500)
        return
      }
      console.error(
        `[terrain] could not verify ACP model ${want}: ` +
        `${err ? err.message : '`opencode models` returned nothing'} ` +
        `(init/ask unverified — this says nothing about whether the model works)`
      )
      return
    }

    if (live.includes(want)) {
      console.error(`[terrain] ACP model ${want} verified against ${live.length} keyless model(s)`)
      return
    }

    console.error(
      `[terrain] ERROR: ACP model ${want} is NOT available keylessly — init and ask WILL FAIL.\n` +
      `           Retired upstream; nothing in this container changed. Live alternatives:\n` +
      live.slice(0, 5).map((m) => `             ${m}`).join('\n') +
      `\n           Fix: edit "model" in terrain/opencode.json, then make terrain-build && make terrain-up.\n` +
      `           Confirm with: make free-models-check`
    )
  })
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
  linkAcpConfig()
  console.error(`[terrain] LLM actions (init, ask): opencode acp · model=${acpModel()} · keyless Zen, NOT llm-gateway`)
  verifyAcpModel()
  // A leaked key is stripped before every spawn, so init/ask keep working — but
  // say so loudly rather than letting a stray credential sit in the env until
  // someone debugs a mysterious provider-billing line. The source is the bug.
  const leaked = PROVIDER_KEYS.filter((k) => process.env[k])
  if (leaked.length) {
    console.error(`[terrain] WARNING: ${leaked.join(', ')} present in container env — stripped before every spawn, but fix the source. Compose passes these only if the environment: map or env_file: is edited.`)
  }
})