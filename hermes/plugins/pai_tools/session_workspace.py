#!/usr/bin/env python3
"""Session workspace resolution for pai-stack Hermes plugins.

The workspace attached to a session is owned by the Hermes runtime, not by
pai-stack. `agent.runtime_cwd` is the single source of truth upstream:

  * `scoped_session_cwd()` — the cwd pinned for THIS session (a ContextVar set
    when a workspace is attached; see tui_gateway/session_workdir.py).
  * `TERMINAL_CWD` — the process/profile-level cwd, bridged from the
    `terminal.cwd` config key at gateway startup.

Resolution order, first hit that is an existing directory wins:

  1. the session's pinned cwd          — a workspace attached to this session
  2. `TERMINAL_CWD`                   — the active profile's configured cwd
  3. `WORKSPACE_DIR` / `HERMES_DATA_DIR` — the container's workspace mount

There is deliberately NO `os.getcwd()` fallback: under Hermes the launch dir is
the package tree (`/opt/hermes`), and writing `.project/` there would create a
vault outside every real workspace. If nothing resolves, raise — a loud failure
beats a vault in the wrong tree.
"""

import os
from pathlib import Path
from typing import Optional

_SESSION_CWD_ENV = "TERMINAL_CWD"
_WORKSPACE_ENV_CANDIDATES = ("WORKSPACE_DIR", "WORKSPACE_PATH", "HERMES_DATA_DIR")


class WorkspaceUnresolved(RuntimeError):
    """No workspace could be resolved for this session."""


def _first_existing_dir(candidates) -> Optional[Path]:
    for raw in candidates:
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if path.is_dir():
            return path
    return None


def _session_pinned_cwd() -> str:
    """The cwd pinned for this session, or "" if the runtime has none."""
    try:
        from agent.runtime_cwd import scoped_session_cwd
    except Exception:
        return ""
    try:
        return scoped_session_cwd() or ""
    except Exception:
        return ""


def session_workspace() -> Path:
    """Return the workspace directory attached to the current session.

    Raises WorkspaceUnresolved when nothing usable is configured, so callers
    surface an actionable error instead of silently writing somewhere else.
    """
    resolved = _first_existing_dir(
        [
            _session_pinned_cwd(),
            os.environ.get(_SESSION_CWD_ENV, ""),
            *(os.environ.get(name, "") for name in _WORKSPACE_ENV_CANDIDATES),
        ]
    )
    if resolved is None:
        raise WorkspaceUnresolved(
            "No workspace is attached to this session, and neither "
            f"{_SESSION_CWD_ENV} nor {'/'.join(_WORKSPACE_ENV_CANDIDATES)} points at "
            "an existing directory. Attach a workspace to the session, or set "
            "`terminal.cwd` in hermes/config.yaml."
        )
    return resolved


def project_dir(subpath: str = "") -> Path:
    """Return `<session workspace>/.project[/subpath]` without creating it."""
    base = session_workspace() / ".project"
    return base / subpath if subpath else base
