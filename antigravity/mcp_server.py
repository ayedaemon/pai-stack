import asyncio
import json
import os
import subprocess
from mcp.server.mcpserver import MCPServer

HOST = "0.0.0.0"
PORT = int(os.environ.get("MCP_PORT", "8000"))
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT", "900"))

mcp = MCPServer(
    "antigravity-delegate",
    instructions="Isolated Google Antigravity (agy) delegate on a Pro account, "
    "a different model family from OpenCode. Runs tasks inside /workspace and "
    "returns a JSON summary with status, changed files, and a diff.",
)
_lock = asyncio.Lock()

SETTINGS_DIR = os.path.expanduser("~/.gemini/antigravity-cli")
SEED = "/opt/seed/settings.json"


def _ensure_settings():
    """Seed agy settings into the (persisted) auth volume on first run."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    dest = os.path.join(SETTINGS_DIR, "settings.json")
    if not os.path.exists(dest) and os.path.exists(SEED):
        with open(SEED) as f:
            data = json.load(f)
        if os.environ.get("ANTIGRAVITY_MODEL"):
            data["model"] = os.environ["ANTIGRAVITY_MODEL"]
        with open(dest, "w") as f:
            json.dump(data, f, indent=2)


def _gather_changes():
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
    """DELEGATE AGENT: Antigravity (mcp-antigravity) — research/implementation specialist.

    Identity: an isolated coding agent (Google Antigravity CLI, `agy`) running
    in its own container on a PRO ACCOUNT, using a DIFFERENT model family from
    OpenCode — ideal for an independent second opinion, broader research,
    documentation, or plan-level reasoning.

    Use this tool when the user (or the manager) wants: a research/investigation
    pass, documentation or README generation, a design/plan, or an
    implementation done by a model family distinct from OpenCode (fan-out for
    higher confidence). It works inside the shared /workspace and returns the
    result — it cannot see your synced notes or other containers.

    Arguments:
      task:        precise description of the work (research, feature, docs, review...).
      context_refs: optional list of file paths / code snippets to ground it.
      mode:        'implement' (default) | 'research' | 'review' — prepended as a hint.

    Returns: {summary, artifacts (changed files), diff, status}.

    Manager note: you (Hermes) remain responsible — provide the repo/context,
    review the returned diff, and write the final artifact into silverbulletKB.
    """
    _ensure_settings()
    async with _lock:  # one task at a time (protect the Pi)
        prompt = f"[{mode}] {task}"
        if context_refs:
            prompt += "\n\nContext references:\n" + "\n".join(f"- {c}" for c in context_refs)

        # Non-interactive: -p prompt, explicit model, skip all permission prompts.
        model = os.environ.get("ANTIGRAVITY_MODEL", "Gemini 3.5 Flash (High)")
        cmd = ["agy", "-p", prompt, "--model", model, "--dangerously-skip-permissions"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd="/workspace",
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
