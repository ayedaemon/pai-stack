#!/usr/bin/env python3
"""pair status — queue depth + active claims + STATE head.

Usage: python3 scripts/pair/status.py [--pair-dir <dir>] (run from project root)
Stdlib only. Runs on host, hermes, dsh, or any future agent container.
Resolves .pair/ (legacy pair/ fallback) via pairlib.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pairlib import find_pair  # noqa: E402


def show(title: str, d) -> None:
    print(f"== {d.parent.name}/{d.name} ==")
    try:
        names = sorted(p.name for p in d.iterdir() if p.name != ".gitkeep")
    except FileNotFoundError:
        print("(missing dir)")
        return
    if not names:
        print("(empty)")
    else:
        for n in names:
            print(n)


def main(argv: list[str] | None = None) -> None:
    pair_arg = None
    argv = argv if argv is not None else sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--pair-dir" and i + 1 < len(argv):
            pair_arg = argv[i + 1]
    PAIR = find_pair(pair_arg)
    show("queue", PAIR / "queue")
    show("claims", PAIR / "claims")
    show("done", PAIR / "done")
    print("== STATE.md head ==")
    state = PAIR / "STATE.md"
    if state.exists():
        for line in state.read_text(encoding="utf-8").splitlines()[:20]:
            print(line)
    else:
        print("(no STATE.md)")


if __name__ == "__main__":
    main()
