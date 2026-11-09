"""pai-stack native tools for Hermes — registered via plugins/pai_tools.

- pai_notebook_ops — Research Brain wiki (Markdown + frontmatter)
- pai_adr_ops      — Living ADRs with SHA-256 symbol drift detection
- pai_ops_design_ops — OpenDesign REST bridge (visual generation / mockups)

Docker is intentionally NOT a tool: both agents drive the mounted
/var/run/docker.sock with the native `docker` + `docker compose` binaries
(see the `docker` skill for socket scope, smart --format output, and
help-first flag discovery).

`pai_code_intel` was removed 2026-10-04. Code intelligence is intentionally
absent from pai-stack; a dedicated lightweight tool replaces it.

Each tool module is imported inside its own registration guard: these modules
resolve the session workspace at call time, and a failure in one must not
unregister the others. Previously a single bad import took the whole plugin
(and every tool in it) down at load.
"""

import importlib

_TOOLS = (
    ("pai_notebook_ops", "pai_tools.notebook_ops", "📓"),
    ("pai_adr_ops", "pai_tools.adr_ops", "🏛"),
    ("pai_ops_design_ops", "pai_tools.ops_design_ops", "🎨"),
    ("pai_web_ops", "pai_tools.web_ops", "🌐"),
)


def register(ctx) -> None:
    """Register all pai-stack tools. Called once by the plugin loader."""
    for tool_name, module_path, emoji in _TOOLS:
        try:
            module = importlib.import_module(f"plugins.{module_path}")
        except Exception as exc:  # noqa: BLE001 - one bad tool must not sink the rest
            print(f"[pai_tools] failed to load {tool_name}: {exc}")
            continue
        try:
            ctx.register_tool(
                name=tool_name,
                toolset="pai",
                schema=module.SCHEMA,
                handler=module.handle,
                emoji=emoji,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[pai_tools] failed to register {tool_name}: {exc}")
