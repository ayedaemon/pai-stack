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
> Tool: `notebook_ops` (MCP)
> API: http://open-notebook:5055
> Web UI: http://localhost:8502 (host)
> Only available when running: `make up-all`

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

## Notes Archiving Convention

Only archive findings when the user explicitly requests "save this research" or
when completing a complex multi-day research task. Do NOT auto-archive every
`findings.md` — this creates noise. Quality over quantity.

Note titles should be: `YYYY-MM-DD <slug> — <one-line summary>`

## Related tools / skills

- `skill://codegraph` — primary code retrieval; always query before reading files
- `skill://planning` — findings.md is the source to archive into notes
- `docker_ops(service=open-notebook)` — to check health, tail logs, or restart
