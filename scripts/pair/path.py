#!/usr/bin/env python3
"""pair path — normalize host <-> container paths to the canonical form.

Canonical form is ALWAYS the container-absolute path:
    /opt/data/workspace/<...>
Host forms (~/Personal/..., /Users/.../Personal/...) must never appear in
pair/ files, prompts, or agent reports — normalize on intake with this tool.

Usage:
    python3 scripts/pair/path.py <path>            # print canonical container form
    python3 scripts/pair/path.py --to host <path>  # print host form (for your own copy-paste)
    python3 scripts/pair/path.py --map             # print the prefix table

Mapping: $WORKSPACE_DIR (or ~/Personal) <-> /opt/data/workspace.
Stdlib only.
"""
import os
import sys
from pathlib import Path

CONTAINER_PREFIX = "/opt/data/workspace"


def host_prefix() -> str:
    ws = os.environ.get("WORKSPACE_DIR") or os.path.join(
        os.path.expanduser("~"), "Personal")
    return ws.rstrip("/")


def to_container(p: str) -> str:
    p = os.path.expanduser(p)
    hp = host_prefix()
    if p == hp or p.startswith(hp + "/"):
        return CONTAINER_PREFIX + p[len(hp):]
    # Human-machine forms the env fallback cannot know (~/Personal on the
    # human host, /Users/*/Personal/...): cut at the shared marker.
    if "/Personal/" in p:
        return CONTAINER_PREFIX + "/" + p.split("/Personal/", 1)[1]
    return p


def to_host(p: str) -> str:
    hp = host_prefix()
    if p == CONTAINER_PREFIX or p.startswith(CONTAINER_PREFIX + "/"):
        return hp + p[len(CONTAINER_PREFIX):]
    return p


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--map":
        print(f"host:      {host_prefix()}/...")
        print(f"container: {CONTAINER_PREFIX}/...  <- canonical, always use this")
        return 0
    if len(argv) == 4 and argv[1] == "--to" and argv[2] == "host":
        print(to_host(argv[3]))
        return 0
    if len(argv) == 2:
        print(to_container(argv[1]))
        return 0
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
