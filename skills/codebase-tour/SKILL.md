---
name: codebase-tour
description: Onboard onto an indexed repo by reading Terrain's 6-chapter human corpus in its own dependency order, deriving the layer table, and registering a diagram. Teaches from unconditional truths first rather than listing files. Load for "onboard me", "how does this repo work", "where do I start reading", or an architecture walkthrough of an indexed project.
---

# Codebase Tour

> An indexed repo already contains its own reading order in `.terrain/human/`. This skill
> reads it the way it was meant to be read, derives the layer table from it, and hands back a
> path you can actually follow — not a file inventory.

## Gate first

Run `skill_view(name="index-health")` before anything else. This tour is built on the index,
so you need to know which corpus you are reading and how old it is. Carry the staleness
verdict into the output — if the corpus is stale, the tour says so at the top.

## Step 1 — Pick the corpus

`.terrain/` holds two different bodies of knowledge. They are not interchangeable.

| Corpus | Produced by | Depth | Use when |
|---|---|---|---|
| `.terrain/human/` — 6 chapters, 13 docs | `init` (**LLM**) | architectural prose: workflows, boundaries, deep-dives | present and fresh enough |
| `.terrain/knowledge/` — 5 docs | `scan`/`refresh` (**free, deterministic**) | grounded facts: components, dataflow, entrypoints, services/ports, architecture | always available once indexed |

Prefer `human/`. Fall back to `knowledge/` when it is missing, and **state which corpus you
used** — a tour built on the thinner corpus is a different, weaker artifact and must not be
presented as the full one.

## Step 2 — Read in terrain's order

The chapter numbering is the dependency order. Do not reorder it.

| # | Chapter | The question it answers |
|---|---|---|
| 1 | `1.Overview.md` | What is this, in one sentence? |
| 2 | `2.Architecture.md` | What are the pieces and how do they connect? |
| 3 | `3.Workflows.md` | What actually happens, end to end? |
| 4 | `4.Deep-Exploration/` | Where do the interesting parts live? |
| 5 | `5.Boundaries-Interfaces.md` | What are the seams, and which way do they face? |
| 6 | `6.Database-Overview.md` | What is persisted, and what shape is it? |

Each chapter answers a question the previous one raised. That is why the order matters —
read 5 before 3 and the interfaces have nothing to attach to.

## Step 3 — Teach it, don't list it

Apply the `teach` skill. Two principles do the work:

1. **Unconditional truths first.** Open with the small set of facts that can be taken at face
   value — what the repo *is*, what it is *for*. Not "this project uses Docker Compose with
   five services", but the one or two claims nothing can contradict. Confirm they read as
   obviously true before building anything on them.
2. **Motivated discovery.** Every step answers "how could I have found this myself?" Why
   this boundary? What problem forced this seam? A fact that feels arbitrary will not stick.

The failure mode to avoid is the file inventory — "here are 13 documents, read them in order".
That is transcription, not teaching. The tour earns its keep by saying what each chapter
*buys* you and what question it leaves open for the next.

## Step 4 — Derive the layer table

`2.Architecture.md` usually names the layers. Confirm against the index rather than trusting
prose alone:

```
pai_terrain_ops(action="search", query="<layer keyword>", project="<slug>")
pai_terrain_ops(action="overview", project="<slug>")   # doc_counts
```

Emit a compact table — layer, what lives there, what it depends on:

| Layer | Lives in | Depends on |
|---|---|---|
| Interface / API | … | … |
| Service | … | … |
| Data | … | … |
| UI | … | … |
| Utility | … | … |

Then register it so it stays live rather than rotting in a transcript:
`skill_view(name="visualize")` writes it to `.project/diagrams/architecture/`, versioned and
linked back to the code. A tour that produces an unregistered diagram gets redrawn by hand
next time; a registered one gets a sync check.

## Output

```
<project> — tour
  corpus: .terrain/human/ (13 docs)          # or .terrain/knowledge/ (5 docs) + why
  health: overall 79/100, human_docs STALE  # omit only if genuinely fresh

  Ground truth
    - <unconditional truth 1>
    - <unconditional truth 2>

  Reading path
    1. 1.Overview        → <what it settles>
    2. 2.Architecture    → <what it settles>
    3. 3.Workflows       → <what it settles>
    ...                  (6 steps)

  Layers
    <table>

  Start here: <the single first thing to read, and why it's first>
```

## Invariants

1. **Gate on `index-health`.** Never tour an index of unknown age without reporting it.
2. **Name your corpus.** `human/` and `knowledge/` are different products.
3. **One unconditional truth before any structure.** If the foundation does not read as
   obviously true, stop and fix it — do not build the tour on sand.
4. **Register the diagram.** An unversioned diagram is a throwaway; use `visualize`.
5. **Terrain is optional.** No service → say so, and tour from `README.md` + `AGENTS.md` +
   directory structure with `grep`. Degraded, not broken.