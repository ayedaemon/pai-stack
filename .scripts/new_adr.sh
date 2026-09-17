#!/bin/bash
# new_adr.sh — Create a new Living ADR with symbol hashes.
# Usage: new_adr.sh <adr-number> <title> "context" "decision" "symbol1 symbol2 ..."

set -euo pipefail

ADR_NUM="${1:-}"
TITLE="${2:-}"
CONTEXT="${3:-}"
DECISION="${4:-}"
SYMBOLS="${5:-}"

if [[ -z "$ADR_NUM" || -z "$TITLE" ]]; then
  echo "Usage: $0 <adr-number> <title> \"context\" \"decision\" \"symbol1 symbol2 ...\""
  echo "Example: $0 001 \"Use Redis for Caching\" \"Need distributed cache\" \"Use Redis\" \"@symbol:src/cache/redis.py:RedisClient @symbol:src/cache/__init__.py:get_cache\""
  exit 1
fi

# Determine planning directory (most recent)
PLANNING_DIR=$(find /opt/data/workspace -maxdepth 4 -name ".planning" -type d 2>/dev/null | head -1)
if [[ -z "$PLANNING_DIR" ]]; then
  echo "Error: No .planning directory found in workspace"
  exit 1
fi

RESEARCH_DIR="$PLANNING_DIR/research"
mkdir -p "$RESEARCH_DIR"

ADR_FILE="$RESEARCH_DIR/ADR-${ADR_NUM}-$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g').md"
DATE=$(date +%Y-%m-%d)

# Compute symbol hashes
SYMBOL_HASHES=""
if [[ -n "$SYMBOLS" ]]; then
  for SYMBOL in $SYMBOLS; do
    # Extract path and symbol name from @symbol:path/to/file.ext:SymbolName
    if [[ "$SYMBOL" =~ ^@symbol:(.+):(.+)$ ]]; then
      FILE_PATH="${BASH_REMATCH[1]}"
      SYMBOL_NAME="${BASH_REMATCH[2]}"
      FULL_PATH="/opt/data/workspace/$FILE_PATH"
      
      if [[ -f "$FULL_PATH" ]]; then
        # Use graft_file_api via MCP or fallback to grep
        # For now, compute hash of the symbol's file content (simplified)
        HASH=$(sha256sum "$FULL_PATH" | cut -d' ' -f1 | cut -c1-16)
        SYMBOL_HASHES="${SYMBOL_HASHES}- ${SYMBOL}#sha256:${HASH}\n"
      else
        SYMBOL_HASHES="${SYMBOL_HASHES}- ${SYMBOL}#sha256:FILE_NOT_FOUND\n"
      fi
    fi
  done
fi

# Build ADR content
cat > "$ADR_FILE" <<EOF
---
adr: ${ADR_NUM}
title: ${TITLE}
status: proposed
date: ${DATE}
deciders: [Hermes, <user>]
symbols:
${SYMBOL_HASHES}supersedes: null
superseded_by: null
---

## Context
${CONTEXT}

## Decision
${DECISION}

## Consequences

### Positive
- 

### Negative
- 

### Neutral
- 

## Dialectical Record
### Counterpoints Considered
- 

### Anti-Patterns Avoided
- 

## Symbol Hashes (for drift detection)
${SYMBOL_HASHES}

## Validation Probes (Phase 4)
- 

## Review Triggers
- Any symbol hash mismatch detected by Graft
- New counterpoint discovered in dialectical search
- Performance regression in validation probes
- Major version upgrade of dependent library
EOF

echo "Created ADR: $ADR_FILE"
echo "Status: proposed — review and confirm to accept"