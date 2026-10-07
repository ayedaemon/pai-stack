#!/usr/bin/env python3
"""pair init — scaffold a self-contained .pair/ in ANY project (no pai-stack needed).

Usage:
  python3 scripts/pair/init.py /path/to/project
  PAIR_DIR=/path/to/project/.pair python3 scripts/pair/init.py --here

Creates <project>/.pair/{queue,claims,done,pokes} + telegram-groups.md with
<fill> placeholders + task _example.md. Never touches code. Stdlib only.
Hidden + untracked by design (.gitignore): the lock is os.rename on the
shared volume, not git. Contract stays in pai-stack (normative); the
queue/claims/done file schema is the portable interface.
"""
import sys
from pathlib import Path

EXAMPLE = """---
slug: _example-YYYY-MM-DD
status: pending
owner: unclaimed
execution_dir: <FILL-CONTAINER-PATH>
branch: pair/_example-YYYY-MM-DD
worktree: .worktrees/_example-YYYY-MM-DD
acceptance: echo EXAMPLE_OK
rounds_left: 2
created_by: human
---

# EXAMPLE — never claim this file. Copy it for real tasks.

## Task

Template. Describe WHAT + acceptance, not HOW.

## Context

Keep file small; details live in planning files, not here.

## Verdict

(leave empty until done)
"""

GROUPS_MD = """# Telegram group mapping — <PROJECT>

> One group = one EXECUTION_DIR. Fill the <fill> values per deployment
> (each host/chat uses its own IDs — never commit real IDs here; copy this
> file to `telegram-groups.local.md` for real values, which is gitignored).

| Field | Value |
|---|---|
| `EXECUTION_DIR` (container) | <FILL-CONTAINER-PATH> |
| `EXECUTION_DIR` (host) | <FILL-HOST-PATH> |
| `group_chat_id` | `<fill: -100...>` |
| `human_ids` | `<fill: from @userinfobot>` |

Bots: @YourHermesBot + @YourDshBot join this group (DSH needs group-chat
support). Optional 3rd bridge bot only for file→Telegram announcements;
human→agent mentions work without it (agents see human messages directly).

Env per deployment (never committed):
`BRIDGE_GROUP_CHAT_ID`, `BRIDGE_ALLOWED_USERS`, `BRIDGE_GROUP_ALLOWED_USERS`.
"""


def main(argv: list[str]) -> int:
    if "--here" in argv:
        dest = Path.cwd() / ".pair"
    elif len(argv) == 2:
        dest = Path(argv[1]).resolve() / ".pair"
    else:
        print("usage: init.py /path/to/project", file=sys.stderr)
        return 1
    for sub in ("queue", "claims", "done", "pokes"):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    (dest / "log.md").write_text(
        "# Pair log — append-only\n\n`YYYY-MM-DDTHH:MMZ | actor | event | slug | note`\n",
        encoding="utf-8",
    )
    (dest / "STATE.md").write_text(
        "# Pair State — human dashboard\n\n**EXECUTION_DIR:** see telegram-groups.md\n",
        encoding="utf-8",
    )
    (dest / "queue" / "_example.md").write_text(EXAMPLE, encoding="utf-8")
    (dest / "telegram-groups.md").write_text(GROUPS_MD, encoding="utf-8")
    print(f"init ok: {dest}/{{queue,claims,done,pokes,log.md,STATE.md,telegram-groups.md}}")
    print("next: add `.pair/` + `.pair/telegram-groups.local.md` to .gitignore, "
          "fill telegram-groups.md per deployment, set BRIDGE_* env, "
          "run bridge with --pair-dir " + str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
