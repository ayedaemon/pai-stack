#!/bin/sh
# Hermes entrypoint wrapper:
# 1. Syncs hermes-config.yaml from host
# 2. Overwrites dashboard password hash from env var
# 3. Delegates to real entrypoint

set -e

# Ensure the data dir is owned by the UID Hermes drops to, so it can write
# sessions/keys into the (named) volume without EACCES.
chown -R "${HERMES_UID:-1000}:${HERMES_GID:-1000}" /opt/hermes/data 2>/dev/null || true

# Ensure SQLite WAL/SHM files are created group/world-writable so the kanban
# dashboard plugin and the dispatcher can both write to the same DB without
# "kanban.db-wal is read-only" warnings. The default umask 022 makes new files
# mode 0644, which means any process running as a non-owner (e.g. a worker
# dispatched under a different uid, or the plugin after a chown from a
# different container layer) cannot reopen the WAL. Setting umask 000 keeps
# new files at 0666; combined with the chown above, the kanban plugin's
# sqlite3.connect(...) call always produces a writable -wal/-shm pair.
# Also back-fix existing files in case they were created with the old umask
# (this is a no-op when permissions are already correct).
umask 000
find /opt/hermes/data -type f \( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.db.dispatch.lock' -o -name '*.db.init.lock' \) -exec chmod -c a+rw {} + 2>/dev/null || true

cp /tmp/hermes-config.yaml.host /opt/hermes/data/hermes-config.yaml

# Ensure the hermes CLI reads the same config the gateway does (CLI defaults to
# config.yaml, not hermes-config.yaml or $HERMES_CONFIG).
cp /opt/hermes/data/hermes-config.yaml /opt/hermes/data/config.yaml

# Silence upstream SyntaxWarning in update_cmd.py (cosmetic, harmless but noisy)
sed -i 's/venv\\Scripts/venv\\\\Scripts/g' /opt/hermes/hermes_cli/update_cmd.py 2>/dev/null || true

# If password env var is set, regenerate the hash in config
if [ -n "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD:-}" ]; then
    HASH=$(sh -c '. /opt/hermes/.venv/bin/activate && python3 -c "
from plugins.dashboard_auth.basic import hash_password
import os
print(hash_password(os.environ[\"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD\"]))
"' 2>/dev/null || true)

    if [ -n "$HASH" ]; then
        sed -i "s|password_hash:.*|password_hash: ${HASH}|" /opt/hermes/data/hermes-config.yaml
    fi
fi

# We also need to tell hermes to use the new config filename if possible.
# By default hermes might look for config.yaml. Let's export HERMES_CONFIG
export HERMES_CONFIG=/opt/hermes/data/hermes-config.yaml

# Start fs-notifier in background (watches STACK_ROOT, notifies downstream services)
if [ "${FS_NOTIFIER_ENABLED:-true}" = "true" ]; then
    /hermes/fs-notifier.sh &
fi

exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
