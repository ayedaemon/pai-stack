# Architecture

Two core services. One optional profile. One workspace mount.

```
Host $WORKSPACE_DIR
  ├── <project-a>/, <project-b>/, ...
  ├── research/            ← Research Brain vault (Markdown)
  └── .planning/           ← per-project planning artifacts
        │
        │  /opt/data/workspace (rw) ──→ hermes
        │
hermes ──→ llm-gateway:4000   (ALL model inference)
hermes ──→ in-process: code intel (tree-sitter), pai_* tools, skills, Mnemosyne (SQLite + ONNX)
open-design (profile: design) ──→ shares $WORKSPACE_DIR at /workspace
```

## Mounts

| Host | Container | Service | Access |
|---|---|---|---|
| `$WORKSPACE_DIR` | `/opt/data/workspace` | hermes | read-write (code edits, intel index, research vault) |
| `$WORKSPACE_DIR` | `/workspace` | open-design | read-write (import via UI: `/workspace/<project>`) |
| `hermes-data` volume | `/opt/hermes/data` | hermes | app state, Mnemosyne DB, logs |
| `open_design_data` volume | `/app/.od` | open-design | daemon state (SQLite, config, artifacts index) |
| `./skills` | `/opt/pai/skills` | hermes | read-only procedural skills |

Hermes code intel runs in-process over the whole workspace; file changes are picked up in real time. No sidecar DB or embedding containers (~2.3 GB RAM saved).

## Tri-Brain (summary)

| Brain | Backing | Role |
|---|---|---|
| Code | `pai_code_intel` | AST symbols, call graphs, file APIs, drift detection |
| Research | `pai_notebook_ops` on `research/` | RFCs, papers, API docs, notes |
| Memory | Mnemosyne (SQLite + fastembed) | Decisions, fixes, preferences, triples |

Cross-linking: `@symbol:path/to/file.ext:SymbolName` anchors in notes + Mnemosyne triples (note → symbol → decision). Full research loop: [research.md](research.md). Hermes operation: [hermes.md](hermes.md).

## LLM posture: gateway-only

- Hermes declares one provider (`gateway` → `llm-gateway:4000`). Model choice, fallbacks, credentials live in `llm-gateway/config.yaml` + `scripts/sync-models.py`.
- Never add direct provider keys or Hermes-level fallbacks. Models.dev reads are metadata-only and fine.
- Exceptions: `opencode-delegate` calls Zen free models directly (keyless, see [delegation.md](delegation.md)); Langfuse receives traces (the audit trail).
- Secrets caveat: keys are absent from the hermes container env, but `.env` sits inside the mounted workspace — file-capable tools can read it. `*.env` reads are hard-denied for delegates.

## Philosophy

- Zero contamination: research lives in `research/` or `.planning/`, never in git code dirs.
- Single gateway: every model call routes through `llm-gateway:4000`.
- Empirical over theoretical: ambiguous docs → micro-probe before trusting web claims.
- Self-realizing agent: Hermes discovers tools, skills, and boundaries on Turn 1.
