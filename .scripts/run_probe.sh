#!/bin/bash
# run_probe.sh — Execute a probe with safety guardrails.
# Usage: run_probe.sh <hypothesis-slug> [python|sh]

set -euo pipefail

SLUG="${1:-}"
MODE="${2:-python}"

if [[ -z "$SLUG" ]]; then
  echo "Usage: $0 <hypothesis-slug> [python|sh]"
  exit 1
fi

PROBE_DIR="/opt/data/probes/$SLUG"
if [[ ! -d "$PROBE_DIR" ]]; then
  echo "Error: Probe directory not found: $PROBE_DIR"
  exit 1
fi

cd "$PROBE_DIR"

case "$MODE" in
  python)
    SCRIPT="./probe.py"
    if [[ ! -f "$SCRIPT" ]]; then
      echo "Error: probe.py not found in $PROBE_DIR"
      exit 1
    fi
    ;;
  sh)
    SCRIPT="./probe.sh"
    if [[ ! -f "$SCRIPT" ]]; then
      echo "Error: probe.sh not found in $PROBE_DIR"
      exit 1
    fi
    ;;
  *)
    echo "Error: Mode must be 'python' or 'sh'"
    exit 1
    ;;
esac

echo "Running probe: $SLUG (mode: $MODE)"
echo "Directory: $PROBE_DIR"
echo "Script: $SCRIPT"
echo "---"

# Safety guardrails: timeout 30s, memory limit 256MB
# Note: ulimit -v is in KB, so 256MB = 262144 KB
if ! timeout 30 bash -c "ulimit -v 262144 && $SCRIPT" > results.json 2>&1; then
  EXIT_CODE=$?
  echo "Probe exited with code $EXIT_CODE (timeout=124, oom=137)"
  # Still try to read partial results
  if [[ -f results.json ]]; then
    cat results.json
  fi
  exit $EXIT_CODE
fi

echo "Results written to $PROBE_DIR/results.json"
cat results.json