#!/bin/sh
# Hermes entrypoint wrapper:
# 1. Sets permissions on Hermes home / SQLite WAL files
# 2. Copies and normalizes config paths
# 3. Sets dashboard auth password hash if provided
# 4. Spawns filesystem notifier in background
# 5. Delegates to upstream entrypoint

set -e

# Ensure lazy-packages directory exists inside hermes-data volume
mkdir -p /opt/hermes/data/lazy-packages

# Ensure /opt/data directory exists and is owned by Hermes user (for helper scripts)
mkdir -p /opt/data
chown -R "${HERMES_UID:-1000}:${HERMES_GID:-1000}" /opt/data 2>/dev/null || true

# Ensure Mnemosyne memory provider plugin wrapper and skill are registered
if [ -x /opt/hermes/.venv/bin/mnemosyne-hermes ]; then
    /opt/hermes/.venv/bin/mnemosyne-hermes install --mode wrapper --python /opt/hermes/.venv/bin/python3 --no-bootstrap --force 2>/dev/null || true
fi

# Ensure Hermes Labyrinth is linked into user plugins root
mkdir -p /opt/hermes/data/plugins
if [ -d /opt/hermes/plugins/hermes-labyrinth ] && [ ! -e /opt/hermes/data/plugins/hermes-labyrinth ]; then
    ln -s /opt/hermes/plugins/hermes-labyrinth /opt/hermes/data/plugins/hermes-labyrinth
fi

# Ensure SQLite WAL/SHM files are created group/world-writable
umask 000
find /opt/hermes/data -type f \( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.db.dispatch.lock' -o -name '*.db.init.lock' \) -exec chmod -c a+rw {} + 2>/dev/null || true

cp /tmp/hermes-config.yaml.host /opt/hermes/data/hermes-config.yaml

DATA_DIR="${HERMES_DATA_DIR:-/opt/data/workspace}"

# Dynamically normalize paths in config to match DATA_DIR
python3 -c "
import re
with open('/opt/hermes/data/hermes-config.yaml', 'r') as f:
    content = f.read()
content = content.replace('/opt/hermes/data/workspace', '${DATA_DIR}')
content = content.replace('/stack_root', '${DATA_DIR}')
content = re.sub(r'(/opt/data)+/workspace', '${DATA_DIR}', content)
content = re.sub(r'(?<!/opt/data)/workspace', '${DATA_DIR}', content)
with open('/opt/hermes/data/hermes-config.yaml', 'w') as f:
    f.write(content)
"

# Ensure CLI reads the same config
cp /opt/hermes/data/hermes-config.yaml /opt/hermes/data/config.yaml

# Silence harmless upstream syntax warning in update_cmd.py
sed -i 's/venv\\Scripts/venv\\\\Scripts/g' /opt/hermes/hermes_cli/update_cmd.py 2>/dev/null || true

# If password env var is set, regenerate hash in config
if [ -n "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD:-}" ]; then
    HASH=$(sh -c '. /opt/hermes/.venv/bin/activate && python3 -c "
from plugins.dashboard_auth.basic import hash_password
import os
print(hash_password(os.environ[\"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD\"]))
"' 2>/dev/null || true)

    if [ -n "$HASH" ]; then
        sed -i "s|password_hash:.*|password_hash: ${HASH}|" /opt/hermes/data/hermes-config.yaml
        sed -i "s|password_hash:.*|password_hash: ${HASH}|" /opt/hermes/data/config.yaml
    fi
fi

export HERMES_CONFIG=/opt/hermes/data/hermes-config.yaml

# Ensure all created files/plugins are owned by the correct user before dropping privileges
chown -R "${HERMES_UID:-1000}:${HERMES_GID:-1000}" /opt/hermes/data 2>/dev/null || true

exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
