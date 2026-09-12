#!/bin/sh
set -e

# Default to supervisord if no arguments passed
if [ $# -eq 0 ]; then
  set -- /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
fi

# Background auto-provisioning: waits for the local FastAPI service to report healthy,
# then provisions the cluster embedding service and fallback cloud provider models.
(
  /app/scripts/wait-for-api.sh
  echo "[pai-stack] Open Notebook API is ready, executing auto-provisioning..."
  /app/.venv/bin/python /app/provision.py || echo "[pai-stack] Auto-provisioning exited with code $?"
) &

# Delegate to original Open Notebook entrypoint
exec /app/scripts/docker-entrypoint.sh "$@"
