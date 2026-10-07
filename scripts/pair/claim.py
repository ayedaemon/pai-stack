#!/usr/bin/env python3
"""pair claim — atomic queue -> claims + stamp owner.

Usage: python3 scripts/pair/claim.py <slug> <owner: hermes|dsh|<id>>
Contract: pair/AGENT_CONTRACT.md section 4. Stdlib only.

Claim is os.rename (atomic on same filesystem). If the source is gone,
another agent claimed it first: re-list and pick another.
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(msg: str) -> int:
    print(f"claim: {msg}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return fail("usage: claim.py <slug> <owner>")
    slug, owner = argv[1], argv[2]
    if slug.startswith("_example"):
        return fail("refusing _example (template, never claim)")
    src = ROOT / "pair" / "queue" / f"{slug}.md"
    dst = ROOT / "pair" / "claims" / f"{slug}.md"
    if not src.is_file():
        return fail(f"already claimed or missing: pair/queue/{slug}.md")
    if dst.exists():
        return fail(f"already in claims: pair/claims/{slug}.md")
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"^status:.*$", "status: claimed", text, flags=re.M)
    text = re.sub(r"^owner:.*$", f"owner: {owner}", text, flags=re.M)
    src.write_text(text, encoding="utf-8")
    # Atomic lock: os.rename is atomic on the same filesystem — the task is
    # visible in exactly one of queue/claims at any instant. A missing src
    # here means a peer won the race; re-list and pick another.
    try:
        src.rename(dst)
    except FileNotFoundError:
        return fail(f"lost race for {slug}: already claimed")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with (ROOT / "pair" / "log.md").open("a", encoding="utf-8") as f:
        f.write(f"{ts} | {owner} | claim | {slug} | queue->claims\n")
    print(f"claimed {slug} as {owner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
