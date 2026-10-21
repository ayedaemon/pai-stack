/**
 * Session workspace resolution for pai-stack DSH plugins.
 *
 * DSH owns the concept natively. `session.create` resolves
 * `workspace?.path ?? request.cwd ?? defaultCwd` and pins it as the session
 * header's cwd (`@deepseek-ai/dsh-api-session-controller`), so the workspace
 * the user attached in the directory picker is readable at tool-execution time
 * as `exec.agent.session.header.cwd`. The workspace registry backs it:
 * `workspaces[*].path` with a `sessionIds` projection.
 *
 * Plugins must read it per call. A module-level constant would pin every
 * session to whichever workspace happened to resolve first, which is how the
 * old `EXECUTION_DIR` env var ended up writing research into a workspace root
 * nobody had attached to.
 *
 * Resolution order, first existing directory wins:
 *   1. `exec.agent.session.header.cwd` — the workspace attached to this session
 *   2. `WORKSPACE_DIR`                   — the container's workspace mount
 *
 * No result is a loud error: writing a vault outside the attached workspace is
 * exactly the failure this replaces.
 */

import { existsSync, statSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export class WorkspaceUnresolved extends Error {
  constructor(message) {
    super(message);
    this.name = "WorkspaceUnresolved";
  }
}

function isDir(path) {
  try {
    return existsSync(path) && statSync(path).isDirectory();
  } catch {
    return false;
  }
}

/**
 * The workspace directory attached to the session making this tool call.
 * @param {object} [exec] the dsh tool execution context
 * @returns {string} absolute path to the session workspace
 * @throws {WorkspaceUnresolved} when no workspace can be resolved
 */
export function sessionWorkspace(exec) {
  const attached = exec?.agent?.session?.header?.cwd;
  if (attached) {
    if (!isAbsolute(attached)) {
      throw new WorkspaceUnresolved(
        `Session workspace "${attached}" is not an absolute path. Re-attach an absolute workspace.`,
      );
    }
    if (!isDir(attached)) {
      throw new WorkspaceUnresolved(
        `Session workspace "${attached}" does not exist. Attach a workspace that exists on disk.`,
      );
    }
    return resolve(attached);
  }

  const fallback = process.env.WORKSPACE_DIR || "/opt/data/workspace";
  if (isDir(fallback)) return resolve(fallback);

  throw new WorkspaceUnresolved(
    "No workspace is attached to this session and WORKSPACE_DIR does not point at an " +
      "existing directory. Attach a workspace to the session, or set WORKSPACE_DIR.",
  );
}

/**
 * `<session workspace>/.project[/subpath]`. Does not create anything.
 * @param {object} [exec] the dsh tool execution context
 * @param {string} [subpath] path under `.project/`
 */
export function projectDir(exec, subpath = "") {
  const base = join(sessionWorkspace(exec), ".project");
  return subpath ? join(base, subpath) : base;
}

/** `<session workspace>/.project/research` — the Research Brain vault. */
export function researchDir(exec) {
  return projectDir(exec, "research");
}

/**
 * True when `candidate` is inside the session workspace.
 *
 * Comparison is string-exact (`path.relative` does not consult the
 * filesystem), which is the safe direction: a path that only differs by case
 * is refused rather than silently allowed to escape the attached workspace.
 */
export function isWithinWorkspace(exec, candidate) {
  const workspace = sessionWorkspace(exec);
  const rel = relative(workspace, resolve(candidate));
  return rel === "" || (!rel.startsWith("..") && !rel.startsWith(sep) && !isAbsolute(rel));
}
