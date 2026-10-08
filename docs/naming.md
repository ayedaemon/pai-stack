# Naming Convention

Canonical, project-wide. Applies to Hermes, DSH, and any future agent. This document
supersedes the narrower rule in [dsh.md](dsh.md) and exists because three naming defects
were live at once (see [audit.md](audit.md) §reported):

- `skills/opendesign-tool/SKILL.md` called `od_design_ops` 6× — a tool no plugin registers.
- `docs/dsh.md` simultaneously said `mnemon_*` and `mnemosyne_*` for the same capability.
- Terrain reaches Hermes as `pai_terrain_ops` but would reach DSH as `terrain_index` —
  two names for one capability, differing only by transport.

## The four namespaces

| Layer | Form | Carries an agent name? | Examples |
|---|---|---|---|
| **Tool** — what the model calls | `pai_<noun>_ops` | **never** | `pai_terrain_ops`, `pai_notebook_ops` |
| **Plugin package** — how it is installed | `<agent>-pai-<noun>` | **yes** | Hermes `pai_tools`, DSH `dsh-pai-tools` |
| **Skill** — procedural markdown | kebab-case | **never** | `opendesign-integration`, `stack-discovery` |
| **Service** — a container | kebab-case | **never** | `llm-gateway`, `open-design`, `terrain` |

## The five binding rules

**1. Tool names are agent-agnostic — byte-identical everywhere.**
The tool name is a contract with the model *and* with every skill that references it. The
same capability carries the same string on every agent. A skill that says
`pai_terrain_ops` must keep working on an agent that has never heard of Hermes.
*Consequence:* porting a capability is a transport problem, never a rename.

**2. Package names carry the agent prefix; tool names do not.**
This is the distinction that was previously conflated. `dsh-pai-notebook` is an npm/plugin
identity that only DSH loads. `pai_notebook_ops` is what the model types. Dropping the
prefix on a tool silently breaks every skill that names it; dropping it on a package breaks
nothing.

**3. `pai_` means "registered by pai-stack", not "belongs to Hermes".**
It is a capability namespace, not an ownership claim. The moment a second agent exists,
`pai_terrain_ops` on DSH is *correct*, not a violation.

**4. Third-party and upstream tool names are never renamed.**
`mnemosyne_*`, `skill_view`, `skills_list` keep their upstream spelling even when the backing
implementation changes (`dsh-mnemon` implements `mnemosyne_*`, not `mnemon_*`). Renaming them
would fork a vendored contract on every upstream bump.

**5. No tool name may be invented in a skill.**
A `SKILL.md` may only reference a name present in some `plugin.yaml`'s `provides_tools`, or a
documented upstream tool. A skill that names a tool which does not exist sends the model
chasing nothing. This is checkable — see Phase 8 of the plan.

## Transports that force fan-out

Hermes native plugins and DSH Cordis plugins both support **one tool with an `action`
discriminator**. MCP does not — the protocol is one tool per action.

Where fan-out is unavoidable, the rule does not relax; the prefix stays:

| Capability | Single-tool agent | Fan-out agent (MCP) |
|---|---|---|
| Terrain | `pai_terrain_ops(action="search", …)` | `pai_terrain_search`, `pai_terrain_index`, … |
| Notebooks | `pai_notebook_ops(action="search", …)` | `pai_notebook_search`, … |

`terrain_index` and `terrain_search` — the names the shim emits today — leak the transport
and drop the namespace. Renaming them to `pai_terrain_*` costs nothing today (no MCP client is
registered) and is the reason to do it before one is.

## Checklist for a new capability

1. Name the tool `pai_<noun>_ops` and commit to using it on **every** agent.
2. Write the skill against that exact string. No aliases, no abbreviations.
3. On a new agent: package it as `<agent>-pai-<noun>`, register the **unprefixed** tool name.
4. If you add an alias for compatibility, the canonical name is the one in `plugin.yaml`;
   aliases are a migration artifact and must be removed.
5. Grep the skills tree before committing: the new name should appear in exactly one
   `plugin.yaml` and any number of `SKILL.md` files — and no other spelling anywhere.

## Current registry

| Tool | Plugin package | Defined in |
|---|---|---|
| `pai_notebook_ops` | `pai_tools` | [pai_tools/plugin.yaml](../hermes/plugins/pai_tools/plugin.yaml) |
| `pai_adr_ops` | `pai_tools` | ↑ |
| `pai_ops_design_ops` | `pai_tools` | ↑ |
| `pai_terrain_ops` | `pai_terrain_ops` | [pai_terrain_ops/plugin.yaml](../hermes/plugins/pai_terrain_ops/plugin.yaml) |

Docker is deliberately NOT in this registry: native `docker` + `docker compose` binaries over the mounted socket (see `docker` skill), identical on Hermes and DSH — no tool port needed.

Upstream, not ours to rename: `skill_view`, `skills_list`, `mnemosyne_*`.

> `pai_terrain_ops/plugin.yaml` also declares `requires: [terrain_service]`. That is a
> *dependency* declaration, not a second tool — it is how the tool self-hides when the
> optional profile is not running.
