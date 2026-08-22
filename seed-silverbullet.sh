#!/usr/bin/env bash
# SilverBullet initialization script — sets up the space and plugs
# Usage: ./seed-silverbullet.sh

set -uo pipefail

SB_DIR="$HOME/Personal/silverbullet"
CONFIG_FILE="$SB_DIR/CONFIG.md"

echo "🌱 Seeding SilverBullet configuration: graphview plug"

# Ensure the SilverBullet space directory exists
mkdir -p "$SB_DIR"

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
    echo "✅ Created $CONFIG_FILE"
else
    echo "Checking existing CONFIG.md for graphview plug..."
    if ! grep -q "silverbullet-graphview" "$CONFIG_FILE"; then
        echo "Appending graphview plug to existing CONFIG.md..."
        cat << 'EOF' >> "$CONFIG_FILE"

# Added by seed-silverbullet.sh
```space-lua
-- Appending graphview plug
config.set({
  plugs = {
    "ghr:deepkn/silverbullet-graphview",
  }
})
```
EOF
        echo "✅ Updated $CONFIG_FILE"
    else
        echo "✅ graphview plug already configured in $CONFIG_FILE"
    fi
fi

echo "🌱 Seed complete."
echo "💡 Note: Open SilverBullet and run the command 'Plugs: Update' to install the plug."
