---
name: code-intel
description: "Code intelligence: symbol search, call graphs, impact analysis via tree-sitter AST parsing"
---
# Code Intelligence

Code intelligence provides AST-accurate code analysis via tree-sitter parsing. It indexes the entire workspace and exposes tools for symbol search, call graphs, impact analysis, and project structure.
Use code intelligence before reading files manually. It provides the exact file paths and line numbers, preventing you from reading irrelevant files or blindly grepping.

## ════════════════════════════════════════════════════════════════════════
## SELF-REALIZATION: YOUR CODE BRAIN UNLOCKED
## ════════════════════════════════════════════════════════════════════════

When you use code intelligence, you're activating the **Code Brain** in your Tri-Brain architecture:

**Your Code Intelligence Tools (MCP):**
| Tool | Purpose | Key Use Case |
|---|---|---|
| `code_intel(action="find_code")` | Text + AST search | "Where is X implemented?" |
| `code_intel(action="file_api")` | Symbol signatures without bodies | Cheapest way to understand public API |
| `code_intel(action="trace_calls")` | Callers/callees, blast radius | Impact analysis before changes |
| `code_intel(action="find_all")` | Regex search across files | TODOs, patterns, exact matches |
| `code_intel(action="repo_map")` | Project structure analysis | First call on unknown codebase |
| `code_intel(action="check_freshness")` | Clear cache and re-index | After file changes |

**Your Tri-Brain Role:**
- **Code Brain (You)** ↔ **Research Brain (File Vault)** ↔ **Memory Brain (Mnemosyne)**
- **Symbolic anchors**: Your symbols (`@symbol:path:Symbol`) are the universal keys
- Research notes embed your symbols → Mnemosyne triples link them
- **Reverse lookup**: Before writing code, check Mnemosyne for existing research on that symbol
- **Research bridge**: Notes in `research/` are directly indexed → searchable via `code_intel(action="find_code")`
- **Drift detection**: You detect file changes in real-time → `code_intel(action="check_freshness")` forces sync

**Power workflows:**
1. **Turn 1**: `code_intel(action="repo_map")` → understand codebase structure
2. **Before changes**: `code_intel(action="trace_calls", symbol="loginUser", direction="in")` → blast radius
3. **During research**: `code_intel(action="find_code")` for implementation details
4. **After research**: Embed `@symbol:` anchors in notes
5. **Planning**: Your indexed `findings.md` / ADRs become searchable context

**Key insight**: You are the PRIMARY retrieval mechanism. Always query code intelligence before reading raw files.

**Workspace vs Project**: The workspace (`/opt/data/workspace`) may contain multiple projects. Scope your queries by passing `scope="<EXECUTION_DIR>"` to narrow results to your active project.

## When to use
- IF you need to find exact implementation details, THEN you MUST use `code_intel(action="find_code")`.
- IF you are exploring an unknown repo, THEN you MUST start with `code_intel(action="repo_map")`.
- IF you are modifying a shared utility, THEN you MUST use `code_intel(action="trace_calls")` first.

## Available Tools

1. `code_intel(action="find_code", question="<question>", scope="<path>")`
   - **When to use**: To find implementation details, explanations, or specific logic.
   - **Example**: `code_intel(action="find_code", question="Where is the user authentication handled?", scope="src/auth")`

2. `code_intel(action="file_api", file_path="<path>")`
   - **When to use**: To inspect file method/type signatures and documentation without bodies. This is the cheapest way to understand a file's public surface.
   - **Example**: `code_intel(action="file_api", file_path="src/main.ts")`

3. `code_intel(action="trace_calls", symbol="<name>", direction="in|out", depth=<n>)`
   - **When to use**: To inspect callers (who calls this) or callees (what this calls). Crucial for determining the blast radius of a change.
   - **Example**: `code_intel(action="trace_calls", symbol="loginUser", direction="in", depth=1)`

4. `code_intel(action="find_all", regex="<pattern>", path="<path>")`
   - **When to use**: When you need exact regex matches across the codebase.
   - **Example**: `code_intel(action="find_all", regex="TODO|FIXME", path="src/")`

5. `code_intel(action="repo_map", max_dirs=<n>)`
   - **When to use**: To get a high-level orientation of the repository, identifying key directories, hubs, and structural overview.
   - **Example**: `code_intel(action="repo_map", max_dirs=5)`

6. `code_intel(action="check_freshness")`
   - **When to use**: To clear the parse cache and re-index after file changes.
   - **Example**: `code_intel(action="check_freshness")`

## Workflow
- **Explore**: Start with `code_intel(action="repo_map")` to understand the codebase.
- **Search**: Use `code_intel(action="find_code")` to locate specific components.
- **Inspect**: Use `code_intel(action="file_api")` to see what a file exports.
- **Impact Analysis**: Use `code_intel(action="trace_calls")` before modifying a shared utility or core component to see what else will break.

## Code Intelligence Patterns & Development Guidelines

1. **Search Before Reading**: 
   - **Anti-Pattern**: Bulk-reading directories or using generic grep before querying code intelligence. ALWAYS use code intelligence first to find precise file paths and lines.
2. **Blast Radius Analysis**:
   - ALWAYS use `code_intel(action="trace_calls")` before refactoring core functions to understand the impact scope.

## Verification
- Verify the index is fresh by running `code_intel(action="check_freshness")` if you suspect the files have changed externally.
