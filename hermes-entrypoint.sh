#!/bin/sh
# Hermes entrypoint wrapper:
# 1. Syncs config.yaml from host
# 2. Overwrites dashboard password hash from env var
# 3. Delegates to real entrypoint

set -e

cp /tmp/config.yaml.host /opt/hermes/data/config.yaml

# If password env var is set, regenerate the hash in config
if [ -n "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD:-}" ]; then
    HASH=$(sh -c '. /opt/hermes/.venv/bin/activate && python3 -c "
from plugins.dashboard_auth.basic import hash_password
import os
print(hash_password(os.environ[\"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD\"]))
"' 2>/dev/null || true)

    if [ -n "$HASH" ]; then
        sed -i "s|password_hash:.*|password_hash: ${HASH}|" /opt/hermes/data/config.yaml
    fi
fi

exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
