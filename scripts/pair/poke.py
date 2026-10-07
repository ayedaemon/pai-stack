#!/usr/bin/env python3
"""pair poke — wake the peer: files never notify, this does.

Usage: python3 scripts/pair/poke.py <peer: hermes|dsh|<id>> "[prompt]"
Stdlib only (subprocess + shlex). Runs from host or either container — both
hold the docker socket, so `docker exec <sibling> ...` works both ways.

Transport: DETACHED docker exec + poll file. Foreground runs were tried and
timed out (DSH headless needs >60s per run; the exec cap kills the client).
So poke launches detached (`docker exec -d`), the peer writes stdout/stderr
to .pair/pokes/<peer>-<ts>.log, and the reporter polls that file:

    docker exec <peer-container> cat <repo>/.pair/pokes/<peer>-<ts>.log

DSH one-shots always carry --patch scripts/pair/dsh-headless-gateway.yml
(pins headless to the stack gateway; without it headless defaults to
deepseek-flash, which the gateway does not serve). Unknown peer ids are
logged but not launched (their next poll picks the task up) — this keeps
future drop-in agents working unchanged.
"""
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pairlib import find_pair  # noqa: E402

PAIR = find_pair()
ROOT = PAIR.parent
REPO_CONTAINER = "/opt/data/workspace/github.com/ayedaemon/pai-stack"
DEFAULT_PROMPT = "check .pair/queue and claim runnable pending tasks"
# Container-view absolute path (valid inside hermes, dsh, and via docker exec
# from the host — the repo sits at the same mount point in every container).
OVERLAY = REPO_CONTAINER + "/scripts/pair/dsh-headless-gateway.yml"

LAUNCH = {
    # <inner-shell-command> run detached inside <container>; output -> log file
    "dsh": ("dsh", "dsh --profile headless --patch "
            + shlex.quote(OVERLAY)),
    "hermes": ("hermes", "/opt/hermes/.venv/bin/hermes-agent -q"),
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: poke.py <hermes|dsh|<id>> "[prompt]"', file=sys.stderr)
        return 1
    peer = argv[1]
    prompt = argv[2] if len(argv) > 2 else DEFAULT_PROMPT
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if peer in LAUNCH:
        container, base = LAUNCH[peer]
        logname = f"{peer}-{ts}.log"
        logpath = f"{REPO_CONTAINER}/.pair/pokes/{logname}"
        inner = f"mkdir -p {REPO_CONTAINER}/.pair/pokes && {base} {shlex.quote(prompt)} > {logpath} 2>&1"
        try:
            subprocess.run(["docker", "exec", "-d", container, "sh", "-c", inner],
                           timeout=60, check=False)
            print(f"launched detached in {container}; poll: docker exec {container} cat {logpath}")
        except FileNotFoundError:
            print("poke: docker CLI not found; logged only", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print("poke: launch hit 60s cap; logged only", file=sys.stderr)
    else:
        print(f"poke: unknown peer '{peer}' — logged only, poll will deliver",
              file=sys.stderr)
    tslog = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with (PAIR / "log.md").open("a", encoding="utf-8") as f:
        f.write(f"{tslog} | human | poke {peer} | - | {prompt}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
