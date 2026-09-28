"""pai_code_intel — tree-sitter based code intelligence (native Hermes tool).

Provides symbol search, call graphs, impact analysis, and project structure
analysis via the `mcp-server-tree-sitter==0.7.0` backend. Runs in-process.

The workspace may contain multiple projects. Scope queries by passing
scope="<EXECUTION_DIR>" to narrow results to the active project.
"""

import json
import os
from pathlib import Path

WORKSPACE = (
    os.environ.get("WORKSPACE_PATH")
    or os.environ.get("WORKSPACE_DIR")
    or os.environ.get("HERMES_DATA_DIR", "/opt/data/workspace")
)

SCHEMA = {
    "name": "pai_code_intel",
    "description": "Code intelligence: symbol search, call graphs, impact analysis, project structure via tree-sitter AST parsing. The workspace may contain multiple projects — scope queries to your EXECUTION_DIR.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["find_code", "file_api", "trace_calls", "find_all", "repo_map", "check_freshness"],
                "description": "Operation to perform. find_code: search for implementations via text+AST. file_api: extract symbol signatures without bodies. trace_calls: find callers/callees of a symbol. find_all: regex search across files. repo_map: analyze project structure. check_freshness: clear cache and re-index.",
            },
            "question": {
                "type": "string",
                "description": "Natural language question for find_code (e.g. 'Where is user authentication handled?').",
            },
            "scope": {
                "type": "string",
                "description": "Directory or file path to scope the search (e.g. EXECUTION_DIR or EXECUTION_DIR/src).",
            },
            "file_path": {
                "type": "string",
                "description": "File path for file_api (e.g. 'src/main.py').",
            },
            "symbol": {
                "type": "string",
                "description": "Symbol name for trace_calls (e.g. 'loginUser').",
            },
            "direction": {
                "type": "string",
                "enum": ["in", "out"],
                "description": "For trace_calls: in=who calls this symbol, out=what does this symbol call.",
            },
            "depth": {
                "type": "integer",
                "description": "Traversal depth for trace_calls (default: 1).",
            },
            "regex": {
                "type": "string",
                "description": "Regex pattern for find_all (e.g. 'TODO|FIXME').",
            },
            "path": {
                "type": "string",
                "description": "Directory or file path for find_all.",
            },
            "max_dirs": {
                "type": "integer",
                "description": "Scan depth for repo_map project analysis (default: 5).",
            },
        },
        "required": ["action"],
    },
}


def check_available() -> bool:
    """Gate dispatch until the tree-sitter backend is importable."""
    try:
        import mcp_server_tree_sitter  # noqa: F401
        return True
    except Exception:
        return False


def _ctx():
    """Return (project, language_registry) for the workspace, registering first use."""
    from mcp_server_tree_sitter import api

    container = api.get_container()
    registry = container.project_registry
    try:
        project = registry.get_project("workspace")
    except Exception:
        api.register_project(path=WORKSPACE, name="workspace", description="pai-stack workspace")
        project = registry.get_project("workspace")
    return project, container.language_registry


def _resolve_path(path_str):
    """Resolve a relative path against workspace. Returns absolute path."""
    if not path_str:
        return WORKSPACE
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(Path(WORKSPACE) / p)


def _in_scope(match_file, scope):
    """Check whether a match file path falls inside the scope directory."""
    if not match_file or not scope:
        return True
    f = str(match_file)
    if not os.path.isabs(f):
        f = os.path.join(WORKSPACE, f)
    return os.path.normpath(f).startswith(os.path.normpath(scope) + os.sep) or os.path.normpath(f) == os.path.normpath(scope)


def _scope_pattern(abs_scope):
    """Convert an absolute scope dir/file into a project-relative glob.

    Bounds the backend scan itself (pathlib glob on the project root) instead
    of scanning the whole workspace and filtering afterwards. Returns None
    when the scope is the workspace root or lies outside it.
    """
    try:
        rel = os.path.relpath(os.path.normpath(abs_scope), os.path.normpath(WORKSPACE))
    except ValueError:
        return None
    if rel in (".", os.curdir):
        return None
    if rel.startswith(".." + os.sep) or rel == "..":
        return None
    full = os.path.join(WORKSPACE, rel)
    if os.path.isdir(full):
        return rel + "/**/*"
    return rel


def _handle_find_code(args):
    """Search for implementations via text search + symbol-mention search."""
    from mcp_server_tree_sitter.tools.search import search_text

    project, _ = _ctx()
    question = args.get("question", "")
    scope = _resolve_path(args.get("scope", WORKSPACE))

    results = {"question": question, "scope": scope, "matches": []}

    try:
        text_results = search_text(project, question, _scope_pattern(scope), max_results=20)
        results["matches"].extend(
            [{"type": "text_match", **r} for r in text_results if _in_scope(r.get("file"), scope)]
        )
    except Exception:
        pass

    # Also search for the likely symbol name (last word) as a whole word,
    # catching definitions and usages the plain-text pass may rank lower.
    try:
        symbol = question.split()[-1] if question.split() else question
        if symbol and symbol != question:
            usage_results = search_text(project, symbol, _scope_pattern(scope), max_results=20, whole_word=True)
            results["matches"].extend(
                [{"type": "symbol_usage", **r} for r in usage_results if _in_scope(r.get("file"), scope)]
            )
    except Exception:
        pass

    return results


def _handle_file_api(args):
    """Extract symbol signatures from a file without bodies."""
    from mcp_server_tree_sitter.tools.analysis import extract_symbols

    project, lang_reg = _ctx()
    file_path = _resolve_path(args.get("file_path", ""))

    symbols = extract_symbols(project, file_path, lang_reg)
    return {"file_path": file_path, "symbols": symbols}


def _handle_trace_calls(args):
    """Find callers (whole-word mentions) or callees (file imports/includes)."""
    from mcp_server_tree_sitter.tools.analysis import find_dependencies
    from mcp_server_tree_sitter.tools.search import search_text

    project, lang_reg = _ctx()
    symbol = args.get("symbol", "")
    direction = args.get("direction", "in")
    depth = args.get("depth", 1)
    scope = _resolve_path(args.get("scope", WORKSPACE))

    results = {"symbol": symbol, "direction": direction, "depth": depth}

    if direction == "in":
        # Who mentions/calls this symbol? (whole-word search, scope-filtered)
        usage = search_text(project, symbol, _scope_pattern(scope), max_results=100, whole_word=True)
        results["callers"] = [r for r in usage if _in_scope(r.get("file"), scope)]
    else:
        # What does this file depend on?
        deps = find_dependencies(project, scope, lang_reg)
        results["callees"] = deps

    return results


def _handle_find_all(args):
    """Regex search across files."""
    from mcp_server_tree_sitter.tools.search import search_text

    project, _ = _ctx()
    regex = args.get("regex", "")
    path = _resolve_path(args.get("path", WORKSPACE))

    matches = search_text(project, regex, _scope_pattern(path), max_results=100, use_regex=True)
    matches = [r for r in matches if _in_scope(r.get("file"), path)]
    return {"pattern": regex, "path": path, "results": matches}


def _handle_repo_map(args):
    """Analyze project structure."""
    from mcp_server_tree_sitter.tools.analysis import analyze_project_structure

    project, lang_reg = _ctx()
    max_dirs = args.get("max_dirs", 5)
    analysis = analyze_project_structure(project, lang_reg, scan_depth=max_dirs)
    return {"workspace": WORKSPACE, "analysis": analysis}


def _handle_check_freshness(args):
    """Clear cache and re-index."""
    from mcp_server_tree_sitter import api

    api.clear_cache(project="workspace")
    # Re-register to force re-index
    api.register_project(path=WORKSPACE, name="workspace", description="pai-stack workspace")
    return {"status": "ok", "message": "Cache cleared and project re-indexed"}


HANDLERS = {
    "find_code": _handle_find_code,
    "file_api": _handle_file_api,
    "trace_calls": _handle_trace_calls,
    "find_all": _handle_find_all,
    "repo_map": _handle_repo_map,
    "check_freshness": _handle_check_freshness,
}


def handle(args, **kwargs) -> str:
    """Hermes tool handler — dispatch an action, always returning a JSON string."""
    if not isinstance(args, dict):
        return json.dumps({"error": "Invalid arguments"})
    action = args.get("action")
    if not action or action not in HANDLERS:
        return json.dumps({"error": f"Unknown action: {action}. Valid: {list(HANDLERS.keys())}"})
    try:
        result = HANDLERS[action](args)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
