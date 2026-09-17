"""MCP Server for pai-stack — discovers and exposes tools + skills from shared folder."""

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Any
from pathlib import Path

from pydantic import ConfigDict
from mcp.server import MCPServer
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from starlette.requests import Request
from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger("pai-mcp")

TOOLS_DIR = Path("/app/tools")
SKILLS_DIR = Path("/app/skills")
KB_DIR = Path("/app/kb")

mcp = MCPServer("pai-tools")


class DynamicArgsModel(ArgModelBase):
    """Flexible model that accepts arbitrary arguments from tool.json schemas."""
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def discover_tools():
    """Scan TOOLS_DIR for tool.json files and register each as an MCP tool."""
    if not TOOLS_DIR.exists():
        log.warning("tools directory not found: %s", TOOLS_DIR)
        return

    for tool_dir in sorted(TOOLS_DIR.iterdir()):
        if not tool_dir.is_dir():
            continue
        config_path = tool_dir / "tool.json"
        if not config_path.exists():
            continue
        try:
            config = json.loads(config_path.read_text())
            _register_tool(config, tool_dir)
            log.info("registered tool: %s", config["name"])
        except Exception as e:
            log.error("failed to register tool %s: %s", tool_dir.name, e)


def _register_tool(config: dict, tool_dir: Path):
    """Register a single tool from its config and directory."""
    name = config["name"]
    description = config.get("description", "")
    command = config["command"]
    timeout = config.get("timeout", 60)
    input_schema = config.get("inputSchema", {"type": "object", "properties": {}})

    async def handler(**arguments) -> str:
        env = {**os.environ, "TOOL_INPUT": json.dumps(arguments)}
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(tool_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                return json.dumps({"error": stderr.decode().strip() or "tool failed"})
            return stdout.decode().strip()
        except asyncio.TimeoutError:
            return json.dumps({"error": f"tool timed out after {timeout}s"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    tool = Tool(
        fn=handler,
        name=name,
        description=description,
        parameters=input_schema,
        fn_metadata=FuncMetadata(
            arg_model=DynamicArgsModel,
            output_schema=None,
            output_model=None,
            wrap_output=False,
        ),
        is_async=True,
    )
    mcp._tool_manager._tools[name] = tool


def discover_skills():
    """Scan SKILLS_DIR for SKILL.md files and expose them as MCP resources."""
    if not SKILLS_DIR.exists():
        log.warning("skills directory not found: %s", SKILLS_DIR)
        return

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            _register_skill(skill_dir.name, skill_file)
            log.info("registered skill: %s", skill_dir.name)
        except Exception as e:
            log.error("failed to register skill %s: %s", skill_dir.name, e)


def _register_skill(name: str, skill_file: Path):
    """Register a skill as an MCP resource so Hermes can read it."""
    @mcp.resource(f"skill://{name}")
    def read_skill() -> str:
        return skill_file.read_text()




def register_templates():
    """Register project scaffolding templates as MCP resources under skill://templates/project/*."""
    tpl_dir = KB_DIR / "Projects" / "_TEMPLATE"
    if not tpl_dir.exists():
        log.warning("template directory not found: %s", tpl_dir)
        return

    for tpl_file in sorted(tpl_dir.rglob("*.md")):
        rel = tpl_file.relative_to(tpl_dir).as_posix()
        uri = f"skill://templates/project/{rel}"
        _register_template_resource(uri, tpl_file)


def _register_template_resource(uri: str, file_path: Path):
    @mcp.resource(uri)
    def read_template() -> str:
        return file_path.read_text()

    log.info("registered template resource: %s", uri)


discover_tools()
discover_skills()

register_templates()
log.info("starting pai-tools MCP server on :8000")

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
