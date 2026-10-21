---
name: research
description: Persistent wiki for the attached session's workspace, at <workspace>/.project/research/. Create, ingest, query, and lint interlinked Markdown knowledge. Use when user mentions wiki, knowledge base, notes, or starts/queries/lints research.
---

# Research — Per-Project Wiki

> Persistent, compounding knowledge base as interlinked Markdown at `.project/research/` in each project.
> Based on Karpathy's LLM Wiki pattern (via `llm-wiki` on hermesskins.io), adapted for pai-stack.

## Wiki Location (the attached session's workspace)

The vault is `.project/research/` **relative to the workspace attached to this session**.
The runtime resolves that base — never hardcode it and never derive it by scanning.

```bash
# resolved for you by the tool — no path guessing
pai_notebook_ops(action="list_pages")
```

- In-container: whatever the session is attached to, e.g. `/opt/data/workspace/<project>/.project/research`.
- Host: `<WORKSPACE_DIR>/<project>/.project/research`.
- A vault only ever exists inside an attached workspace. There is no global
  `research/` at the workspace root; if a session is attached to the root, the vault is
  `<root>/.project/research` and belongs to that root session only.
- Legacy notebook vaults (`<notebook>/{notes/,sources/,notebook.json}`) are **not** migrated.
  New knowledge goes in the wiki sections below.

## Architecture: per-workspace wiki

```
<attached workspace>/.project/research/   ← $WIKI
├── SCHEMA.md                        ← conventions, tag taxonomy, domain
├── index.md                         ← sectioned catalog, one-line summaries
├── log.md                           ← chronological action log (append-only, rotate at 500)
├── raw/articles|papers|.../         ← Layer 1: immutable sources (never edit)
├── entities/                        ← Layer 2: people, orgs, products, models
├── concepts/                        ← Layer 2: topics, techniques
├── comparisons/                     ← Layer 2: side-by-side analyses
├── queries/                         ← Layer 2: filed answers worth keeping
└── _archive/                        ← superseded pages (removed from index)
```

Layer 1 raw = immutable. Layer 2 wiki = agent-owned. Layer 3 SCHEMA = rules.

## Orient First (every session touching research)

1. Read `SCHEMA.md` (domain, conventions, tags).
2. Read `index.md` (what exists).
3. Read last 20 lines of `log.md` (recent activity).
4. For 100+ pages, `pai_notebook_ops(action="search")` the topic before creating anything.

Skipping this causes duplicates and missed cross-refs.

## Init New Wiki (vault empty)

1. `pai_notebook_ops(action="init_wiki")` — creates `SCHEMA.md`, `index.md`, `log.md` and logs the init.
2. Edit `SCHEMA.md` to set the domain and the tag taxonomy (specific, e.g. "Aurora Postgres tuning").
   Everything else it writes is a starting point; the schema is yours to specialize.
3. Suggest first sources.

### SCHEMA.md (adapt to domain)

- Filenames: lowercase, hyphens (`transformer-architecture.md`).
- Every page: YAML frontmatter (`title, created, updated, type: entity|concept|comparison|query|summary, tags, sources`), ≥2 `[[wikilinks]]`, bump `updated` on edit, add to `index.md`, append to `log.md`.
- Tags only from taxonomy (add to SCHEMA first).
- Thresholds: create when entity appears in 2+ sources or is central to one; split at ~200 lines; archive (move to `_archive/`, delink) when superseded.
- Contradictions: keep both claims with dates, set `contested: true` + `contradictions: [slug]`, surface in lint.
- Confidence: `high|medium|low` for opinion-heavy/fast-moving/single-source claims.
- Raw files get `source_url, ingested, sha256` (body hash; skip re-ingest when unchanged, flag drift when changed).

## Ingest (URL, file, paste)

1. Capture raw → `pai_notebook_ops(action="ingest_url"|"ingest_file")`. The tool writes
   `raw/<category>/<slug>.md` with `source_url`, `ingested`, `sha256` frontmatter. Re-ingesting
   an unchanged body returns `status: "unchanged"`; a changed body returns `"ingested"` and
   refreshes the hash. Never modify `raw/` by hand afterwards.
2. Check existing: `index.md` + `pai_notebook_ops(action="search")` for mentioned entities.
3. Write/update Layer-2 pages with `pai_notebook_ops(action="write_page", section=...)`.
   Cross-ref ≥2 `[[wikilinks]]` (both directions). Tags from taxonomy. Cite `raw/...` refs in
   `sources` on 3+-source syntheses. The tool returns `broken_links` and `warnings` — resolve
   a forward reference by writing the target page, not by dropping the link.
4. `index.md` and `log.md` are maintained by the tool. Do not hand-edit them; a write that
   skips the tool is a write the index never learns about.
5. Report files changed. If 10+ pages touched, confirm scope with user first.
6. Memory glue (mandatory): embed `@symbol:path/to/file.ext:Symbol` anchors for code claims —
   `write_page` extracts them into frontmatter. `mnemosyne_triple_add(subject="research:<page_ref>", predicate="anchors_symbol", object="@symbol:...")`; reverse-lookup via `mnemosyne_triple_query` before creating.

Tool mapping: `ingest_url`/`ingest_file` → raw capture; `write_page` → Layer-2 page body;
`search` → duplicate check; `ask` → grounded draft; `get_page`/`get_source` → read back.

## Query

1. `index.md` → relevant pages (+ `pai_notebook_ops(action="search")` for 100+ pages).
2. Read top-3 pages max via `pai_notebook_ops(action="get_page")` (never bulk-read).
3. Synthesize with citations (`[[page]]`, `@symbol:` for code).
4. File back substantial novel synthesis to `queries/` or `comparisons/` via `write_page`
   (skip trivial lookups). The tool logs the write.
5. `pai_notebook_ops(action="ask")` when the answer should come from the gateway rather than
   your own reading — it grounds on search hits only.

## Lint (health-check)

Read the vault and report grouped by severity (broken links > orphans > drift > contested >
stale > style). `write_page` already reports `broken_links` on every write, so this pass is
about what accumulates between writes: orphans (0 inbound links), broken `[[links]]`, index
completeness (fs vs index), frontmatter validity + taxonomy, stale (`updated` >90d behind
newest source), `contested:true` / `contradictions:` / `confidence:low`, raw `sha256` drift
(re-ingest each `raw/` source and look for `status: "ingested"`), pages >200 lines, tag
sprawl, log rotation (>500 entries → `log-YYYY.md`, which the tool does automatically).

## Agent Integration

- Vault is plain Markdown on the mounted workspace — new pages are immediately searchable with `grep`.
- Both hermes and dsh write the same layout at the same path, resolved against their own
  attached session workspace. Sharing a workspace shares a vault.
- Planning files (`task_plan/findings/progress.md`) stay in `<workspace>/.project/planning/`;
  research conclusions graduate to wiki + Living ADRs (`.project/planning/research/ADR-XXX.md`
  via `pai_adr_ops`).
- Probes: `/opt/data/probes/<slug>/` scripts; results ingested as evidence pages with `@symbol:` anchors.
- Turn 1: load this skill only when research is the task or `<workspace>/.project/research/SCHEMA.md`
  exists; orient reads are SCHEMA + index + log-tail-20 only.

## Pitfalls

- Never edit `raw/`. Never hand-edit `index.md` or `log.md` — the tool owns both. No pages for
  passing mentions. No isolated pages. Frontmatter required. Tags from taxonomy only. Split
  >200 lines. Contradictions explicit, never silent overwrite.
- Never write research outside the attached workspace. If the task needs another project's
  research, ask for that project to be attached first.