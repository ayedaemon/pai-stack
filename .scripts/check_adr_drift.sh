#!/bin/bash
# check_adr_drift.sh — Check all ADRs for symbol hash drift.
# Usage: check_adr_drift.sh

set -euo pipefail

# Find all ADR files
PLANNING_DIR=$(find /opt/data/workspace -maxdepth 4 -name ".planning" -type d 2>/dev/null | head -1)
if [[ -z "$PLANNING_DIR" ]]; then
  echo "No .planning directory found"
  exit 0
fi

RESEARCH_DIR="$PLANNING_DIR/research"
if [[ ! -d "$RESEARCH_DIR" ]]; then
  echo "No research directory found"
  exit 0
fi

ADR_FILES=$(find "$RESEARCH_DIR" -name "ADR-*.md" -type f 2>/dev/null)
if [[ -z "$ADR_FILES" ]]; then
  echo "No ADR files found"
  exit 0
fi

DRIFT_FOUND=false

for ADR_FILE in $ADR_FILES; do
  echo "Checking: $(basename "$ADR_FILE")"
  
  # Extract symbol lines with hashes
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*@symbol:(.+)#sha256:([a-f0-9]+)$ ]]; then
      SYMBOL_REF="${BASH_REMATCH[1]}"
      OLD_HASH="${BASH_REMATCH[2]}"
      
      # Parse path and symbol
      if [[ "$SYMBOL_REF" =~ ^(.+):(.+)$ ]]; then
        FILE_PATH="${BASH_REMATCH[1]}"
        SYMBOL_NAME="${BASH_REMATCH[2]}"
        FULL_PATH="/opt/data/workspace/$FILE_PATH"
        
        if [[ -f "$FULL_PATH" ]]; then
          NEW_HASH=$(sha256sum "$FULL_PATH" | cut -d' ' -f1 | cut -c1-16)
          if [[ "$OLD_HASH" != "$NEW_HASH" ]]; then
            echo "  DRIFT DETECTED: $SYMBOL_REF"
            echo "    Old: $OLD_HASH"
            echo "    New: $NEW_HASH"
            echo "    File: $FULL_PATH"
            DRIFT_FOUND=true
            
            # Flag in findings.md
            FINDINGS_FILE="$PLANNING_DIR/findings.md"
            if [[ -f "$FINDINGS_FILE" ]]; then
              echo "" >> "$FINDINGS_FILE"
              echo "### DRIFT_DETECTED: $(basename "$ADR_FILE")" >> "$FINDINGS_FILE"
              echo "Symbol \`$SYMBOL_REF\` hash mismatch (old: $OLD_HASH, new: $NEW_HASH)." >> "$FINDINGS_FILE"
              echo "Triggered review of ADR." >> "$FINDINGS_FILE"
            fi
          fi
        else
          echo "  FILE MISSING: $FULL_PATH"
        fi
      fi
    fi
  done < "$ADR_FILE"
done

if [[ "$DRIFT_FOUND" == "true" ]]; then
  echo ""
  echo "⚠️  Drift detected in one or more ADRs. Review needed."
  exit 1
else
  echo "✓ No drift detected."
  exit 0
fi