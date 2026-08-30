import asyncio
import os
import subprocess
from mcp.server.mcpserver import MCPServer

HOST = "0.0.0.0"
PORT = int(os.environ.get("MCP_PORT", "8001"))
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT", "900"))

mcp = MCPServer(
    "opencode-delegate",
    instructions="Isolated OpenCode coding delegate. Uses its own free models "
    "(no API key). Runs tasks inside /workspace and returns a JSON summary "
    "with status, changed files, and a diff.",
)
_lock = asyncio.Lock()


def _gather_changes():
    """Best-effort list of what changed in /workspace (git if available)."""
    try:
        diff = subprocess.run(
            ["git", "-C", "/workspace", "diff", "--stat"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", "/workspace", "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return diff, status
    except Exception:
        return "", ""


@mcp.tool()
async def run_task(task: str, context_refs: list = None, mode: str = "implement") -> dict:
    """DELEGATE AGENT: OpenCode (mcp-opencode) — coding/implementation specialist.

    Identity: an isolated coding agent (OpenCode CLI) running in its own
    container, powered by its OWN FREE MODELS (no external API key required).

    Use this tool when the user (or the manager) wants code work done on a
    configured project: implement a feature, fix a bug, refactor, write tests,
    or produce a code diff. It works autonomously inside the shared
    /workspace and returns the result — it cannot see your synced notes or
    other containers.

    Arguments:
      task:        precise description of the work (bug fix, feature, review...).
      context_refs: optional list of file paths / code snippets to ground it.
      mode:        'implement' (default) | 'research' | 'review' — prepended as a hint.

    Returns: {summary, artifacts (changed files), diff, status}.

    Manager note: you (Hermes) remain responsible — provide the repo/context,
    review the returned diff, and write the final artifact into silverbulletKB.
    """
    async with _lock:  # one task at a time (protect the Pi)
        prompt = f"[{mode}] {task}"
        if context_refs:
            prompt += "\n\nContext references:\n" + "\n".join(f"- {c}" for c in context_refs)

        # OpenCode is provider-agnostic and uses its own free/default models.
        # `opencode run` is the non-interactive path. CRITICAL: permissions must
        # be 'allow' or it hangs waiting for a prompt we can't answer.
        env = dict(os.environ)
        env.setdefault("OPENCODE_PERMISSION", '{"*":"allow"}')
        if os.environ.get("OPENCODE_MODEL"):
            cmd = ["opencode", "run", "--model", os.environ["OPENCODE_MODEL"], prompt]
        else:
            cmd = ["opencode", "run", prompt]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd="/workspace", env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=TASK_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"summary": "Task timed out", "artifacts": "", "diff": "", "status": "error"}
            summary = (out or b"").decode(errors="replace").strip()[-4000:]
            diff, status = _gather_changes()
            return {
                "summary": summary,
                "artifacts": status,
                "diff": diff,
                "status": "ok" if proc.returncode == 0 else "error",
            }
        except Exception as e:
            return {"summary": f"Wrapper error: {e}", "artifacts": "", "diff": "", "status": "error"}


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=HOST, port=PORT)
