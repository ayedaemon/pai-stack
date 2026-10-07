"""pairlib — shared blackboard locator (stdlib only, no imports beyond stdlib).

The blackboard is `.pair/` (hidden + gitignored) in the project root:
`<project>/.pair/{queue,claims,done,pokes,log.md,STATE.md}`.
The lock is os.rename on the shared volume, not git — so the dir must live
on the shared mount, and must NOT be git-tracked.

Resolution order (first hit wins):
  1. explicit arg (--pair-dir / PAIR_DIR env)
  2. walk up from cwd: nearest `.pair/` with a queue/ dir, else legacy `pair/`
  3. this script's own repo: .pair/, else legacy pair/ (backwards compat)

Usage in helpers:
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pairlib import find_pair
    PAIR = find_pair()
"""
import os
from pathlib import Path


def find_pair(explicit: str | None = None) -> Path:
    for cand in (explicit, os.environ.get("PAIR_DIR")):
        if cand:
            p = Path(cand)
            if (p / "queue").is_dir():
                return p.resolve()
            if (p / ".pair" / "queue").is_dir():
                return (p / ".pair").resolve()
    here = Path.cwd().resolve()
    probes: list[Path] = [here, *here.parents]
    for name in (".pair", "pair"):  # hidden first, legacy fallback
        for probe in probes:
            if probe.name == name and (probe / "queue").is_dir():
                return probe
            cand = probe / name
            if (cand / "queue").is_dir():
                return cand.resolve()
    home = Path(__file__).resolve().parents[2]
    for name in (".pair", "pair"):
        if (home / name / "queue").is_dir():
            return home / name
    return home / ".pair"
