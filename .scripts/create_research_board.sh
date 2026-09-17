#!/bin/bash
# create_research_board.sh — Create a Kanban board for a research swarm.
# Usage: create_research_board.sh <inquiry_question> <pattern> <notebook_id> [perspective1 perspective2 ...]

set -euo pipefail

QUESTION="${1:-}"
PATTERN="${2:-deep_research}"
NOTEBOOK_ID="${3:-}"
PERSPECTIVES="${4:-Systems Architecture Security & Threats Developer Ergonomics Failure Modes}"

if [[ -z "$QUESTION" || -z "$NOTEBOOK_ID" ]]; then
  echo "Usage: $0 <inquiry_question> <pattern> <notebook_id> [perspectives...]"
  echo "Patterns: deep_research, quick_fact_check, empirical_validation"
  exit 1
fi

# Generate board slug
SLUG=$(echo "$QUESTION" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g' | cut -c1-50)
BOARD_NAME="research-${SLUG}-$(date +%s)"

# This would integrate with Hermes Kanban API
# For now, output the board specification as JSON for manual creation or API call

cat <<EOF
{
  "board_name": "$BOARD_NAME",
  "inquiry_question": "$QUESTION",
  "pattern": "$PATTERN",
  "notebook_id": "$NOTEBOOK_ID",
  "execution_dir": "/opt/data/workspace/github.com/ayedaemon/pai-stack",
  "anchor_symbols": [],
  "columns": [
    {"name": "Decompose", "limit": 1},
    {"name": "Research", "limit": 4},
    {"name": "Synthesize", "limit": 1},
    {"name": "ADR Author", "limit": 1},
    {"name": "Review", "limit": 1},
    {"name": "Done", "limit": 10}
  ],
  "tasks": [
EOF

# Generate tasks based on pattern
case "$PATTERN" in
  deep_research)
    # Decompose task
    cat <<TASK
    {
      "id": "task-decompose",
      "title": "Decompose: $QUESTION",
      "column": "Decompose",
      "worker": "orchestrator",
      "action": "decompose_question_into_perspectives",
      "input": {
        "question": "$QUESTION",
        "perspectives": ["Systems Architecture", "Security & Threats", "Developer Ergonomics", "Failure Modes"]
      },
      "output_keys": ["perspective_tasks"]
    },
TASK

    # Research tasks per perspective
    i=1
    for PERSPECTIVE in $PERSPECTIVES; do
      cat <<TASK
    {
      "id": "task-research-$i",
      "title": "Research: $PERSPECTIVE",
      "column": "Research",
      "worker": "researcher",
      "depends_on": ["task-decompose"],
      "input": {
        "topic": "$QUESTION",
        "perspective": "$PERSPECTIVE",
        "notebook_id": "$NOTEBOOK_ID",
        "anchor_symbols": [],
        "context": "Perspective: $PERSPECTIVE. Focus on relevant sub-questions."
      },
      "output_keys": ["evidence_note_ids", "symbol_anchors", "confidence", "unresolved_questions"]
    },
TASK
      i=$((i+1))
    done

    # Synthesize task
    cat <<TASK
    {
      "id": "task-synthesize",
      "title": "Synthesize findings",
      "column": "Synthesize",
      "worker": "synthesizer",
      "depends_on": ["task-research-1", "task-research-2", "task-research-3", "task-research-4"],
      "input": {
        "inquiry_question": "$QUESTION",
        "target_format": "adr_section",
        "worker_outputs": "\${tasks.research_parallel.outputs}"
      },
      "output_keys": ["synthesis", "confidence", "unresolved_questions", "symbol_anchors"]
    },
TASK

    # ADR Author task
    cat <<TASK
    {
      "id": "task-adr",
      "title": "Author Living ADR",
      "column": "ADR Author",
      "worker": "adr_author",
      "depends_on": ["task-synthesize"],
      "input": {
        "synthesis": "\${tasks.synthesize.output.synthesis}",
        "decision_topic": "$QUESTION",
        "symbols": "\${tasks.synthesize.output.symbol_anchors}",
        "context": "Full inquiry context from decomposition and research phases."
      },
      "output_keys": ["adr_path", "adr_number"]
    }
TASK
    ;;
    
  quick_fact_check)
    cat <<TASK
    {
      "id": "task-research",
      "title": "Research: $QUESTION",
      "column": "Research",
      "worker": "researcher",
      "input": {
        "topic": "$QUESTION",
        "notebook_id": "$NOTEBOOK_ID",
        "anchor_symbols": [],
        "context": "Quick fact check. Find definitive answer with evidence."
      },
      "output_keys": ["evidence_note_ids", "symbol_anchors", "confidence", "answer"]
    },
TASK
    cat <<TASK
    {
      "id": "task-answer",
      "title": "Synthesize answer",
      "column": "Synthesize",
      "worker": "synthesizer",
      "depends_on": ["task-research"],
      "input": {
        "inquiry_question": "$QUESTION",
        "target_format": "answer",
        "worker_outputs": "\${tasks.research.outputs}"
      },
      "output_keys": ["answer", "confidence", "evidence_note_ids"]
    }
TASK
    ;;

  empirical_validation)
    cat <<TASK
    {
      "id": "task-probe",
      "title": "Run probe: $QUESTION",
      "column": "Research",
      "worker": "researcher",
      "action": "run_hypothesis_probe",
      "input": {
        "hypothesis": "$QUESTION",
        "notebook_id": "$NOTEBOOK_ID",
        "anchor_symbols": []
      },
      "output_keys": ["probe_slug", "results", "evidence_note_id"]
    },
TASK
    cat <<TASK
    {
      "id": "task-document",
      "title": "Ingest evidence note",
      "column": "Research",
      "worker": "researcher",
      "action": "ingest_evidence",
      "depends_on": ["task-probe"],
      "input": {
        "probe_slug": "\${tasks.probe.output.probe_slug}",
        "notebook_id": "$NOTEBOOK_ID"
      },
      "output_keys": ["evidence_note_id"]
    }
TASK
    ;;
esac

cat <<EOF
  ]
}
EOF

echo ""
echo "Board spec generated. To create in Hermes:"
echo "  1. Open Hermes dashboard → Kanban"
echo "  2. Create board: $BOARD_NAME"
echo "  3. Add columns: Decompose, Research, Synthesize, ADR Author, Review, Done"
echo "  4. Add tasks per JSON above"
echo "  5. Assign workers (researcher, synthesizer, adr_author) to cards"