#!/bin/sh
# notebook_ops — MCP tool bridge to the Open Notebook REST API.
#
# Reads $TOOL_INPUT (JSON via jq), calls http://open-notebook:5055, prints JSON.
#
# Graceful degradation: when OPEN_NOTEBOOK_URL is unset (base stack running
# without the docker-compose.open-notebook.yml overlay), returns a structured
# {"available":false} response instead of crashing. Hermes sees this, logs it,
# and falls back to CodeGraph semantic search.
#
# API surface used:
#   GET  /notebooks          — list all notebooks
#   POST /notebooks          — create a notebook  {name, description}
#   POST /search             — search             {query, type, notebook_id}
#   POST /notes              — create a note (via /notes endpoint with notebook_id param)
#   POST /sources (form)     — ingest a URL source

set -e

OPEN_NOTEBOOK_URL="${OPEN_NOTEBOOK_URL:-}"
ALLOWED_ACTIONS="list_notebooks create_notebook search add_note add_source_url poll_source_status get_source add_source_file ask_notebook get_notebook"

# ── Graceful no-op when overlay is not active ──────────────────────────────
if [ -z "$OPEN_NOTEBOOK_URL" ]; then
  printf '{"available":false,"error":"Open Notebook is not configured","hint":"Run make up-all to enable the Open Notebook research stack"}\n'
  exit 0
fi

# ── Parse inputs ───────────────────────────────────────────────────────────
ACTION=$(printf '%s' "$TOOL_INPUT" | jq -r '.action // empty' 2>/dev/null)
NOTEBOOK_ID=$(printf '%s' "$TOOL_INPUT" | jq -r '.notebook_id // empty' 2>/dev/null)
NOTEBOOK_NAME=$(printf '%s' "$TOOL_INPUT" | jq -r '.notebook_name // empty' 2>/dev/null)
NOTEBOOK_DESC=$(printf '%s' "$TOOL_INPUT" | jq -r '.notebook_description // ""' 2>/dev/null)
QUERY=$(printf '%s' "$TOOL_INPUT" | jq -r '.query // empty' 2>/dev/null)
SEARCH_TYPE=$(printf '%s' "$TOOL_INPUT" | jq -r '.search_type // "vector"' 2>/dev/null)
TITLE=$(printf '%s' "$TOOL_INPUT" | jq -r '.title // ""' 2>/dev/null)
CONTENT=$(printf '%s' "$TOOL_INPUT" | jq -r '.content // empty' 2>/dev/null)
URL=$(printf '%s' "$TOOL_INPUT" | jq -r '.url // empty' 2>/dev/null)
SOURCE_ID=$(printf '%s' "$TOOL_INPUT" | jq -r '.source_id // empty' 2>/dev/null)
FILE_PATH=$(printf '%s' "$TOOL_INPUT" | jq -r '.file_path // empty' 2>/dev/null)
STRATEGY_MODEL=$(printf '%s' "$TOOL_INPUT" | jq -r '.strategy_model // empty' 2>/dev/null)
ANSWER_MODEL=$(printf '%s' "$TOOL_INPUT" | jq -r '.answer_model // empty' 2>/dev/null)
FINAL_ANSWER_MODEL=$(printf '%s' "$TOOL_INPUT" | jq -r '.final_answer_model // empty' 2>/dev/null)

# ── Validate action ────────────────────────────────────────────────────────
case " $ALLOWED_ACTIONS " in
  *" $ACTION "*) ;;
  *)
    printf '{"error":"unknown action: %s","allowed":"%s"}\n' "$ACTION" "$ALLOWED_ACTIONS" >&2
    exit 1
    ;;
esac

# ── Auth header (optional) ─────────────────────────────────────────────────
AUTH_ARGS=""
if [ -n "${OPEN_NOTEBOOK_PASSWORD:-}" ]; then
  AUTH_ARGS="-H X-Notebook-Password: ${OPEN_NOTEBOOK_PASSWORD}"
fi

# ── Shared curl helper — prints response or error ──────────────────────────
# Usage: api_json METHOD ENDPOINT [JSON_BODY]
api_json() {
  METHOD="$1"; ENDPOINT="$2"; BODY="${3:-}"
  if [ -n "$BODY" ]; then
    curl -sf --max-time 25 \
      -X "$METHOD" \
      -H "Content-Type: application/json" \
      ${AUTH_ARGS:+-H "$AUTH_ARGS"} \
      -d "$BODY" \
      "${OPEN_NOTEBOOK_URL}${ENDPOINT}" 2>/dev/null \
      || printf '{"error":"request failed","endpoint":"%s"}\n' "$ENDPOINT"
  else
    curl -sf --max-time 25 \
      -X "$METHOD" \
      ${AUTH_ARGS:+-H "$AUTH_ARGS"} \
      "${OPEN_NOTEBOOK_URL}${ENDPOINT}" 2>/dev/null \
      || printf '{"error":"request failed","endpoint":"%s"}\n' "$ENDPOINT"
  fi
}

# ── Dispatch ───────────────────────────────────────────────────────────────
case "$ACTION" in

  list_notebooks)
    api_json GET /api/notebooks
    ;;

  create_notebook)
    if [ -z "$NOTEBOOK_NAME" ]; then
      printf '{"error":"notebook_name is required for create_notebook"}\n' >&2
      exit 1
    fi
    BODY=$(jq -cn \
      --arg name "$NOTEBOOK_NAME" \
      --arg desc "$NOTEBOOK_DESC" \
      '{name: $name, description: $desc}')
    api_json POST /api/notebooks "$BODY"
    ;;

  search)
    if [ -z "$QUERY" ]; then
      printf '{"error":"query is required for search"}\n' >&2
      exit 1
    fi
    # Build scope: include notebook_id if provided, otherwise search all notebooks
    if [ -n "$NOTEBOOK_ID" ]; then
      BODY=$(jq -cn \
        --arg q "$QUERY" \
        --arg t "$SEARCH_TYPE" \
        --arg nb "$NOTEBOOK_ID" \
        '{query: $q, type: $t, notebook_id: $nb}')
    else
      BODY=$(jq -cn \
        --arg q "$QUERY" \
        --arg t "$SEARCH_TYPE" \
        '{query: $q, type: $t}')
    fi
    api_json POST /api/search "$BODY"
    ;;

  add_note)
    if [ -z "$NOTEBOOK_ID" ]; then
      printf '{"error":"notebook_id is required for add_note"}\n' >&2
      exit 1
    fi
    if [ -z "$CONTENT" ]; then
      printf '{"error":"content is required for add_note"}\n' >&2
      exit 1
    fi
    # Notes endpoint: POST /api/notes with notebook_id as a query param
    BODY=$(jq -cn \
      --arg title "${TITLE:-Hermes Note}" \
      --arg content "$CONTENT" \
      --arg note_type "human" \
      '{title: $title, content: $content, note_type: $note_type}')
    curl -sf --max-time 25 \
      -X POST \
      -H "Content-Type: application/json" \
      ${AUTH_ARGS:+-H "$AUTH_ARGS"} \
      -d "$BODY" \
      "${OPEN_NOTEBOOK_URL}/api/notes?notebook_id=${NOTEBOOK_ID}" 2>/dev/null \
      || printf '{"error":"request failed","endpoint":"/api/notes"}\n'
    ;;

  add_source_url)
    if [ -z "$NOTEBOOK_ID" ]; then
      printf '{"error":"notebook_id is required for add_source_url"}\n' >&2
      exit 1
    fi
    if [ -z "$URL" ]; then
      printf '{"error":"url is required for add_source_url"}\n' >&2
      exit 1
    fi
    # Sources endpoint uses multipart form data (not JSON).
    # async_processing=true so the tool returns immediately with a source ID;
    # actual content extraction happens in the background worker.
    curl -sf --max-time 25 \
      -X POST \
      ${AUTH_ARGS:+-H "$AUTH_ARGS"} \
      -F "type=link" \
      -F "url=${URL}" \
      -F "notebook_id=${NOTEBOOK_ID}" \
      -F "title=${TITLE}" \
      -F "async_processing=true" \
      "${OPEN_NOTEBOOK_URL}/api/sources" 2>/dev/null \
      || printf '{"error":"request failed","endpoint":"/api/sources"}\n'
    ;;

  poll_source_status)
    if [ -z "$SOURCE_ID" ]; then
      printf '{"error":"source_id is required for poll_source_status"}\n' >&2
      exit 1
    fi
    api_json GET "/api/sources/${SOURCE_ID}/status"
    ;;

  get_source)
    if [ -z "$SOURCE_ID" ]; then
      printf '{"error":"source_id is required for get_source"}\n' >&2
      exit 1
    fi
    api_json GET "/api/sources/${SOURCE_ID}"
    ;;

  add_source_file)
    if [ -z "$NOTEBOOK_ID" ]; then
      printf '{"error":"notebook_id is required for add_source_file"}\n' >&2
      exit 1
    fi
    if [ -z "$FILE_PATH" ]; then
      printf '{"error":"file_path is required for add_source_file"}\n' >&2
      exit 1
    fi
    if [ ! -f "$FILE_PATH" ]; then
      printf '{"error":"file not found: %s"}\n' "$FILE_PATH" >&2
      exit 1
    fi
    curl -sf --max-time 60 \
      -X POST \
      ${AUTH_ARGS:+-H "$AUTH_ARGS"} \
      -F "type=file" \
      -F "file=@${FILE_PATH}" \
      -F "notebook_id=${NOTEBOOK_ID}" \
      -F "title=${TITLE}" \
      -F "async_processing=true" \
      "${OPEN_NOTEBOOK_URL}/api/sources" 2>/dev/null \
      || printf '{"error":"request failed","endpoint":"/api/sources"}\n'
    ;;

  ask_notebook)
    if [ -z "$NOTEBOOK_ID" ]; then
      printf '{"error":"notebook_id is required for ask_notebook"}\n' >&2
      exit 1
    fi
    if [ -z "$QUERY" ]; then
      printf '{"error":"query is required for ask_notebook"}\n' >&2
      exit 1
    fi
    BODY=$(jq -cn \
      --arg q "$QUERY" \
      --arg nb "$NOTEBOOK_ID" \
      --arg sm "${STRATEGY_MODEL:-}" \
      --arg am "${ANSWER_MODEL:-}" \
      --arg fam "${FINAL_ANSWER_MODEL:-}" \
      '{question: $q, notebook_id: $nb, strategy_model: ($sm | select(. != "")), answer_model: ($am | select(. != "")), final_answer_model: ($fam | select(. != ""))}')
    api_json POST /api/search/ask/simple "$BODY"
    ;;

  get_notebook)
    if [ -z "$NOTEBOOK_ID" ]; then
      printf '{"error":"notebook_id is required for get_notebook"}\n' >&2
      exit 1
    fi
    api_json GET "/api/notebooks/${NOTEBOOK_ID}"
    ;;

esac
