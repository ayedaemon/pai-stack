#!/usr/bin/env python3
"""opencode-free-models.py — list and validate OpenCode's keyless Zen models.

These slugs are NOT stable. They get retired upstream with no deprecation
notice here, and the failure is quiet in a specific way: terrain's
`terrain settings check-acp` keeps reporting {"available": true} because that
only proves the BINARY exists, and an LLM action then hangs until it times out.
`muse-spark-1.3-contributor-free` was pinned in terrain/opencode.json and in
hermes/opencode/opencode-delegate while being dead keylessly for weeks.

TWO SOURCES, TWO DIFFERENT JOBS — do not conflate them:

  * `opencode models` is the ONLY ground truth for what is reachable keylessly.
    It reflects the live Zen pool.
  * models.dev is a CATALOG. It still listed muse-spark-1.3-contributor-free at
    cost 0 long after the keyless pool dropped it, and it advertises ~50 "free"
    models where only ~10 are actually keyless. Use it only to ENRICH a model
    that the CLI already vouched for (context/output window). Never use it to
    decide availability, or this script will happily "validate" a dead slug.

For the same reason, never filter on a `-free` suffix: `big-pickle` is keyless
and has none.

Usage:
    opencode-free-models.py                      # ranked table
    opencode-free-models.py --min-context 500000 # only models that fit a big repo
    opencode-free-models.py check opencode/foo   # exit 1 if not keyless
    opencode-free-models.py allowlist            # emit ids for a shell allowlist
    docker exec terrain opencode models | opencode-free-models.py   # stdin

Exit codes: 0 ok · 1 (check mode) model not available keylessly · 2 usage/IO.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

MODELS_DEV = "https://models.dev/api.json"
CACHE_TTL_S = 6 * 3600
PROVIDER = "opencode"


def die(msg, code=2):
    print(f"opencode-free-models: {msg}", file=sys.stderr)
    sys.exit(code)


def read_live_models():
    """Models the CLI says are actually reachable keylessly.

    Accepts them on stdin so this can run on the host against a container:
        docker exec terrain opencode models | opencode-free-models.py
    """
    raw = ""
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
    if not raw.strip():
        exe = os.environ.get("OPENCODE_BIN", "opencode")
        try:
            raw = subprocess.run(
                [exe, "models"], capture_output=True, text=True, timeout=60, check=True
            ).stdout
        except FileNotFoundError:
            die(
                f"{exe} not found and nothing on stdin.\n"
                f"  Either install opencode, or pipe it from a container:\n"
                f"    docker exec terrain opencode models | {sys.argv[0]}"
            )
        except subprocess.CalledProcessError as e:
            die(f"{exe} models failed: {e.stderr.strip() or e.returncode}")
        except subprocess.TimeoutExpired:
            die(f"{exe} models timed out after 60s")

    ids = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith(PROVIDER + "/"):
            ids.append(line)
    return sorted(set(ids))


def read_catalog():
    """models.dev limits for context/output. Advisory only — never authoritative.

    Returns {} on any failure: a machine with no network still gets a usable
    (if unsorted-by-size) list, which beats a hard failure here.
    """
    cache = os.path.expanduser(
        os.environ.get(
            "OPENCODE_MODEL_CACHE", os.path.join("~", ".cache", "opencode-models.json")
        )
    )
    cache = os.path.expanduser(cache)
    try:
        fresh = os.path.exists(cache) and (time.time() - os.path.getmtime(cache) < CACHE_TTL_S)
    except OSError:
        fresh = False
    if fresh:
        try:
            with open(cache) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    try:
        # models.dev 403s the urllib default User-Agent; identify honestly.
        req = urllib.request.Request(
            MODELS_DEV, headers={"User-Agent": "pai-stack/opencode-free-models"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            prov = json.load(resp).get(PROVIDER, {}).get("models", {})
        limits = {
            # Keys here are BARE model ids (no "opencode/" prefix), even though
            # `opencode models` prints them prefixed. Normalise on the prefix, not
            # with split("/") — that raises on every key.
            mid[len(PROVIDER) + 1:] if mid.startswith(PROVIDER + "/") else mid: {
                "context": (mm.get("limit") or {}).get("context", 0),
                "output": (mm.get("limit") or {}).get("output", 0),
                # Advisory only. `status: deprecated` is upstream's early warning
                # that a slug is on its way out — useful for spotting a pin that
                # still works today but will not next month. Never use it to
                # decide availability; only `opencode models` decides that.
                "status": mm.get("status", ""),
                "vision": "image" in ((mm.get("modalities") or {}).get("input") or []),
            }
            for mid, mm in prov.items()
        }
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w") as fh:
            json.dump(limits, fh)
        return limits
    except Exception:
        return {}


def build_rows(live, limits):
    rows = []
    for mid in live:
        short = mid.split("/", 1)[-1]
        lim = limits.get(short, {})
        rows.append(
            {
                "id": mid,
                "short": short,
                "context": lim.get("context", 0),
                "output": lim.get("output", 0),
                "status": lim.get("status", ""),
                "vision": lim.get("vision", False),
            }
        )
    # Context first: Litho has to fit a whole repo, so window is the binding
    # constraint, not raw speed. Name is the tiebreak so output is stable
    # across runs when models.dev is unreachable.
    rows.sort(key=lambda r: (-r["context"], -r["output"], r["short"]))
    return rows


def cmd_list(rows, min_context):
    rows = [r for r in rows if r["context"] >= min_context] if min_context else rows
    if not rows:
        die(f"no keyless model meets --min-context {min_context}")
    width = max(len(r["id"]) for r in rows)
    print(f"{'MODEL'.ljust(width)}  {'CONTEXT':>9}  {'OUTPUT':>7}  NOTES")
    print("-" * (width + 32))
    for r in rows:
        ctx = f"{r['context']:,}" if r["context"] else "?"
        out = f"{r['output']:,}" if r["output"] else "?"
        notes = []
        if r["status"] == "deprecated":
            notes.append("DEPRECATED upstream")
        if r["vision"]:
            notes.append("accepts image input")
        if r["short"] == "big-pickle":
            notes.append("alias — backing model can change without the slug changing")
        print(f"{r['id'].ljust(width)}  {ctx:>9}  {out:>7}  {', '.join(notes)}")
    print(f"\n{len(rows)} keyless model(s), from `opencode models` (live).")
    if any(not r["context"] for r in rows):
        print("Context '?' = not in models.dev; sizes unavailable, ordering is by name.")


def cmd_check(rows, want):
    hit = next((r for r in rows if r["id"] == want or r["short"] == want), None)
    if hit:
        ctx = f"{hit['context']:,}" if hit["context"] else "?"
        print(f"OK  {hit['id']} is keyless (context {ctx}).")
        if hit["status"] == "deprecated":
            print(
                f"    WARNING: models.dev marks it status=deprecated. It still works\n"
                f"    today, but expect it to be retired — pick a replacement before it is.",
                file=sys.stderr,
            )
        return 0
    print(f"FAIL  {want} is NOT available keylessly.", file=sys.stderr)
    print("Live alternatives, largest context first:", file=sys.stderr)
    for r in rows[:5]:
        print(f"  {r['id']}", file=sys.stderr)
    return 1


def cmd_allowlist(rows):
    print(" ".join(r["id"] for r in rows))


def main(argv):
    args = argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    mode = "list"
    if args and args[0] in ("list", "check", "allowlist"):
        mode = args.pop(0)

    min_context = 0
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--min-context":
            if i + 1 >= len(args):
                die("--min-context needs a number")
            try:
                min_context = int(args[i + 1])
            except ValueError:
                die(f"--min-context expects a number, got {args[i + 1]!r}")
            i += 2
            continue
        if a.startswith("--min-context="):
            try:
                min_context = int(a.split("=", 1)[1])
            except ValueError:
                die(f"--min-context expects a number, got {a.split('=', 1)[1]!r}")
            i += 1
            continue
        rest.append(a)
        i += 1

    live = read_live_models()
    if not live:
        die("no keyless models reported by `opencode models`")
    rows = build_rows(live, read_catalog())

    if mode == "check":
        if not rest:
            die("check needs a model id, e.g. `check opencode/space-bunny-free`")
        return cmd_check(rows, rest[0])
    if mode == "allowlist":
        cmd_allowlist(rows)
        return 0
    cmd_list(rows, min_context)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
