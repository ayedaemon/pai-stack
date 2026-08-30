#!/usr/bin/env bash
# OmniRoute combo seed script — runs after server starts
# Non-fatal: if seeding fails, the server keeps running
# Usage: ./seed-combos.sh

set -uo pipefail

API_BASE="${API_BASE:-http://localhost:20128}"
PORT=20128

echo "🌱 OmniRoute combo seed starting"

# Wait for omniroute to be ready (max 60s)
echo "⏳ Waiting for OmniRoute API..."
for i in $(seq 1 12); do
  if node -e "require('net').createConnection($PORT,'localhost').on('connect',()=>process.exit(0)).on('error',()=>process.exit(1))" 2>/dev/null; then
    echo "✅ OmniRoute API ready"
    break
  fi
  if [ "$i" -eq 12 ]; then
    echo "❌ OmniRoute API not ready after 60s, skipping seed"
    exit 0
  fi
  sleep 5
done

# Upsert a combo from an inline JSON body (idempotent: delete then create)
upsert_combo () {
  local name="$1"; local body="$2"
  node -e "
const http=require('http');
const PORT=$PORT;
function del(n){return new Promise(r=>{const q=http.request({hostname:'localhost',port:PORT,path:'/api/combos/'+encodeURIComponent(n),method:'DELETE'},()=>r());q.on('error',()=>r());q.end();});}
function post(b){return new Promise(r=>{const q=http.request({hostname:'localhost',port:PORT,path:'/api/combos',method:'POST',headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(b)}},x=>{let d='';x.on('data',y=>d+=y);x.on('end',()=>r(d));});q.on('error',e=>r('ERR:'+e.message));q.write(b);q.end();});}
const data=$body;
del('$name').then(()=>post(data)).then(b=>{try{const j=JSON.parse(b);if(j.name)console.log('✅ Combo \\'' + j.name + '\\' created with ' + (j.models||[]).length + ' models');else console.log('⚠️  Response:', JSON.stringify(j).slice(0,300));}catch(e){console.log('⚠️  Could not parse response:', b.slice(0,200));}});
" 2>/dev/null || true
}

# ── 1) personal/gemini-fallback (antigravity-first, opencode fallback) ───────
GEMINI_BODY='{"name":"personal/gemini-fallback","description":"Gemini subscription (antigravity) first, free opencode fallback on exhaustion","models":[{"kind":"model","model":"antigravity/gemini-3.6-flash-high","providerId":"antigravity","weight":100},{"kind":"model","model":"antigravity/gemini-3.6-flash-medium","providerId":"antigravity","weight":95},{"kind":"model","model":"antigravity/gemini-pro-agent","providerId":"antigravity","weight":90},{"kind":"model","model":"antigravity/gemini-3.1-pro-low","providerId":"antigravity","weight":85},{"kind":"model","model":"antigravity/gemini-3-flash-agent","providerId":"antigravity","weight":80},{"kind":"model","model":"antigravity/gemini-3.6-flash-low","providerId":"antigravity","weight":75},{"kind":"model","model":"antigravity/gemini-3.5-flash-low","providerId":"antigravity","weight":70},{"kind":"model","model":"antigravity/gemini-3.5-flash-extra-low","providerId":"antigravity","weight":65},{"kind":"model","model":"antigravity/gemini-2.5-flash-thinking","providerId":"antigravity","weight":60},{"kind":"model","model":"antigravity/gemini-3.1-flash-lite","providerId":"antigravity","weight":55},{"kind":"model","model":"oc/big-pickle","providerId":"opencode","weight":10},{"kind":"model","model":"oc/mimo-v2.5-free","providerId":"opencode","weight":9},{"kind":"model","model":"oc/deepseek-v4-flash-free","providerId":"opencode","weight":8},{"kind":"model","model":"oc/hy3-free","providerId":"opencode","weight":7},{"kind":"model","model":"oc/nemotron-3-ultra-free","providerId":"opencode","weight":6},{"kind":"model","model":"oc/north-mini-code-free","providerId":"opencode","weight":5}],"strategy":"auto","config":{"maxRetries":1,"retryDelayMs":2000,"candidatePool":["antigravity","opencode"],"routerStrategy":"rules","trackMetrics":true,"reasoningTokenBufferEnabled":true,"modePack":"cost-saver","explorationRate":0.05},"sortOrder":1}'
upsert_combo "personal/gemini-fallback" "$GEMINI_BODY"

# ── 2) personal/free-chat (dynamic: all free chat LLMs, failover) ────────────
echo "🌱 Building personal/free-chat from OmniRoute's live free LLM list"
node -e "
const http=require('http');
const PORT=$PORT;
function get(){return new Promise((res,rej)=>{const r=http.get({hostname:'localhost',port:PORT,path:'/v1/models'},x=>{let b='';x.on('data',d=>b+=d);x.on('end',()=>res(b));});r.on('error',rej);});}
function del(n){return new Promise(r=>{const q=http.request({hostname:'localhost',port:PORT,path:'/api/combos/'+encodeURIComponent(n),method:'DELETE'},()=>r());q.on('error',()=>r());q.end();});}
function post(b){return new Promise(r=>{const q=http.request({hostname:'localhost',port:PORT,path:'/api/combos',method:'POST',headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(b)}},x=>{let d='';x.on('data',y=>d+=y);x.on('end',()=>r(d));});q.on('error',e=>r('ERR:'+e.message));q.write(b);q.end();});}
const NON_LLM=/flux|whisper|parakeet|fastpitch|tacotron|embedqa|rerank|asr|tts|image[_-]?gen|speech/i;
get().then(raw=>{
  const j=JSON.parse(raw);
  const list=j.data||[];
  const free=[];
  for(const m of list){
    const id=m.id||'';
    if(id.startsWith('auto/')||m.owned_by==='combo') continue;
    const isFree = m.owned_by==='opencode' || id.endsWith(':free') || (m.owned_by==='nvidia' && !NON_LLM.test(id));
    if(!isFree) continue;
    free.push({kind:'model',model:id,providerId:m.owned_by,weight: free.length===0?100:Math.max(1,100-free.length)});
  }
  const body=JSON.stringify({name:'personal/free-chat',description:'All free chat LLMs (OpenCode pool, OpenRouter :free, NVIDIA free) with failover — maximizes free-token usage',models:free,strategy:'auto',config:{maxRetries:2,retryDelayMs:2000,candidatePool:['opencode','openrouter','nvidia'],routerStrategy:'rules',trackMetrics:true,reasoningTokenBufferEnabled:true,modePack:'cost-saver',explorationRate:0.1},sortOrder:0});
  del('personal/free-chat').then(()=>post(body)).then(b=>{try{const k=JSON.parse(b);if(k.name)console.log('✅ Combo \\'personal/free-chat\\' created with '+(k.models||[]).length+' models');else console.log('⚠️  Response:',JSON.stringify(k).slice(0,300));}catch(e){console.log('⚠️  Could not parse response:',b.slice(0,200));}});
}).catch(e=>console.log('❌ Could not fetch /v1/models:',e.message));
" 2>/dev/null || true

echo "🌱 Seed complete"
