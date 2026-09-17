#!/bin/bash
# new_probe.sh — Scaffold a new empirical probe directory.
# Usage: new_probe.sh <hypothesis-slug> "Hypothesis statement"

set -euo pipefail

SLUG="${1:-}"
HYPOTHESIS="${2:-}"

if [[ -z "$SLUG" || -z "$HYPOTHESIS" ]]; then
  echo "Usage: $0 <hypothesis-slug> \"Hypothesis statement\""
  echo "Example: $0 fastapi-background-tasks-concurrent \"BackgroundTasks run concurrently\""
  exit 1
fi

PROBE_DIR="/opt/data/probes/$SLUG"
mkdir -p "$PROBE_DIR"

# hypothesis.md
cat > "$PROBE_DIR/hypothesis.md" <<EOF
# Hypothesis: $SLUG

**Statement**: $HYPOTHESIS

**Expected Outcome**: 
- [ ] Supported
- [ ] Refuted  
- [ ] Inconclusive

**Related Code**: @symbol:path/to/relevant:SymbolName

**Context**: Why this matters for the current task.
EOF

# probe.py template
cat > "$PROBE_DIR/probe.py" <<'PYEOF'
#!/usr/bin/env python3
"""
Empirical probe: <hypothesis-slug>

Tests: <hypothesis statement>
"""
import json
import time
import sys
from pathlib import Path

def main():
    start = time.perf_counter()
    
    # TODO: Implement test logic here
    # Example:
    # result = some_function_under_test()
    
    elapsed = time.perf_counter() - start
    
    output = {
        "hypothesis": "<hypothesis statement>",
        "result": "inconclusive",  # supported | refuted | inconclusive
        "metrics": {"elapsed_s": elapsed},
        "stdout": "",
        "stderr": ""
    }
    
    print(json.dumps(output, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
PYEOF

chmod +x "$PROBE_DIR/probe.py"

# probe.sh alternative template
cat > "$PROBE_DIR/probe.sh" <<'SHEOF'
#!/bin/bash
# Empirical probe: <hypothesis-slug>
# Tests: <hypothesis statement>

set -euo pipefail

start=$(date +%s.%N)

# TODO: Implement test logic here
# Example:
# result=$(some_command_under_test)

elapsed=$(echo "$(date +%s.%N) - $start" | bc)

cat <<EOF
{
  "hypothesis": "<hypothesis statement>",
  "result": "inconclusive",
  "metrics": {"elapsed_s": $elapsed},
  "stdout": "",
  "stderr": ""
}
EOF
SHEOF

chmod +x "$PROBE_DIR/probe.sh"

echo "Created probe scaffold at $PROBE_DIR/"
echo "  hypothesis.md  — edit with full hypothesis details"
echo "  probe.py       — Python template (edit TODO)"
echo "  probe.sh       — Shell template (edit TODO)"
echo ""
echo "Next: Edit probe.py/probe.sh, then run: run_probe.sh $SLUG"