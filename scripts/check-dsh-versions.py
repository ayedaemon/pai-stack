#!/usr/bin/env python3
"""check-dsh-versions.py — fail fast on DSH version-pin drift.

Version pins live in several places by design (.env.example template,
compose defaults, Dockerfile ARG defaults, plugin package.json). This
stdlib-only script asserts they agree, so a bump in one place without the
others fails here instead of surfacing as a half-upgraded container:

1. Registry pins agree across .env.example, docker-compose.yaml
   (:-defaults) and dsh/Dockerfile (ARG defaults):
   DSH_VERSION, DSH_REMOTE_PLUGIN_VERSION, DSH_MNEMON_PLUGIN_VERSION,
   DSH_AUTOMATION_PLUGIN_VERSION, PLAYWRIGHT_VERSION.
2. All dsh-pai-*/package.json share one version (the entrypoint upgrade
   gate keys the whole tree off dsh-pai-notebook — bump them in lockstep).
3. dsh-pai-web's `playwright` dependency matches PLAYWRIGHT_VERSION.
4. Every DSH_* gate read by dsh/docker-entrypoint.sh is wired through
   docker-compose.yaml and documented in .env.example (catches dead
   gates like the historical DSH_WITH_PAI_PLUGINS, which was read but
   never set anywhere).
5. The live .env does not silently contradict .env.example. Checks 1-4
   only ever compare committed files, so a stale .env passes every one
   of them: compose resolves `${VAR:-default}` against .env first, and
   the .env value wins. Editing the compose default and .env.example
   then looks like it took effect while the running container keeps the
   old value — the exact failure this check was added after. Pins
   diverge as errors (a version in .env that differs from the committed
   template means one of the two is lying); gates diverge as warnings,
   because a per-machine override is a legitimate thing to want. Pass
   --strict to promote warnings to errors.

Usage: make dsh-versions-check (exit 0 = in sync, 1 = drift found).
      --strict also fails on .env gate overrides.
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO / ".env.example"
ENV_LIVE = REPO / ".env"
COMPOSE = REPO / "docker-compose.yaml"
DOCKERFILE = REPO / "dsh" / "Dockerfile"
ENTRYPOINT = REPO / "dsh" / "docker-entrypoint.sh"
PLUGINS = REPO / "dsh" / "plugins"

# .env name -> Dockerfile ARG name (compose maps them 1:1 via build args).
PIN_VARS = {
    "DSH_VERSION": "DSH_VERSION",
    "DSH_REMOTE_PLUGIN_VERSION": "REMOTE_PLUGIN_VERSION",
    "DSH_MNEMON_PLUGIN_VERSION": "MNEMON_PLUGIN_VERSION",
    "DSH_AUTOMATION_PLUGIN_VERSION": "AUTOMATION_PLUGIN_VERSION",
    "DSH_REWIND_PLUGIN_VERSION": "REWIND_PLUGIN_VERSION",
    "DSH_AUTOCONTINUE_PLUGIN_VERSION": "AUTOCONTINUE_PLUGIN_VERSION",
    "DSH_SUGGEST_PROMPT_PLUGIN_VERSION": "SUGGEST_PROMPT_PLUGIN_VERSION",
    "DSH_PROMPT_LIBRARY_PLUGIN_VERSION": "PROMPT_LIBRARY_PLUGIN_VERSION",
    "PLAYWRIGHT_VERSION": "PLAYWRIGHT_VERSION",
}

PAI_PLUGINS = [
    "dsh-pai-notebook",
    "dsh-pai-adr",
    "dsh-pai-design",
    "dsh-pai-terrain",
    "dsh-pai-git",
    "dsh-pai-web",
]

errors: list[str] = []
warnings: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        errors.append(msg)


def warn(cond: bool, msg: str, strict: bool) -> None:
    """A non-fatal finding. `--strict` promotes it to an error."""
    if cond:
        print("PASS " + msg)
    elif strict:
        print("FAIL " + msg + "  (--strict)")
        errors.append(msg)
    else:
        print("WARN " + msg)
        warnings.append(msg)


def env_val(text: str, name: str) -> str | None:
    """Value of `NAME="v"` or `NAME=v`, or None if unset.

    Tolerant of unquoted values because the live .env is hand-edited and not
    every key was quoted (DSH_PORT=9229, for one).
    """
    m = re.search(rf'^{name}="([^"]*)"', text, re.M)
    if m:
        return m.group(1)
    m = re.search(rf"^{name}=([^\s#]+)", text, re.M)
    return m.group(1) if m else None


def check_live_env(env_example_text: str, gates: list[str], strict: bool) -> None:
    """Check 5: the live .env must not silently contradict .env.example.

    Compose resolves `${VAR:-default}` against .env *before* the default, so
    the .env value is the one that reaches the container. Every other check in
    this script compares committed files only, which is why a .env left behind
    after a default change passes all of them and then quietly wins at runtime.

    Keys absent from .env are skipped: a partial .env is legitimate and falls
    back to the compose default, which checks 1-4 already cover.
    """
    if not ENV_LIVE.exists():
        print("SKIP  live .env not present (fresh clone) — checks 1-4 cover the committed defaults")
        return

    live_text = ENV_LIVE.read_text()

    # Pins first: a .env carrying a different version than the committed
    # template is not a per-machine preference, it means one of the two is
    # stale and the next rebuild silently changes behaviour.
    for env_name in PIN_VARS:
        want = env_val(env_example_text, env_name)
        got = env_val(live_text, env_name)
        if got is None:
            continue
        check(
            got == want,
            f"live .env {env_name} matches .env.example ({got!r} vs {want!r})",
        )

    # Gates second: overriding a gate per-machine is a legitimate thing to
    # want (e.g. telegram off locally), so divergence is reported, not fatal.
    # The message is phrased to read correctly either way — the PASS/WARN
    # prefix carries the verdict, not the wording.
    for gate in gates:
        want = env_val(env_example_text, gate)
        got = env_val(live_text, gate)
        if got is None or want is None:
            continue
        warn(
            got == want,
            f"live .env {gate}={got!r} vs .env.example {want!r} "
            f"(compose prefers .env, so {got!r} is what the container gets)",
            strict,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--strict",
        action="store_true",
        help="also fail when the live .env overrides a gate from .env.example",
    )
    args = ap.parse_args()

    env_text = ENV_EXAMPLE.read_text()
    compose_text = COMPOSE.read_text()
    docker_text = DOCKERFILE.read_text()
    entry_text = ENTRYPOINT.read_text()

    for env_name, arg_name in PIN_VARS.items():
        v_env = env_val(env_text, env_name)
        m_compose = re.search(rf"{arg_name}: \${{{env_name}:-(.*?)}}", compose_text)
        v_compose = m_compose.group(1) if m_compose else None
        m_docker = re.search(rf"^ARG {arg_name}=(.+)$", docker_text, re.M)
        v_docker = m_docker.group(1).strip() if m_docker else None
        check(v_env is not None, f"{env_name} present in .env.example")
        check(
            v_env is not None and v_env == v_compose == v_docker,
            f"{env_name} agrees (.env.example={v_env} compose={v_compose} Dockerfile={v_docker})",
        )

    pai_versions = {}
    for plugin in PAI_PLUGINS:
        pkg = json.loads((PLUGINS / plugin / "package.json").read_text())
        pai_versions[plugin] = pkg["version"]
    check(
        len(set(pai_versions.values())) == 1,
        f"pai plugins in lockstep {pai_versions}",
    )
    web_pkg = json.loads((PLUGINS / "dsh-pai-web" / "package.json").read_text())
    pw_pin = env_val(env_text, "PLAYWRIGHT_VERSION")
    check(
        web_pkg["dependencies"].get("playwright") == pw_pin,
        f"dsh-pai-web playwright dep matches PLAYWRIGHT_VERSION ({web_pkg['dependencies'].get('playwright')} vs {pw_pin})",
    )

    # SEED_LOCALE was dropped from the pattern: that gate is gone (the store it
    # wrote was never read by DSH, which resolves locale from Accept-Language).
    gates = sorted(set(re.findall(r"DSH_(?:WITH_\w+|DISABLE_WEB_SEARCH)", entry_text)))
    for gate in gates:
        in_compose = f"{gate}:" in compose_text or "${" + gate in compose_text
        check(in_compose, f"gate {gate} wired in docker-compose.yaml")
        check(f"{gate}=" in env_text, f"gate {gate} documented in .env.example")

    # Single joint tree: the old per-plugin /opt/dsh-*-seed dirs must not
    # come back (they duplicated ~300MB of image layers as strict subsets
    # of the final tree). /opt/dsh-seed is the only seed dir allowed.
    for path, label in ((DOCKERFILE, "dsh/Dockerfile"), (ENTRYPOINT, "dsh/docker-entrypoint.sh")):
        text = path.read_text()
        olds = sorted(set(re.findall(r"/opt/dsh-(?:remote|mnemon|auto|telegram|pai)-seed", text)))
        check(not olds, f"no per-plugin seed dirs in {label}" + (f" (found {olds})" if olds else ""))
        check("/opt/dsh-seed" in text, f"single joint seed dir referenced in {label}")

    # Check 5: the live .env is the value compose actually resolves against,
    # so it gets compared against the committed template too.
    check_live_env(env_text, gates, args.strict)

    if errors:
        print(f"\n{len(errors)} drift problem(s) found.", flush=True)
        if warnings:
            print(f"{len(warnings)} warning(s) (use --strict to fail on these).", flush=True)
        return 1
    if warnings:
        print(f"\nAll DSH pins and gates in sync ({len(warnings)} .env override warning(s)).", flush=True)
        return 0
    print("\nAll DSH pins and gates in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
