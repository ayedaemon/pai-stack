#!/bin/sh
# Hermes entrypoint wrapper:
# 1. Sets permissions on Hermes home / SQLite WAL files
# 2. Configures knowledge base directories dynamically relative to HERMES_DATA_DIR
# 3. Sets dashboard auth password hash if provided
# 4. Spawns filesystem notifier in background
# 5. Delegates to upstream entrypoint

set -e

# Ensure lazy-packages directory exists inside hermes-data volume
mkdir -p /opt/hermes/data/lazy-packages

# Ensure /opt/data directory exists and is owned by Hermes user (for helper scripts)
mkdir -p /opt/data
chown -R "${HERMES_UID:-1000}:${HERMES_GID:-1000}" /opt/data 2>/dev/null || true

# Ensure the hermes runtime data dir is owned by the UID Hermes drops to
chown -R "${HERMES_UID:-1000}:${HERMES_GID:-1000}" /opt/hermes/data 2>/dev/null || true

# Ensure Mnemosyne memory provider plugin wrapper and skill are registered
if [ -x /opt/hermes/.venv/bin/mnemosyne-hermes ]; then
    /opt/hermes/.venv/bin/mnemosyne-hermes install --mode wrapper --python /opt/hermes/.venv/bin/python3 --no-bootstrap --force 2>/dev/null || true
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

# Inject KB_DIRS into knowledgebase.directories relative to DATA_DIR
if [ -n "${KB_DIRS:-}" ] && [ "$KB_DIRS" != "." ]; then
    KB_YAML=$(echo "$KB_DIRS" | python3 -c "
import sys, os
base_dir = os.environ.get('HERMES_DATA_DIR', '/opt/data/workspace').rstrip('/')
dirs = [d.strip() for d in sys.stdin.read().split(',') if d.strip()]
print('\n'.join(f'    - {base_dir}/{d.lstrip(\"/\")}' for d in dirs))
")
    sed -i "/^knowledgebase:/,/^[^ ]/{s|directories:.*|directories:\n${KB_YAML}|}" \
        /opt/hermes/data/hermes-config.yaml
else
    # Index entire DATA_DIR
    sed -i "/^knowledgebase:/,/^[^ ]/{s|directories:.*|directories:\n    - ${DATA_DIR}|}" \
        /opt/hermes/data/hermes-config.yaml
fi

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
export FS_NOTIFIER_WATCH_PATH="${FS_NOTIFIER_WATCH_PATH:-${DATA_DIR}}"

# Start fs-notifier in background
if [ "${FS_NOTIFIER_ENABLED:-true}" = "true" ]; then
    if [ -f /fs-notifier.sh ]; then
        /bin/sh /fs-notifier.sh &
    elif [ -f /hermes/fs-notifier.sh ]; then
        /bin/sh /hermes/fs-notifier.sh &
    else
        echo "[WARN] fs-notifier.sh not found, file watching disabled"
    fi
fi

exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
