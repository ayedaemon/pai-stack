#!/bin/bash
# handoff_context.sh — Simulate worker handoff context passing.
# This demonstrates the kanban.handoff protocol from config.yaml

set -euo pipefail

# Example: Researcher → Synthesizer handoff
cat <<'EOF'
# ============================================================
# WORKER HANDOFF PROTOCOL (kanban.handoff in hermes/config.yaml)
# ============================================================

## Context Keys (always passed)
# These flow from orchestrator → researcher → synthesizer → adr_author

CONTEXT_KEYS=(
  "notebook_id"           # Open Notebook notebook ID
  "execution_dir"         # Project root for symbol resolution
  "anchor_symbols"        # Initial @symbol: anchors from orchestrator
  "inquiry_question"      # Root question
  "perspective"           # Current perspective (for researcher)
)

## Required Artifacts (must be produced by each worker)
# Researcher produces:
RESEARCHER_ARTIFACTS=(
  "evidence_note_ids"     # Array of note IDs created in Open Notebook
  "symbol_anchors"        # Array of @symbol: discovered during research
  "confidence_score"      # 0.0-1.0 confidence in findings
  "unresolved_questions"  # Array of questions needing further research
)

# Synthesizer produces:
SYNTHESIZER_ARTIFACTS=(
  "synthesis"             # Markdown synthesis of all evidence
  "confidence"            # Overall confidence
  "unresolved_questions"  # Remaining gaps
  "symbol_anchors"        # Consolidated anchors from all researchers
  "counterpoints"         # COUNTERPOINT: entries for dialectical record
)

# ADR Author produces:
ADR_AUTHOR_ARTIFACTS=(
  "adr_path"              # Path to created ADR file
  "adr_number"            # ADR number (e.g., 001)
  "status"                # "proposed" (initial state)
)

## Handoff Example: Researcher → Synthesizer

# Researcher completes task, writes handoff file:
cat > /tmp/handoff-researcher-to-synthesizer.json <<'HANDOFF'
{
  "from_worker": "researcher",
  "to_worker": "synthesizer",
  "task_id": "task-research-1",
  "perspective": "Systems Architecture",
  "artifacts": {
    "evidence_note_ids": ["note:abc123", "note:def456"],
    "symbol_anchors": [
      "@symbol:src/cache/redis_client.py:RedisClient",
      "@symbol:src/cache/__init__.py:get_cache"
    ],
    "confidence_score": 0.85,
    "unresolved_questions": [
      "What's the exact TTL behavior under network partition?",
      "Does Redis Cluster change invalidation semantics?"
    ]
  },
  "summary": "Found Redis client implementation. BackgroundTasks in FastAPI are concurrent for async functions. Cache invalidation uses pub/sub pattern.",
  "context": {
    "notebook_id": "notebook:xyz789",
    "execution_dir": "/opt/data/workspace/github.com/ayedaemon/pai-stack",
    "inquiry_question": "Resilient Distributed Caching Strategy"
  }
}
HANDOFF

# Synthesizer reads handoff, uses context + artifacts
# Then produces its own handoff for ADR Author:
cat > /tmp/handoff-synthesizer-to-adr.json <<'HANDOFF'
{
  "from_worker": "synthesizer",
  "to_worker": "adr_author",
  "task_id": "task-synthesize",
  "artifacts": {
    "synthesis": "## Synthesis: Resilient Distributed Caching\n\n### Systems Architecture\nRedis sidecar with pub/sub invalidation...\n\n### Security & Threats\nCache poisoning mitigated by...\n\n### Developer Ergonomics\nDecorator API @cached() provides...\n\n### Failure Modes\nGraceful degradation via local LRU fallback...\n\n### Counterpoints\n- COUNTERPOINT: Redis adds ops complexity → mitigated by managed service\n- COUNTERPOINT: In-memory simpler → rejected for multi-instance needs",
    "confidence": 0.82,
    "unresolved_questions": [
      "Exact failover latency with Redis Sentinel"
    ],
    "symbol_anchors": [
      "@symbol:src/cache/redis_client.py:RedisClient",
      "@symbol:src/cache/__init__.py:get_cache",
      "@symbol:src/cache/decorators.py:cached",
      "@symbol:src/cache/fallback.py:LocalCache"
    ],
    "counterpoints": [
      "Redis adds ops complexity → mitigated by managed ElastiCache",
      "In-memory cache simpler → rejected due to multi-instance invalidation needs",
      "Cache-as-source-of-truth → avoided, using cache-aside only"
    ]
  },
  "context": {
    "notebook_id": "notebook:xyz789",
    "execution_dir": "/opt/data/workspace/github.com/ayedaemon/pai-stack",
    "inquiry_question": "Resilient Distributed Caching Strategy",
    "decision_topic": "Use Redis for Distributed Caching"
  }
}
HANDOFF

## Orchestration Flow

# Hermes (Orchestrator) creates Kanban board with columns:
# [Decompose] → [Research] → [Synthesize] → [ADR Author] → [Review] → [Done]

# 1. ORCHESTRATOR creates decomposition task
#    → spawns researcher workers in parallel (one per perspective)
#    → each gets: notebook_id, execution_dir, inquiry_question, perspective

# 2. RESEARCHER workers:
#    - Search notebook (notebook_ops search/ask_notebook)
#    - Add sources (add_source_url, add_source_file)
#    - Run probes (run_probe.sh) if empirical validation needed
#    - Write evidence notes (notebook_ops add_note) with @symbol: anchors
#    - Output handoff with evidence_note_ids, symbol_anchors, confidence

# 3. SYNTHESIZER worker:
#    - Reads all evidence notes via note IDs
#    - Identifies agreements/conflicts
#    - Produces synthesis + counterpoints
#    - Output handoff with synthesis, symbol_anchors, counterpoints

# 4. ADR_AUTHOR worker:
#    - Uses new_adr.sh with synthesis + symbols
#    - Computes symbol hashes
#    - Writes ADR to .planning/research/
#    - Output handoff with adr_path, adr_number

# 5. ORCHESTRATOR presents ADR to user for review/acceptance

EOF

echo "Handoff protocol documented. See kanban.handoff in hermes/config.yaml"