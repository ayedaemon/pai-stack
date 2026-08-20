#!/usr/bin/env bash
# OmniRoute combo seed script — runs after server starts
# Non-fatal: if seeding fails, the server keeps running
# Usage: ./seed-combos.sh

set -uo pipefail

API_BASE="${API_BASE:-http://localhost:20128}"
COMBO_NAME="personal/gemini-fallback"

echo "🌱 Seeding OmniRoute combo: $COMBO_NAME"

# Wait for omniroute to be ready (max 60s)
echo "⏳ Waiting for OmniRoute API..."
for i in $(seq 1 12); do
  if node -e "require('net').createConnection(20128,'localhost').on('connect',()=>process.exit(0)).on('error',()=>process.exit(1))" 2>/dev/null; then
    echo "✅ OmniRoute API ready"
    break
  fi
  if [ "$i" -eq 12 ]; then
    echo "❌ OmniRoute API not ready after 60s, skipping seed"
    exit 0
  fi
  sleep 5
done

# Delete existing combo if present (idempotent)
node -e "
const http = require('http');
const req = http.request({hostname:'localhost',port:20128,path:'/api/combos/$COMBO_NAME',method:'DELETE'},()=>process.exit(0));
req.on('error',()=>process.exit(0));
req.end();
" 2>/dev/null || true

# Create the combo
node -e "
const http = require('http');
const data = JSON.stringify({
  name: '$COMBO_NAME',
  description: 'Gemini subscription (antigravity) first, free opencode fallback on exhaustion',
  models: [
    {kind:'model',model:'antigravity/gemini-3.6-flash-high',providerId:'antigravity',weight:100},
    {kind:'model',model:'antigravity/gemini-3.6-flash-medium',providerId:'antigravity',weight:95},
    {kind:'model',model:'antigravity/gemini-pro-agent',providerId:'antigravity',weight:90},
    {kind:'model',model:'antigravity/gemini-3.1-pro-low',providerId:'antigravity',weight:85},
    {kind:'model',model:'antigravity/gemini-3-flash-agent',providerId:'antigravity',weight:80},
    {kind:'model',model:'antigravity/gemini-3.6-flash-low',providerId:'antigravity',weight:75},
    {kind:'model',model:'antigravity/gemini-3.5-flash-low',providerId:'antigravity',weight:70},
    {kind:'model',model:'antigravity/gemini-3.5-flash-extra-low',providerId:'antigravity',weight:65},
    {kind:'model',model:'antigravity/gemini-2.5-flash-thinking',providerId:'antigravity',weight:60},
    {kind:'model',model:'antigravity/gemini-3.1-flash-lite',providerId:'antigravity',weight:55},
    {kind:'model',model:'oc/big-pickle',providerId:'opencode',weight:10},
    {kind:'model',model:'oc/mimo-v2.5-free',providerId:'opencode',weight:9},
    {kind:'model',model:'oc/deepseek-v4-flash-free',providerId:'opencode',weight:8},
    {kind:'model',model:'oc/hy3-free',providerId:'opencode',weight:7},
    {kind:'model',model:'oc/nemotron-3-ultra-free',providerId:'opencode',weight:6},
    {kind:'model',model:'oc/north-mini-code-free',providerId:'opencode',weight:5}
  ],
  strategy: 'auto',
  config: {
    maxRetries: 1,
    retryDelayMs: 2000,
    candidatePool: ['antigravity', 'opencode'],
    routerStrategy: 'rules',
    trackMetrics: true,
    reasoningTokenBufferEnabled: true,
    modePack: 'cost-saver',
    explorationRate: 0.05
  },
  sortOrder: 1
});
const req = http.request({hostname:'localhost',port:20128,path:'/api/combos',method:'POST',headers:{'Content-Type':'application/json','Content-Length':data.length}},res=>{
  let body='';
  res.on('data',d=>body+=d);
  res.on('end',()=>{
    try{
      const j=JSON.parse(body);
      if(j.name) console.log('✅ Combo \\'' + j.name + '\\' created with ' + (j.models||[]).length + ' models (id=' + j.id + ')');
      else console.log('⚠️  Response:', JSON.stringify(j).slice(0,300));
    }catch(e){ console.log('⚠️  Could not parse response'); }
  });
});
req.on('error',e=>console.log('❌ Request failed:', e.message));
req.write(data);
req.end();
" 2>/dev/null || true

echo "🌱 Seed complete"
