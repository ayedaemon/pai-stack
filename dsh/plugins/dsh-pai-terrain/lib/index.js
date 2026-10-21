/**
 * dsh-pai-terrain — DSH plugin for code intelligence via Terrain service.
 *
 * Provides: pai_terrain_ops tool with actions:
 * - index, refresh, search, read, overview, projects, unregister, source, init, ask
 *
 * Connects to Terrain service (TERRAIN_URL, default http://terrain:7878).
 * Indexing (index, refresh) is free — no LLM calls. Only init/ask use an LLM, run
 * by the opencode binary inside the terrain container on keyless Zen free models,
 * not llm-gateway.
 * Each scan writes .terrain/ inside the repo (gitignored, per-host).
 * Paths are given relative to the workspace attached to this session and
 * translated to workspace-relative before they reach the service, which
 * resolves them against its own root (/opt/data/workspace).
 */

import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { isAbsolute, relative, resolve } from "node:path";

import { WorkspaceUnresolved, sessionWorkspace } from "./session-workspace.js";

export const name = "pai-terrain";
export const inject = ["tools"];

export const Config = z.object({
  enabled: z.boolean().default(true),
});

const SERVICE = process.env.TERRAIN_URL || "http://terrain:7878";
const TOKEN = process.env.TERRAIN_TOKEN || "";
// The terrain container mounts the same workspace root this plugin resolves
// against, so a session-relative path must be rebased onto it.
const SERVICE_ROOT = process.env.TERRAIN_WORKSPACE || "/opt/data/workspace";

// Matches the service-side spawn timeout; `init` runs Litho over a whole repo.
const TIMEOUT = 600;

const ALLOWED_ACTIONS = [
  "index", "refresh", "search", "read", "overview", 
  "projects", "unregister", "source", "init", "ask"
];

function headers() {
  const h = { "content-type": "application/json" };
  if (TOKEN) h["x-terrain-token"] = TOKEN;
  return h;
}

async function post(action, params) {
  const body = JSON.stringify({ action, params });
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT * 1000);
  
  try {
    const response = await fetch(`${SERVICE}/call`, {
      method: "POST",
      headers: headers(),
      body,
      signal: controller.signal,
    });
    clearTimeout(timeout);
    const text = await response.text();
    if (!response.ok) {
      let detail = text;
      try { detail = JSON.parse(text).error || detail; } catch {}
      return [1, JSON.stringify({ error: detail || `HTTP ${response.status}` })];
    }
    return [0, text];
  } catch (e) {
    clearTimeout(timeout);
    if (e.name === "AbortError") {
      return [1, JSON.stringify({ error: `Request timeout after ${TIMEOUT}s` })];
    }
    return [1, JSON.stringify({ 
      error: `Cannot reach terrain service at ${SERVICE}: ${e.message}. Start with 'make terrain-up' or fall back to grep.` 
    })];
  }
}

async function checkAvailable() {
  try {
    const response = await fetch(`${SERVICE}/healthz`, { 
      headers: headers(), 
      signal: AbortSignal.timeout(3000) 
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Translate a path written relative to the session workspace into one the
 * service can resolve against its own root. Already-correct
 * workspace-relative paths pass through; anything escaping the attached
 * workspace is refused rather than indexed.
 */
function rebaseOntoServiceRoot(exec, raw) {
  const workspace = sessionWorkspace(exec);
  const absolute = isAbsolute(raw) ? resolve(raw) : resolve(workspace, raw);
  const rel = relative(workspace, absolute);
  if (rel.startsWith("..") || isAbsolute(rel)) {
    return { error: `path '${raw}' resolves outside this session's workspace (${workspace}). Attach the right workspace or pass a path inside it.` };
  }
  const rebased = relative(SERVICE_ROOT, absolute);
  if (rebased.startsWith("..") || isAbsolute(rebased)) {
    return { error: `path '${raw}' is outside the terrain service root (${SERVICE_ROOT}).` };
  }
  return { path: rebased };
}

export function apply(ctx, config) {
  const cfg = { enabled: true, ...(config ?? {}) };
  if (!cfg.enabled) return;

  const terrainTool = defineTool({
    name: "pai_terrain_ops",
    description: "Code intelligence over the Terrain index service. Terrain scans a project repo into .terrain/ (Markdown knowledge docs + agent context); this tool triggers those scans and reads the result. Check action='projects' first: if the repo is indexed, this is far more precise than grep; if it is not, fall back to grep + targeted reads. Indexing ('index', 'refresh') makes NO LLM call and costs nothing. Only 'ask' and 'init' use an LLM — Terrain's keyless Zen free models, run by the opencode binary inside the terrain container, not the llm-gateway. Both are always available. Write scope: each scan writes .terrain/ inside the repo you pass. Paths are resolved relative to the workspace attached to this session and must stay inside it; other paths are rejected. Allowed actions: index, refresh, search, read, overview, projects, unregister, source, init, ask.",
    parameters: {
      action: {
        type: "string",
        required: true,
        enum: ALLOWED_ACTIONS,
        description: "Operation to perform"
      },
      path: {
        type: "string",
        description:
        "Repo directory to index, relative to the workspace attached to this session " +
        "or absolute inside it (e.g. 'pai-stack' when that repo is the attached " +
        "workspace, or 'github.com/ayedaemon/pai-stack' when the workspace root is). " +
        "Required for 'index', 'refresh', 'init'. Optional for 'source'."
      },
      slug: {
        type: "string",
        description: "Registry name for this project. Defaults to the directory name."
      },
      query: {
        type: "string",
        description: "Search string ('search') or question ('ask')."
      },
      project: {
        type: "string",
        description: "Project slug ('search', 'overview', 'ask', 'source', 'unregister')."
      },
      file: {
        type: "string",
        description:
        "File to read ('source' only). Workspace-relative, not repo-relative: resolved " +
        "against the session workspace then rebased onto " + SERVICE_ROOT + ", so when a " +
        "project is attached it is simply 'README.md' (e.g. " +
        "'github.com/ayedaemon/pai-stack/README.md' when the workspace root is attached).",
      },
      limit: {
        type: "integer",
        description: "Max search results ('search' only). Default: 20.",
        default: 20,
      },
    },
    output: {
      schema: { type: "json" },
      render: (_args, value) => [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }]
    },
    async execute(args, exec) {
      const action = args.action;
      const start = Date.now();

      try {
        if (!ALLOWED_ACTIONS.includes(action)) {
          return { error: `Unknown action: ${action}. Allowed: ${ALLOWED_ACTIONS.join(", ")}` };
        }

        if (["index", "refresh", "init"].includes(action) && !args.path) {
          return { error: `path is required for '${action}'. Pass the repo directory relative to this session's workspace, e.g. path='pai-stack'.` };
        }
        if (["search", "ask"].includes(action) && !args.query) {
          return { error: `query is required for '${action}'` };
        }
        if (action === "overview" && !args.project) {
          return { error: "project is required for 'overview'" };
        }

        const params = {};
        for (const key of ["path", "slug", "query", "project", "file", "limit"]) {
          if (args[key] !== undefined) params[key] = args[key];
        }

        // Rebase session-relative paths onto the root the service resolves
        // against, and refuse anything that escapes the attached workspace.
        for (const key of ["path", "file"]) {
          if (params[key] === undefined) continue;
          const rebased = rebaseOntoServiceRoot(exec, params[key]);
          if (rebased.error) return rebased;
          params[key] = rebased.path;
        }

        // Validate limit if provided
        if (params.limit !== undefined && (params.limit < 1 || params.limit > 200)) {
          return { error: "limit must be between 1 and 200" };
        }
        
        const [code, out] = await post(action, params);
        
        let parsed;
        try { parsed = JSON.parse(out); } catch { parsed = { raw: out }; }
        
        if (parsed && typeof parsed === "object") {
          parsed._duration_ms = Date.now() - start;
          parsed._action = action;
          if (code === 0 && ["index", "refresh", "init"].includes(action)) {
            parsed._hint = `'.terrain/' now exists inside ${params.path}. It is gitignored; re-run 'refresh' after meaningful code changes.`;
          }
        }
        return parsed;
      } catch (err) {
        if (err instanceof WorkspaceUnresolved) return { error: err.message, action };
        return { error: `${action}: ${err.message}` };
      }
    },
  });

  // Also expose health check as a provided service
  ctx.provide("paiTerrainHealth", {
    async check() {
      return await checkAvailable();
    },
    getServiceUrl() {
      return SERVICE;
    }
  });

  ctx.tools.register(terrainTool);
}

export default { Config, apply, inject, name };