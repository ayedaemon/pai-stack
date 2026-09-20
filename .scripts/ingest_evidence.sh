#!/bin/bash
# ingest_evidence.sh — Format probe results as Open Notebook evidence note and ingest.
# Usage: ingest_evidence.sh <hypothesis-slug> <notebook_id> [title_suffix]

set -euo pipefail

SLUG="${1:-}"
NOTEBOOK_ID="${2:-}"
TITLE_SUFFIX="${3:-}"

if [[ -z "$SLUG" || -z "$NOTEBOOK_ID" ]]; then
  echo "Usage: $0 <hypothesis-slug> <notebook_id> [title_suffix]"
  echo "Example: $0 fastapi-background-tasks-concurrent notebook:abc123 \"refuted\""
  exit 1
fi

PROBE_DIR="/opt/data/probes/$SLUG"
RESULTS_FILE="$PROBE_DIR/results.json"
HYPOTHESIS_FILE="$PROBE_DIR/hypothesis.md"

if [[ ! -f "$RESULTS_FILE" ]]; then
  echo "Error: results.json not found. Run run_probe.sh first."
  exit 1
fi

if [[ ! -f "$HYPOTHESIS_FILE" ]]; then
  echo "Error: hypothesis.md not found."
  exit 1
fi

# Parse results
RESULT=$(jq -r '.result // "inconclusive"' "$RESULTS_FILE")
HYPOTHESIS_TEXT=$(grep -A2 '^**Statement**:' "$HYPOTHESIS_FILE" | tail -1 | sed 's/^ *//')
METRICS=$(jq -c '.metrics // {}' "$RESULTS_FILE")
STDOUT=$(jq -r '.stdout // ""' "$RESULTS_FILE")
STDERR=$(jq -r '.stderr // ""' "$RESULTS_FILE")

# Build evidence note content
EVIDENCE_CONTENT=$(cat <<EOF
## Hypothesis
$HYPOTHESIS_TEXT

## Method
Executed probe at \`$PROBE_DIR/\` with \`run_probe.sh $SLUG\`.

### Probe Script (\`probe.py\`)
\`\`\`python
$(cat "$PROBE_DIR/probe.py")
\`\`\`

## Results
\`\`\`json
$(cat "$RESULTS_FILE")
\`\`\`

## Conclusion
**Status**: $RESULT

$(if [[ "$RESULT" == "supported" ]]; then echo "The hypothesis is **supported** by empirical evidence."; elif [[ "$RESULT" == "refuted" ]]; then echo "The hypothesis is **refuted** — behavior differs from expectation."; else echo "Results are **inconclusive** — probe failed, timed out, or produced ambiguous data."; fi)

## Anchors
@symbol:path/to/relevant:SymbolName
EOF
)

# Title with status
TITLE="EVIDENCE: $SLUG — $RESULT"
if [[ -n "$TITLE_SUFFIX" ]]; then
  TITLE="$TITLE — $TITLE_SUFFIX"
fi

# Ingest evidence note via native notebook_ops
TOOL_INPUT=$(jq -cn \
  --arg action "add_note" \
  --arg notebook_id "$NOTEBOOK_ID" \
  --arg title "$TITLE" \
  --arg content "$EVIDENCE_CONTENT" \
  '{action: $action, notebook_id: $notebook_id, title: $title, content: $content}')

echo "Ingesting evidence note into Research Brain ($NOTEBOOK_ID)..."
if [[ -d "/app/tools/notebook-ops" ]]; then
  cd /app/tools/notebook-ops
  TOOL_INPUT="$TOOL_INPUT" sh run.sh
else
  docker exec -i -e TOOL_INPUT="$TOOL_INPUT" mcp-server python3 /app/tools/notebook-ops/notebook_ops.py
fi