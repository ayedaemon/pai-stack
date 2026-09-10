# ADR-006: Local Embeddings + File-Based RAG over Vector DB Service

## Status
Accepted

## Context
Hermes needs grounded recall over all user notes and projects. Options were hosted embeddings (OpenAI), or a dedicated vector DB (Qdrant/Weaviate).

## Decision
`knowledgebase: enabled: true directories: [/stack_root] auto_retrieve: true max_context_chunks: 8 relevance_threshold: 0.5 embedding_model: local reindex_on_change: true` `hermes/config.yaml:141`, using `fastembed all-MiniLM-L6-v2` (~80 MB) with `context_files: [/stack_root/AGENTS.md]` always injected `hermes/config.yaml:136`.

## Alternatives Considered
- **OpenAI embeddings** — higher quality, but network + key + cost per reindex.
- **Qdrant/Weaviate sidecar** — stronger ANN, but extra container, RAM (256–512 MB) and volume on Pi.

## Consequences
- Positive: No external API, privacy, instant reindex on file change, whole `Personal` searchable (finds codebases before KB scaffold).
- Negative: Lower recall than large hosted models; threshold `0.5` and `8` chunks tuned as sweet spot — raising adds noise.

## Trade-offs
Simplicity, privacy, and Pi-fit prioritized over peak retrieval quality. Can swap `embedding_model` later without changing RAG contracts.
