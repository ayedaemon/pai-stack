#!/bin/sh
# fs-notifier — generic filesystem watcher that notifies downstream services.
# Watches STACK_ROOT for changes, debounces, then triggers CodeGraph rebuild.
# Configurable via environment variables.
set -e

WATCH_PATH="${FS_NOTIFIER_WATCH_PATH:-/opt/data/Personal}"
NOTIFY_URL="${FS_NOTIFIER_NOTIFY_URL:-http://codegraph:20128/query}"
NOTIFY_PAYLOAD="${FS_NOTIFIER_NOTIFY_PAYLOAD:-{\"tool\":\"codegraph_reindex_workspace\",\"args\":{}}}"
DEBOUNCE="${FS_NOTIFIER_DEBOUNCE_SECONDS:-30}"
EXCLUDE_PATTERN='\.(db|db-wal|db-shm|lock|pyc)$'

log() { echo "[fs-notifier] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

log "starting — watch=${WATCH_PATH} debounce=${DEBOUNCE}s notify=${NOTIFY_URL}"

# Retry loop for initial connection (CodeGraph may not be ready at startup)
wait_for_service() {
  local url="$1" max_attempts="${2:-30}" attempt=1
  while [ "$attempt" -le "$max_attempts" ]; do
    if curl -sf "${url%/*}/health" >/dev/null 2>&1; then
      log "target service ready"
      return 0
    fi
    log "waiting for target service (attempt ${attempt}/${max_attempts})..."
    sleep 5
    attempt=$((attempt + 1))
  done
  log "WARNING: target service not ready after ${max_attempts} attempts, will retry on notify"
}

wait_for_service "$NOTIFY_URL"

# Main loop: inotifywait → debounce → notify
last_triggered=0
while true; do
  # Wait for any file change, excluding db/lock files
  inotifywait -r -q \
    --exclude "$EXCLUDE_PATTERN" \
    -e modify,create,delete,move \
    "$WATCH_PATH" 2>/dev/null || true

  now=$(date +%s)
  elapsed=$((now - last_triggered))

  if [ "$elapsed" -ge "$DEBOUNCE" ]; then
    log "change detected, triggering rebuild (debounce passed)"
    last_triggered=$now
    # Run rebuild in background so watcher stays responsive
    curl -sf -X POST "$NOTIFY_URL" \
      -H "Content-Type: application/json" \
      -d "$NOTIFY_PAYLOAD" >/dev/null 2>&1 &
  else
    remaining=$((DEBOUNCE - elapsed))
    log "change detected, debounce active (${remaining}s remaining)"
  fi
done
