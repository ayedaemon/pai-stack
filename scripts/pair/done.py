#!/usr/bin/env python3
"""pair done — claims -> done + verdict + secret gate.

Usage: python3 scripts/pair/done.py <slug> "<verdict one-liner>"
Stdlib only. Refuses files carrying raw secrets (env refs only).
"""
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pairlib import find_pair  # noqa: E402

PAIR = find_pair()
SECRET = re.compile(
    r"sk-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{8,}"
    r"|xox[bpas]-[A-Za-z0-9-]{8,}|Bearer [A-Za-z0-9._\-]{8,}"
)


def fail(msg: str) -> int:
    print(f"done: {msg}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return fail('usage: done.py <slug> "<verdict>"')
    slug = argv[1]
    verdict = argv[2] if len(argv) > 2 else "done"
    src = PAIR / "claims" / f"{slug}.md"
    dst = PAIR / "done" / f"{slug}.md"
    if not src.is_file():
        return fail(f"not in claims: {PAIR.name}/claims/{slug}.md")
    text = src.read_text(encoding="utf-8")
    if SECRET.search(text):
        return fail(f"REFUSED — possible raw secret in {src} (use env refs)")
    text = re.sub(r"^status:.*$", "status: done", text, flags=re.M)
    if "## Verdict" not in text:
        text = text.rstrip() + f"\n\n## Verdict\n{verdict}\n"
    else:
        text = text.rstrip() + f"\n{verdict}\n"
    src.write_text(text, encoding="utf-8")
    src.rename(dst)  # atomic: visible in exactly one of claims/done
    owner = "unknown"
    m = re.search(r"^owner:\s*(.+)$", text, flags=re.M)
    if m:
        owner = m.group(1).strip()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with (PAIR / "log.md").open("a", encoding="utf-8") as f:
        f.write(f"{ts} | {owner} | done | {slug} | {verdict}\n")
    print(f"done {slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
