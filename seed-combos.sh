#!/usr/bin/env bash
# OmniRoute combo seed script — run inside the omniroute container at startup
# This makes combos declarative and reproducible (git-trackable)
# Usage: docker exec omniroute /app/data/seed-combos.sh

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:20128}"
COMBO_NAME="personal/gemini-fallback"

echo "🌱 Seeding OmniRoute combo: $COMBO_NAME"

# Delete existing combo if present (idempotent)
curl -s -X DELETE "$API_BASE/api/combos/$COMBO_NAME" >/dev/null 2>&1 || true

# Create the combo
curl -s -X POST "$API_BASE/api/combos" \
  -H "Content-Type: application/json" \
  -d '{
  "name": "personal/gemini-fallback",
  "description": "Gemini subscription (antigravity) first, free opencode fallback on exhaustion",
  "models": [
    {"kind":"model","model":"antigravity/gemini-3.6-flash-high","providerId":"antigravity","weight":100},
    {"kind":"model","model":"antigravity/gemini-3.6-flash-medium","providerId":"antigravity","weight":95},
    {"kind":"model","model":"antigravity/gemini-pro-agent","providerId":"antigravity","weight":90},
    {"kind":"model","model":"antigravity/gemini-3.1-pro-low","providerId":"antigravity","weight":85},
    {"kind":"model","model":"antigravity/gemini-3-flash-agent","providerId":"antigravity","weight":80},
    {"kind":"model","model":"antigravity/gemini-3.6-flash-low","providerId":"antigravity","weight":75},
    {"kind":"model","model":"antigravity/gemini-3.5-flash-low","providerId":"antigravity","weight":70},
    {"kind":"model","model":"antigravity/gemini-3.5-flash-extra-low","providerId":"antigravity","weight":65},
    {"kind":"model","model":"antigravity/gemini-2.5-flash-thinking","providerId":"antigravity","weight":60},
    {"kind":"model","model":"antigravity/gemini-3.1-flash-lite","providerId":"antigravity","weight":55},
    {"kind":"model","model":"oc/big-pickle","providerId":"opencode","weight":10},
    {"kind":"model","model":"oc/mimo-v2.5-free","providerId":"opencode","weight":9},
    {"kind":"model","model":"oc/deepseek-v4-flash-free","providerId":"opencode","weight":8},
    {"kind":"model","model":"oc/hy3-free","providerId":"opencode","weight":7},
    {"kind":"model","model":"oc/nemotron-3-ultra-free","providerId":"opencode","weight":6},
    {"kind":"model","model":"oc/north-mini-code-free","providerId":"opencode","weight":5}
  ],
  "strategy": "auto",
  "config": {
    "maxRetries": 1,
    "retryDelayMs": 2000,
    "candidatePool": ["antigravity", "opencode"],
    "routerStrategy": "rules",
    "trackMetrics": true,
    "reasoningTokenBufferEnabled": true,
    "modePack": "cost-saver",
    "explorationRate": 0.05
  },
  "sortOrder": 1
}' | python3 -c "
import json, sys
d = json.load(sys.stdin)
if 'name' in d:
    print(f\"✅ Combo '{d['name']}' created with {len(d.get('models',[]))} models (id={d.get('id')})\")
else:
    print('❌ Failed:', json.dumps(d)[:300])
    sys.exit(1)
"

echo "🌱 Seed complete"
