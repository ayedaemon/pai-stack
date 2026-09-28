"""pai_docker_ops — pai-stack container management (native Hermes tool).

Ported from the retired mcp-server shell tool to Python. Operates the Docker
CLI over /var/run/docker.sock (mounted read-only into the hermes container).
Every action is audited to the hermes-data volume log.
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "pai-stack")
ALLOWED_SERVICES = ("hermes", "llm-gateway")
ALLOWED_ACTIONS = ("list", "status", "logs", "restart", "start", "stop", "exec")
LOG_DIR = os.environ.get("LOG_DIR", "/opt/hermes/data/logs")
LOG_FILE = os.path.join(LOG_DIR, "docker-ops.log")

SCHEMA = {
    "name": "pai_docker_ops",
    "description": "Manage pai-stack Docker containers via Docker socket. Logs every action to the hermes-data volume log. Allowed actions: list, status, logs, restart, start, stop, exec.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "status", "logs", "restart", "start", "stop", "exec"],
                "description": "Operation to perform",
            },
            "service": {
                "type": "string",
                "enum": ["hermes", "llm-gateway"],
                "description": "Target container name. Required for all actions except 'list'.",
            },
            "lines": {
                "type": "integer",
                "description": "Log lines to tail (for 'logs' only). Default: 50. Max: 500.",
                "default": 50,
                "minimum": 1,
                "maximum": 500,
            },
            "cmd": {
                "type": "string",
                "description": "Command to run inside the container (for 'exec' only). Runs via sh -c.",
            },
        },
        "required": ["action"],
    },
}


def check_available() -> bool:
    """Gate dispatch until the Docker CLI is installed."""
    return shutil.which("docker") is not None


def _log_action(action, service, cmd, exit_code, duration_ms):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(
                f"[{ts}] action={action} service={service} "
                f"cmd={cmd} exit={exit_code} duration={duration_ms}ms\n"
            )
    except Exception:
        pass


def _run_docker(*argv) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["docker", *argv], capture_output=True, text=True, timeout=60
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "docker command timed out after 60s"
    except Exception as e:
        return 1, str(e)


def handle(args, **kwargs) -> str:
    """Hermes tool handler — dispatch an action, always returning a string."""
    if not isinstance(args, dict):
        return json.dumps({"error": "Invalid arguments"})
    start = time.monotonic()
    action = args.get("action", "")
    service = args.get("service", "") or ""
    cmd = args.get("cmd", "") or ""
    try:
        lines = int(args.get("lines", 50))
    except (TypeError, ValueError):
        lines = 50
    lines = max(1, min(500, lines))

    def done(exit_code, output):
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_action(action, service, cmd, exit_code, duration_ms)
        return output

    if action not in ALLOWED_ACTIONS:
        return done(1, json.dumps({"error": f"unknown action: {action}. Allowed: {list(ALLOWED_ACTIONS)}"}))

    if action != "list":
        if not service:
            return done(1, json.dumps({"error": f"service is required for action: {action}"}))
        if service not in ALLOWED_SERVICES:
            return done(1, json.dumps({"error": f"unknown service: {service}. Allowed: {list(ALLOWED_SERVICES)}"}))

    if action == "exec" and not cmd:
        return done(1, json.dumps({"error": "cmd is required for exec action"}))

    if action == "list":
        code, out = _run_docker(
            "ps", "-a",
            "--filter", f"label=com.docker.compose.project={PROJECT}",
            "--format", '{"id":"{{.ID}}","name":"{{.Names}}","status":"{{.Status}}","state":"{{.State}}"}',
        )
        if code != 0:
            return done(code, json.dumps({"error": out or "docker ps failed"}))
        rows = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return done(0, json.dumps(rows))

    if action == "status":
        code, out = _run_docker("inspect", service, "--format", "{{json .State}}")
        if code != 0:
            return done(code, json.dumps({"error": out or f"inspect failed for {service}"}))
        return done(0, out)

    if action == "logs":
        code, out = _run_docker("logs", f"--tail={lines}", service)
        if code != 0:
            return done(code, json.dumps({"error": out or f"logs failed for {service}"}))
        return done(0, out)

    if action in ("restart", "start", "stop"):
        code, out = _run_docker(action, service)
        if code != 0:
            return done(code, json.dumps({"error": out or f"{action} failed for {service}"}))
        return done(0, json.dumps({"ok": True, "message": f"{action}ed {service}"}))

    if action == "exec":
        code, out = _run_docker("exec", service, "sh", "-c", cmd)
        if code != 0:
            return done(code, json.dumps({"error": out or f"exec failed in {service}"}))
        return done(0, out)

    return done(1, json.dumps({"error": f"unhandled action: {action}"}))
