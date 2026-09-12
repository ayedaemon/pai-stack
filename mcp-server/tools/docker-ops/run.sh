#!/bin/sh

# ── Configuration ──────────────────────────────────────────────────────────────
PROJECT="${COMPOSE_PROJECT_NAME:-pai-stack}"
ALLOWED_SERVICES="hermes codegraph embeddings mcp-server open-notebook surrealdb"
ALLOWED_ACTIONS="list status logs restart start stop exec"
LOG_DIR="${LOG_DIR:-/app/logs}"
LOG_FILE="$LOG_DIR/docker-ops.log"
mkdir -p "$LOG_DIR" 2>/dev/null || true

START_MS=$(date +%s%3N 2>/dev/null || echo 0)

# ── Logging Helper ─────────────────────────────────────────────────────────────
log_action() {
  EXIT_CODE=$1
  END_MS=$(date +%s%3N 2>/dev/null || echo 0)
  DURATION=0
  if [ "$START_MS" -gt 0 ] 2>/dev/null && [ "$END_MS" -gt 0 ] 2>/dev/null; then
    DURATION=$((END_MS - START_MS))
  fi
  TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  if [ -d "$LOG_DIR" ] && [ -w "$LOG_DIR" ]; then
    printf '[%s] action=%s service=%s cmd=%s exit=%s duration=%sms\n' \
      "$TS" "$ACTION" "$SERVICE" "$CMD" "$EXIT_CODE" "$DURATION" >> "$LOG_FILE" 2>/dev/null || true
  fi
}

# ── Parse Input ────────────────────────────────────────────────────────────────
ACTION=$(printf '%s' "$TOOL_INPUT" | jq -r '.action // empty' 2>/dev/null)
SERVICE=$(printf '%s' "$TOOL_INPUT" | jq -r '.service // empty' 2>/dev/null)
LINES=$(printf '%s' "$TOOL_INPUT" | jq -r '.lines // 50' 2>/dev/null)
CMD=$(printf '%s' "$TOOL_INPUT" | jq -r '.cmd // empty' 2>/dev/null)

# ── Validate Action ────────────────────────────────────────────────────────────
case " $ALLOWED_ACTIONS " in
  *" $ACTION "*) ;;
  *)
    ERR="unknown action: $ACTION. Allowed: $ALLOWED_ACTIONS"
    printf '%s\n' "$ERR" >&2
    log_action 1
    exit 1
    ;;
esac

# ── Validate Service ───────────────────────────────────────────────────────────
if [ "$ACTION" != "list" ]; then
  if [ -z "$SERVICE" ]; then
    ERR="service is required for action: $ACTION"
    printf '%s\n' "$ERR" >&2
    log_action 1
    exit 1
  fi
  case " $ALLOWED_SERVICES " in
    *" $SERVICE "*) ;;
    *)
      ERR="unknown service: $SERVICE. Allowed: $ALLOWED_SERVICES"
      printf '%s\n' "$ERR" >&2
      log_action 1
      exit 1
      ;;
  esac
fi

# ── Validate Exec Requirements ─────────────────────────────────────────────────
if [ "$ACTION" = "exec" ] && [ -z "$CMD" ]; then
  ERR="cmd is required for exec action"
  printf '%s\n' "$ERR" >&2
  log_action 1
  exit 1
fi

# ── Clamp Log Lines ────────────────────────────────────────────────────────────
if [ "$LINES" -gt 500 ] 2>/dev/null; then LINES=500; fi
if [ "$LINES" -lt 1 ] 2>/dev/null; then LINES=50; fi

# ── Dispatch Directly via Docker Socket ────────────────────────────────────────
OUTPUT=""
RESULT=0

case "$ACTION" in
  list)
    OUTPUT=$(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{"id":"{{.ID}}","name":"{{.Names}}","status":"{{.Status}}","state":"{{.State}}"}' 2>&1 | jq -s '.')
    RESULT=$?
    ;;
  status)
    OUTPUT=$(docker inspect "$SERVICE" --format '{{json .State}}' 2>&1)
    RESULT=$?
    ;;
  logs)
    OUTPUT=$(docker logs --tail="$LINES" "$SERVICE" 2>&1)
    RESULT=$?
    ;;
  restart)
    OUTPUT=$(docker restart "$SERVICE" 2>&1)
    RESULT=$?
    [ $RESULT -eq 0 ] && OUTPUT=$(printf '{"ok":true,"message":"restarted %s"}\n' "$SERVICE")
    ;;
  start)
    OUTPUT=$(docker start "$SERVICE" 2>&1)
    RESULT=$?
    [ $RESULT -eq 0 ] && OUTPUT=$(printf '{"ok":true,"message":"started %s"}\n' "$SERVICE")
    ;;
  stop)
    OUTPUT=$(docker stop "$SERVICE" 2>&1)
    RESULT=$?
    [ $RESULT -eq 0 ] && OUTPUT=$(printf '{"ok":true,"message":"stopped %s"}\n' "$SERVICE")
    ;;
  exec)
    OUTPUT=$(docker exec "$SERVICE" sh -c "$CMD" 2>&1)
    RESULT=$?
    ;;
esac

log_action $RESULT

if [ $RESULT -ne 0 ]; then
  printf '%s\n' "$OUTPUT" >&2
  exit $RESULT
else
  printf '%s\n' "$OUTPUT"
  exit 0
fi
