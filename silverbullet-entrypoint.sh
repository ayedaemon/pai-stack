#!/bin/sh
set -e

# Setup plugs directory in the workspace
mkdir -p /space/_plug
# Copy preloaded plugs if they don't exist
cp -n /opt/preloaded_plugs/* /space/_plug/ 2>/dev/null || true

# Seed CONFIG.md if necessary
CONFIG_FILE="/space/CONFIG.md"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Creating new CONFIG.md with graphview plug..."
    cat << 'EOF' > "$CONFIG_FILE"
# SilverBullet Configuration

This is your main configuration page.

```space-lua
config.set({
  plugs = {
    "ghr:deepkn/silverbullet-graphview",
  }
})
```
EOF
else
    if ! grep -q "silverbullet-graphview" "$CONFIG_FILE"; then
        echo "Appending graphview plug to existing CONFIG.md..."
        cat << 'EOF' >> "$CONFIG_FILE"

# Added automatically
```space-lua
config.set({
  plugs = {
    "ghr:deepkn/silverbullet-graphview",
  }
})
```
EOF
    fi
fi

# Hand over to original SilverBullet entrypoint
exec /docker-entrypoint.sh "$@"
