#!/usr/bin/env python3
"""Fallback applier for kanban.default_model — idempotent, line-number agnostic.
Edits hermes_cli/config_defaults.py and hermes_cli/kanban_db_dispatch.py in-place.
"""
from pathlib import Path

ROOT = Path("/opt/hermes")

CONFIG_INSERT = """        # Board-wide default model for spawned workers. Accepts the
        # ``"provider/model"`` shorthand (e.g. ``openrouter/model-name``)
        # or a plain model name; when a provider is embedded, the
        # dispatcher passes ``--provider <name>`` so the worker resolves
        # the model against the intended backend instead of the assignee
        # profile's configured provider.
        #
        # Precedence (highest wins):
        #   1. Per-task ``model_override`` (set at create-time or via
        #      ``kanban set-model <id>``) -- always wins, ignores this field.
        #   2. This ``kanban.default_model`` setting -- applied to every
        #      task that has no override, regardless of assignee profile.
        #   3. Assignee profile's own ``model`` config -- the legacy
        #      behaviour, when ``kanban.default_model`` is empty/unset.
        #
        # Empty string (default) preserves legacy behaviour.
        "default_model": "","""

KANBAN_ELSE = """    else:
        # No per-task override -- fall through to the board-wide default
        # if one is configured. Empty/unset = legacy "use the profile's
        # own model" behaviour, so unset boards keep working unchanged.
        from hermes_cli.config import load_config as _load_cfg
        try:
            _kb_default_model = (
                (_load_cfg().get("kanban") or {}).get("default_model") or ""
            ).strip()
        except Exception:
            # Config load failures must NOT block the dispatcher -- better
            # to fall back to the legacy "profile model" path than to
            # refuse to spawn a worker.
            _kb_default_model = ""
        if _kb_default_model:
            cmd.extend(["-m", _kb_default_model])
            # If the model name contains a /, treat the part before it as
            # the provider and pin --provider accordingly.
            if "/" in _kb_default_model:
                _kb_provider, _kb_rest = _kb_default_model.split("/", 1)
                if _kb_provider and _kb_rest:
                    cmd.extend(["--provider", _kb_provider])

"""

def patch_config_defaults():
    p = ROOT / "hermes_cli" / "config_defaults.py"
    t = p.read_text()
    if '"default_model"' in t and "kanban" in t:
        print("config_defaults.py already patched")
        return
    # Insert after the line containing '"default_assignee": ""'
    idx = t.find('"default_assignee": ""')
    if idx == -1:
        raise RuntimeError("could not find default_assignee insertion point")
    # Find the end of that line
    line_end = t.find('\n', idx)
    if line_end == -1:
        raise RuntimeError("could not find end of default_assignee line")
    new_t = t[:line_end + 1] + CONFIG_INSERT + '\n' + t[line_end + 1:]
    p.write_text(new_t)
    print("patched config_defaults.py")

def patch_kanban_db_dispatch():
    p = ROOT / "hermes_cli" / "kanban_db_dispatch.py"
    t = p.read_text()
    if "default_model" in t and "_load_cfg" in t:
        print("kanban_db_dispatch.py already patched")
        return

    lines = t.split('\n')

    # Find "if task.model_override:" line — in kanban_db_dispatch.py this is
    # where the dispatcher builds the worker command with -m / --provider.
    model_override_idx = None
    for i, line in enumerate(lines):
        if 'if task.model_override:' in line:
            model_override_idx = i
            break

    if model_override_idx is None:
        raise RuntimeError("could not find kanban_db_dispatch insertion point (no model_override)")

    # Determine indentation of the if block
    base_indent = len(lines[model_override_idx]) - len(lines[model_override_idx].lstrip())
    # Adjust KANBAN_ELSE to match the base indentation
    else_raw = KANBAN_ELSE.rstrip('\n').split('\n')
    min_indent = min((len(l) - len(l.lstrip()) for l in else_raw if l.strip()), default=0)
    else_block = '\n'.join(' ' * (base_indent + (len(l) - len(l.lstrip()) - min_indent)) + l.lstrip() if l.strip() else '' for l in else_raw)

    # Walk forward from model_override to find the end of its block.
    # Skip blank lines and comments — only act on code lines.
    insert_idx = None
    for j in range(model_override_idx + 1, len(lines)):
        line = lines[j]
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            insert_idx = j
            break

    if insert_idx is None:
        raise RuntimeError("could not find kanban_db_dispatch insertion point (end of block)")

    new_lines = lines[:insert_idx] + else_block.split('\n') + [''] + lines[insert_idx:]
    p.write_text('\n'.join(new_lines))
    print("patched kanban_db_dispatch.py")

if __name__ == "__main__":
    patch_config_defaults()
    patch_kanban_db_dispatch()
    print("fallback patch applied")
