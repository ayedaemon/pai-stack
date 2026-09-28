"""pai-stack native tools for Hermes — registered via plugins/pai_tools.

Ports the four retired mcp-server tools to the native plugin API so the
mcp-server container is no longer needed:

- pai_code_intel   — tree-sitter AST symbol search, call graphs, repo maps
- pai_notebook_ops — file-based Research Brain vault (Markdown + frontmatter)
- pai_adr_ops      — Living ADRs with SHA-256 symbol drift detection
- pai_docker_ops   — pai-stack container management via the Docker socket
"""

from plugins.pai_tools import adr_ops, code_intel, docker_ops, notebook_ops


def register(ctx) -> None:
    """Register all pai-stack tools. Called once by the plugin loader."""
    ctx.register_tool(
        name="pai_code_intel",
        toolset="pai",
        schema=code_intel.SCHEMA,
        handler=code_intel.handle,
        check_fn=code_intel.check_available,
        emoji="🔍",
    )
    ctx.register_tool(
        name="pai_notebook_ops",
        toolset="pai",
        schema=notebook_ops.SCHEMA,
        handler=notebook_ops.handle,
        emoji="📓",
    )
    ctx.register_tool(
        name="pai_adr_ops",
        toolset="pai",
        schema=adr_ops.SCHEMA,
        handler=adr_ops.handle,
        emoji="🏛",
    )
    ctx.register_tool(
        name="pai_docker_ops",
        toolset="pai",
        schema=docker_ops.SCHEMA,
        handler=docker_ops.handle,
        check_fn=docker_ops.check_available,
        emoji="🐳",
    )
