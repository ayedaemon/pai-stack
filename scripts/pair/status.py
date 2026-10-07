#!/usr/bin/env python3
"""pair status — queue depth + active claims + STATE head.

Usage: python3 scripts/pair/status.py  (run from repo root)
Stdlib only. Runs on host, hermes, dsh, or any future agent container.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def show(title: str, rel: str) -> None:
    d = ROOT / rel
    print(f"== {rel} ==")
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


def main() -> None:
    show("queue", "pair/queue")
    show("claims", "pair/claims")
    show("done", "pair/done")
    print("== STATE.md head ==")
    state = ROOT / "pair" / "STATE.md"
    if state.exists():
        for line in state.read_text(encoding="utf-8").splitlines()[:20]:
            print(line)
    else:
        print("(no STATE.md)")


if __name__ == "__main__":
    main()
