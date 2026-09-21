"""Code intelligence tool — tree-sitter based code analysis for pai-stack.

Provides symbol search, call graphs, impact analysis, and project structure
analysis. Runs in-process within mcp-server.

The workspace may contain multiple projects. Hermes scopes queries by passing
scope="<EXECUTION_DIR>" to narrow results to the active project.
"""

import json
import os
import sys
from pathlib import Path

WORKSPACE = os.environ.get("WORKSPACE_PATH", "/opt/data/workspace")

_project_registered = False


def _ensure_project():
    """Register workspace with mcp-server-tree-sitter on first use."""
    global _project_registered
    if _project_registered:
        return
    try:
        from mcp_server_tree_sitter.api import register_project
        register_project(path=WORKSPACE, name="workspace", description="pai-stack workspace")
        _project_registered = True
    except Exception as e:
        print(json.dumps({"error": f"Failed to register project: {e}"}))
        sys.exit(1)


def _resolve_path(path_str):
    """Resolve a relative path against workspace. Returns absolute path."""
    if not path_str:
        return WORKSPACE
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(Path(WORKSPACE) / p)


def _handle_find_code(args):
    """Search for implementations via text search + symbol extraction."""
    from mcp_server_tree_sitter.api import find_text, get_symbols

    question = args.get("question", "")
    scope = _resolve_path(args.get("scope", WORKSPACE))

    results = {"question": question, "scope": scope, "matches": []}

    # Text search across the scope
    try:
        text_results = find_text(
            project="workspace",
            pattern=question,
            scope=scope,
            max_results=20,
        )
        if text_results:
            results["matches"].extend(
                [{"type": "text_match", **r} for r in (text_results if isinstance(text_results, list) else [text_results])]
            )
    except Exception:
        pass

    # Also try to find matching symbols
    try:
        from mcp_server_tree_sitter.api import find_usage
        usage_results = find_usage(
            project="workspace",
            symbol=question.split()[-1] if question.split() else question,
            scope=scope,
        )
        if usage_results:
            results["matches"].extend(
                [{"type": "symbol_usage", **r} for r in (usage_results if isinstance(usage_results, list) else [usage_results])]
            )
    except Exception:
        pass

    return results


def _handle_file_api(args):
    """Extract symbol signatures from a file without bodies."""
    from mcp_server_tree_sitter.api import get_symbols

    file_path = _resolve_path(args.get("file_path", ""))

    symbols = get_symbols(project="workspace", file_path=file_path)
    return {"file_path": file_path, "symbols": symbols}


def _handle_trace_calls(args):
    """Find callers or callees of a symbol."""
    from mcp_server_tree_sitter.api import find_usage, get_dependencies

    symbol = args.get("symbol", "")
    direction = args.get("direction", "in")
    depth = args.get("depth", 1)
    scope = _resolve_path(args.get("scope", WORKSPACE))

    results = {"symbol": symbol, "direction": direction, "depth": depth}

    if direction == "in":
        # Who calls this symbol?
        usage = find_usage(project="workspace", symbol=symbol, scope=scope)
        results["callers"] = usage
    else:
        # What does this symbol call?
        deps = get_dependencies(project="workspace", file_path=scope)
        results["callees"] = deps

    return results


def _handle_find_all(args):
    """Regex search across files."""
    from mcp_server_tree_sitter.api import find_text

    regex = args.get("regex", "")
    path = _resolve_path(args.get("path", WORKSPACE))

    results = find_text(
        project="workspace",
        pattern=regex,
        scope=path,
        max_results=100,
    )
    return {"pattern": regex, "path": path, "results": results}


def _handle_repo_map(args):
    """Analyze project structure."""
    from mcp_server_tree_sitter.api import analyze_project

    max_dirs = args.get("max_dirs", 5)
    analysis = analyze_project(project="workspace", scan_depth=max_dirs)
    return {"workspace": WORKSPACE, "analysis": analysis}


def _handle_check_freshness(args):
    """Clear cache and re-index."""
    from mcp_server_tree_sitter.api import clear_cache, register_project

    clear_cache(project="workspace")
    # Re-register to force re-index
    register_project(path=WORKSPACE, name="workspace", description="pai-stack workspace")
    return {"status": "ok", "message": "Cache cleared and project re-indexed"}


HANDLERS = {
    "find_code": _handle_find_code,
    "file_api": _handle_file_api,
    "trace_calls": _handle_trace_calls,
    "find_all": _handle_find_all,
    "repo_map": _handle_repo_map,
    "check_freshness": _handle_check_freshness,
}


def main():
    raw = os.environ.get("TOOL_INPUT", "{}")
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}))
        sys.exit(1)

    action = args.get("action")
    if not action or action not in HANDLERS:
        print(json.dumps({"error": f"Unknown action: {action}. Valid: {list(HANDLERS.keys())}"}))
        sys.exit(1)

    _ensure_project()

    try:
        result = HANDLERS[action](args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
