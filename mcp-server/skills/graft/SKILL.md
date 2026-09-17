---
name: graft
description: "Code intelligence and contextual code search using Graft"
---
# Graft (Code Intelligence)

Graft builds and maintains an AST-accurate index of the workspace. It exposes native MCP tools that you can call directly.
Use Graft before reading files manually. It provides the exact file paths and line numbers, preventing you from reading irrelevant files or blindly grepping.

## ════════════════════════════════════════════════════════════════════════
## SELF-REALIZATION: YOUR CODE BRAIN UNLOCKED
## ════════════════════════════════════════════════════════════════════════

When you use Graft, you're activating the **Code Brain** in your Tri-Brain architecture:

**Your Graft Tools (MCP):**
| Tool | Purpose | Key Use Case |
|---|---|---|
| `graft_find_code` | Semantic search for implementations | "Where is X implemented?" |
| `graft_file_api` | File signatures without bodies | Cheapest way to understand public API |
| `graft_trace_calls` | Callers/callees, blast radius | Impact analysis before changes |
| `graft_find_all` | Regex search grouped by symbol | TODOs, patterns, exact matches |
| `graft_repo_map` | High-level repo orientation | First call on unknown codebase |
| `graft_check_freshness` | Verify index sync | After file changes |

**Your Tri-Brain Role:**
- **Code Brain (You)** ↔ **Research Brain (Open Notebook)** ↔ **Memory Brain (Mnemosyne)**
- **Symbolic anchors**: Your symbols (`@symbol:path:Symbol`) are the universal keys
- Research notes embed your symbols → Mnemosyne triples link them
- **Reverse lookup**: Before writing code, check Mnemosyne for existing research on that symbol
- **Export bridge**: `.open-notebook-exports/` markdown → you index it → searchable as code
- **Drift detection**: You detect file changes in real-time → `graft_check_freshness` forces sync

**Power workflows:**
1. **Turn 1**: `graft_repo_map` → understand codebase structure
2. **Before changes**: `graft_trace_calls(symbol, direction="in")` → blast radius
3. **During research**: `graft_find_code` for implementation details
4. **After research**: Embed `@symbol:` anchors in notes
5. **Planning**: Your indexed `findings.md` / ADRs become searchable context

**Key insight**: You are the PRIMARY retrieval mechanism. Always query Graft before reading raw files.

## When to use
- IF you need to find exact implementation details, THEN you MUST use `graft_find_code`.
- IF you are exploring an unknown repo, THEN you MUST start with `graft_repo_map`.
- IF you are modifying a shared utility, THEN you MUST use `graft_trace_calls` first.

## Available Tools

1. `graft_find_code(question, scope)`
   - **When to use**: To find implementation details, explanations, or specific logic.
   - **Example**: `graft_find_code(question="Where is the user authentication handled?", scope="src/auth")`

2. `graft_file_api(file_path)`
   - **When to use**: To inspect file method/type signatures and documentation without bodies. This is the cheapest way to understand a file's public surface.
   - **Example**: `graft_file_api(file_path="src/main.ts")`

3. `graft_trace_calls(symbol, direction, depth)`
   - **When to use**: To inspect callers (who calls this) or callees (what this calls). Crucial for determining the blast radius of a change.
   - **Example**: `graft_trace_calls(symbol="loginUser", direction="in", depth=1)`

4. `graft_find_all(regex, path)`
   - **When to use**: When you need exact regex matches across the codebase, grouped by symbol and ranked by coupling.
   - **Example**: `graft_find_all(regex="TODO|FIXME", path="src/")`

5. `graft_repo_map(max_dirs)`
   - **When to use**: To get a high-level orientation of the repository, identifying key directories, hubs, and structural overview.
   - **Example**: `graft_repo_map(max_dirs=5)`

6. `graft_check_freshness()`
   - **When to use**: To ensure the index is fully synced with the filesystem. Graft natively auto-detects drift on every query via `probeDrift`, but this tool forces a check.
   - **Example**: `graft_check_freshness()`

## Workflow
- **Explore**: Start with `graft_repo_map` to understand the codebase.
- **Search**: Use `graft_find_code` to locate specific components.
- **Inspect**: Use `graft_file_api` to see what a file exports.
- **Impact Analysis**: Use `graft_trace_calls` before modifying a shared utility or core component to see what else will break.

## Graft Patterns & Development Guidelines

1. **Search Before Reading**: 
   - **Anti-Pattern**: Bulk-reading directories or using generic grep before querying Graft. ALWAYS use Graft first to find precise file paths and lines.
2. **Blast Radius Analysis**:
   - ALWAYS use `graft_trace_calls` before refactoring core functions to understand the impact scope.

## Verification
- Verify the index is fully synced by running `graft_check_freshness` if you suspect the files have changed externally.
