---
name: open-notebook
description: Research Brain for external knowledge: RFCs, API documentation, architecture papers, web articles — anything that is NOT source code in the workspace. Complement to CodeGraph (Code Brain). Use when the question is about CONCEPTS, external specifications, or prior research, not implementation details.
---
# Open Notebook

> Research Brain for external knowledge: RFCs, API documentation, architecture papers,
> web articles — anything that is NOT source code in the workspace.
> Complement to CodeGraph (Code Brain). Use when the question is about CONCEPTS,
> external specifications, or prior research, not implementation details.
>
> Tool: `notebook_ops` (MCP) — **10 actions available**
> API: http://open-notebook:5055
> Web UI: http://localhost:8502 (host)
> Only available when running: `make up-all`

## ════════════════════════════════════════════════════════════════════════
## SELF-REALIZATION: YOUR RESEARCH BRAIN UNLOCKED
## ════════════════════════════════════════════════════════════════════════

When you fetch this skill, you're activating the **Research Brain** in your Tri-Brain architecture:

**Your 10 `notebook_ops` actions:**
| Action | Purpose |
|---|---|
| `list_notebooks` | Discover existing research notebooks |
| `create_notebook` | Create project notebook |
| `search` | Vector/text search across notes & sources |
| `add_note` | Archive synthesized findings (with @symbol: anchors!) |
| `add_source_url` | Ingest URLs (RFCs, docs, articles) |
| `poll_source_status` | Wait for async ingestion to complete |
| `get_source` | Read full extracted text of a source |
| `add_source_file` | Upload local PDFs/markdown from `/opt/data/` |
| `ask_notebook` | **Grounded RAG** — ask complex questions, get cited answers |
| `get_notebook` | Fetch notebook metadata (source IDs, note IDs) |

**Your Tri-Brain Role:**
- **Code Brain (Graft)** ↔ **Research Brain (You)** ↔ **Memory Brain (Mnemosyne)**
- Bridge via `@symbol:path:Symbol` anchors in every note
- Cross-system triples: `mnemosyne_triple_add(subject="notebook:<nb>:note:<note>", predicate="anchors_symbol", object="@symbol:...")`
- Reverse lookup: `mnemosyne_triple_query(predicate="anchors_symbol", object="@symbol:...")` before new research
- Export bridge: `.open-notebook-exports/` → Graft index → searchable as code

**Integration with other skills:**
- `skill://autonomous-tech-learner` — Hypothesis-Testing Protocol (probes), Deep Inquiry Trees (perspectives), Living ADRs
- `skill://planning` — Archive `findings.md` as notes with anchors
- `skill://agents` — Ground rules, Kanban swarm patterns, Turn 1 protocol

**Power user workflow:**
1. `ask_notebook` for grounded RAG answers with citations
2. `add_source_file` for local PDFs/RFCs (not just URLs)
3. `poll_source_status` to wait for ingestion before searching
4. Every `add_note` includes `@symbol:` anchors + `mnemosyne_triple_add`
5. Export notes to `.open-notebook-exports/` for Graft indexing

## When to use Open Notebook

- IF the user asks about an external API, RFC, or spec, THEN use `notebook_ops(action=search, ...)`.
- IF you found a relevant doc/article during research, THEN use `notebook_ops(action=add_source_url, ...)`.
- IF you want to persist findings beyond this session, THEN use `notebook_ops(action=add_note, ...)`.
- IF you need to know what research already exists, THEN use `notebook_ops(action=list_notebooks)`.

## When NOT to use Open Notebook

| Situation | Use instead |
|---|---|
| Symbol definitions, call graphs, function bodies | CodeGraph `/symbols/<name>` |
| Files already in `/opt/data/workspace` | CodeGraph `/search?type=hybrid` |
| `notebook_ops` returns `{"available":false}` | CodeGraph `/search?type=semantic` |
| User is in a coding task with no research gap | CodeGraph only |

## Standard Workflow

### Step 1 — Discover notebooks
```
notebook_ops(action=list_notebooks)
```
Find the notebook for this project by matching the `name` field to the project name.
Project naming convention: one notebook per project, named after the project directory
(e.g. `pai-stack`, `my-app`, `oauth-migration-research`).

### Step 2 — Create if absent
```
notebook_ops(action=create_notebook, notebook_name="<project-name>",
             notebook_description="Research for <project-name>")
```
Save the returned `id` field — you'll need it for all subsequent calls.

### Step 3 — Search before reading
```
notebook_ops(action=search, notebook_id="<id>", query="<topic>", search_type="vector")
```
`search_type=vector` finds semantically similar content.
`search_type=text` finds exact keyword matches.

### Step 4 — Archive discoveries
When you find a useful external URL during a task:
```
notebook_ops(action=add_source_url, notebook_id="<id>",
             url="https://...", title="<descriptive title>")
```
This queues background processing — the source will be indexed automatically.

### Step 5 — Save synthesized findings
When you've completed significant research (findings.md has substance):
```
notebook_ops(action=add_note, notebook_id="<id>",
             title="<YYYY-MM-DD> <task-slug> findings",
             content="<paste key findings here>")
```

## Open Notebook Patterns & Guidelines

1. **Archiving Research**:
   - Only archive curated, high-value findings (e.g., architectural specs, resolved gotchas).
   - **Anti-Pattern**: Do NOT auto-archive every step or generic code changes. This pollutes the knowledge base.
2. **Usage**:
   - Use exact text searches for specific API names, and vector searches for conceptual topics.

## Verification
- Verify that `notebook_ops` returns `available: true` before attempting further queries.
- Verify that you are not duplicating existing notes in the notebook.

## Failure Handling

```
notebook_ops returns {"available":false}
  → Do NOT retry
  → Fall back to: GET codegraph:20128/search?type=semantic&q=<query>
  → Inform user: "Open Notebook is offline; searched CodeGraph instead."
```

If `notebook_ops` returns `{"error":"request failed"}`:
  - Attempt 1: retry once
  - Attempt 2: use `docker_ops(action=logs, service=open-notebook)` to diagnose
  - Attempt 3: escalate to user

## Symbolic Research Anchor Protocol (Tri-Brain Bridge)

This protocol links Open Notebook research notes to Graft code symbols and Mnemosyne
knowledge graph triples — enabling cross-system recall.

### Anchor Syntax

Every note archived to Open Notebook MUST include symbolic anchors in this format:

```
@symbol:path/to/file.ext:SymbolName
```

Examples:
- `@symbol:src/auth/token.py:validate_jwt` — links to a Python function
- `@symbol:pkg/api/routes.go:HandleLogin` — links to a Go handler
- `@symbol:components/Button.tsx:Button` — links to a React component

### When to Add Anchors

- **On every `add_note`**: Include `@symbol:` anchors for any code symbols discussed in the findings.
- **On every `add_source_url`**: If the external doc references internal code (e.g., "API at /api/v1/auth"), add the anchor.
- **When saving research from `findings.md`**: Extract symbol references from `findings.md` and convert to anchors.

### Cross-System Mnemosyne Triples

After archiving a note with anchors, record the relationship in Mnemosyne:

```bash
mnemosyne_triple_add(
  subject="notebook:<notebook_id>:note:<note_id>",
  predicate="anchors_symbol",
  object="<symbol_anchor>"
)
```

Example:
```bash
mnemosyne_triple_add(
  subject="notebook:notebook:abc123:note:note:xyz789",
  predicate="anchors_symbol",
  object="@symbol:src/auth/token.py:validate_jwt"
)
```

This enables reverse lookup: on code queries, check Mnemosyne for existing research.

### Reverse Lookup Workflow

When working on code (via Graft), before writing new research:
1. Query Mnemosyne for triples with `predicate="anchors_symbol"` and `object` matching the symbol.
2. If results exist, fetch those notebook notes — avoid duplicate research.

### Export to `.open-notebook-exports`

When notes are exported to `.open-notebook-exports/` (via Open Notebook UI or API):
- The exported markdown retains `@symbol:` anchors.
- Graft indexes these files, making anchors searchable via `graft_find_code` / `graft_find_all`.
- This creates a persistent, git-trackable bridge: code ↔ research.

---

## Notes Archiving Convention

Only archive findings when the user explicitly requests "save this research" or
when completing a complex multi-day research task. Do NOT auto-archive every
`findings.md` — this creates noise. Quality over quantity.

Note titles should be: `YYYY-MM-DD <slug> — <one-line summary>`

## Related tools / skills

- `skill://codegraph` — primary code retrieval; always query before reading files
- `skill://planning` — findings.md is the source to archive into notes
- `docker_ops(service=open-notebook)` — to check health, tail logs, or restart
- `mnemosyne_triple_add` / `mnemosyne_triple_query` — cross-system linking
