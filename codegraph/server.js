const express = require('express');
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const app = express();
const PORT = 20128;
const WORKSPACE = path.normalize(process.env.WORKSPACE_PATH || '/opt/data/workspace');
const EMBEDDINGS_URL = process.env.EMBEDDINGS_URL || 'http://embeddings:8080/v1';
const VECTOR_CACHE_FILE = '/data/vector_cache.json';

app.use(express.json());
app.use('/viz', express.static(path.join(__dirname, 'viz')));

function toRelativePath(filePath) {
  if (!filePath) return '';
  const prefix = WORKSPACE.endsWith('/') ? WORKSPACE : `${WORKSPACE}/`;
  if (filePath.startsWith(prefix)) {
    return filePath.slice(prefix.length);
  }
  return filePath.replace(/^\/opt\/data\/workspace\/?/, '')
                 .replace(/^\/workspace\/?/, '')
                 .replace(/^\/opt\/hermes\/data\/workspace\/?/, '')
                 .replace(/^\/opt\/data\/?/, '')
                 .replace(/^\/stack_root\/?/, '')
                 .replace(/^\/codebase\/?/, '');
}

function runCodeGraph(tool, args = {}) {
  const argsJson = JSON.stringify(args);
  const started = Date.now();
  console.log(`[codegraph] start tool=${tool} args=${argsJson.slice(0, 200)}`);
  try {
    const result = execSync(
      `codegraph-server --run-tool ${tool} --tool-args '${argsJson}' --graph-only --workspace ${WORKSPACE} --exclude node_modules --exclude .git --exclude __pycache__ --exclude .venv --exclude dist --exclude build`,
      { encoding: 'utf-8', timeout: 120000, maxBuffer: 10 * 1024 * 1024 }
    );
    console.log(`[codegraph] done tool=${tool} took=${Date.now() - started}ms bytes=${result.length}`);
    return JSON.parse(result.trim());
  } catch (e) {
    console.log(`[codegraph] FAIL tool=${tool} took=${Date.now() - started}ms err=${String(e.message).slice(0, 300)}`);
    return { error: e.message, stdout: e.stdout?.slice(0, 500) };
  }
}

// ── Full-Text Lexical Search (ripgrep) ─────────────────────────────────────────
function runRipgrep(query, limit = 30) {
  const started = Date.now();
  // Escape single quotes for shell safety
  const safeQuery = query.replace(/'/g, "'\\''");
  const cmd = `rg --json --max-count ${limit} -i -e '${safeQuery}' ${WORKSPACE} ` +
              `--glob '!node_modules/**' --glob '!.git/**' --glob '!__pycache__/**' ` +
              `--glob '!.venv/**' --glob '!dist/**' --glob '!build/**' ` +
              `--glob '!*.db*' --glob '!*.lock'`;
  try {
    const stdout = execSync(cmd, { encoding: 'utf-8', timeout: 30000, maxBuffer: 10 * 1024 * 1024 });
    const lines = stdout.trim().split('\n').filter(Boolean);
    const results = [];

    for (const line of lines) {
      if (results.length >= limit) break;
      try {
        const item = JSON.parse(line);
        if (item.type === 'match') {
          const matchData = item.data;
          const rawFile = matchData.path?.text || '';
          const lineNum = matchData.line_number || null;
          const snippet = (matchData.lines?.text || '').trim();
          results.push({
            name: null,
            kind: 'text',
            file: toRelativePath(rawFile),
            line: lineNum,
            snippet: snippet.length > 200 ? snippet.slice(0, 200) + '...' : snippet,
            matchType: 'text',
            score: 0.8,
          });
        }
      } catch (_) {
        // Skip malformed JSON lines
      }
    }
    console.log(`[ripgrep] q="${query}" returned=${results.length} took=${Date.now() - started}ms`);
    return results;
  } catch (e) {
    // ripgrep exit code 1 means "no matches found", which is not a server error
    if (e.status === 1) return [];
    console.log(`[ripgrep] error q="${query}": ${e.message}`);
    return [];
  }
}

// ── AST Symbol Search ─────────────────────────────────────────────────────────
function extractCodeContext(rawFile, startLine, endLine) {
  if (!rawFile) return '';
  try {
    let absPath = rawFile;
    if (!absPath.startsWith('/')) {
      absPath = path.join(WORKSPACE, absPath);
    }
    if (!fs.existsSync(absPath)) return '';
    const stat = fs.statSync(absPath);
    if (stat.size > 2 * 1024 * 1024) return ''; // Skip files > 2MB

    const content = fs.readFileSync(absPath, 'utf-8');
    const lines = content.split('\n');

    if (!startLine || startLine < 1) {
      return lines.slice(0, 20).join('\n').trim();
    }

    const zeroStart = startLine - 1;
    // Look back up to 10 lines, but only include lines if they are comments, docstrings, decorators, or empty
    let lookbackStart = zeroStart;
    for (let i = zeroStart - 1; i >= Math.max(0, zeroStart - 10); i--) {
      const lineTrim = lines[i].trim();
      if (lineTrim === '' ||
          lineTrim.startsWith('//') ||
          lineTrim.startsWith('/*') ||
          lineTrim.startsWith('*') ||
          lineTrim.startsWith('#') ||
          lineTrim.startsWith('@') ||
          lineTrim.startsWith('///')) {
        lookbackStart = i;
      } else {
        // Hit previous code block -> stop looking back
        break;
      }
    }

    // Look forward up to endLine or 35 lines to capture signature, docstring, and implementation
    const forwardEnd = endLine ? Math.min(endLine, zeroStart + 35) : Math.min(lines.length, zeroStart + 25);

    return lines.slice(lookbackStart, forwardEnd).join('\n').trim();
  } catch (_) {
    return '';
  }
}

function runSymbolSearch(query, limit = 30) {
  const result = runCodeGraph('codegraph_symbol_search', { query });
  const raw = Array.isArray(result) ? result : (result.results || result.symbols || []);
  return (Array.isArray(raw) ? raw : []).slice(0, limit).map((r) => {
    const loc = r.symbol?.location || r.location || {};
    const line = loc.line ?? loc.range?.start?.line ?? r.line ?? null;
    const endLine = loc.end_line ?? loc.range?.end?.line ?? null;
    const rawFile = loc.file ?? r.file ?? '';
    const file = toRelativePath(rawFile);
    return {
      id: String(r.node_id ?? r.nodeId ?? r.id ?? ''),
      name: r.symbol?.name ?? r.name ?? '',
      kind: r.symbol?.kind ?? r.kind ?? 'Symbol',
      file,
      rawFile,
      line,
      endLine,
      signature: r.symbol?.signature ?? null,
      docstring: r.symbol?.docstring ?? null,
      snippet: r.symbol?.detail || r.match_reason || null,
      matchType: 'symbol',
      score: r.score ?? 1.0,
    };
  }).filter((x) => x.name);
}

// ── Vector Search & Embeddings Integration ────────────────────────────────────
let vectorCache = new Map();

function loadVectorCache() {
  try {
    if (fs.existsSync(VECTOR_CACHE_FILE)) {
      const data = JSON.parse(fs.readFileSync(VECTOR_CACHE_FILE, 'utf-8'));
      vectorCache = new Map(Object.entries(data));
      console.log(`[embeddings] loaded ${vectorCache.size} cached vector(s)`);
    }
  } catch (e) {
    console.log(`[embeddings] could not load cache: ${e.message}`);
  }
}

function saveVectorCache() {
  try {
    const dir = path.dirname(VECTOR_CACHE_FILE);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    const obj = Object.fromEntries(vectorCache);
    fs.writeFileSync(VECTOR_CACHE_FILE, JSON.stringify(obj), 'utf-8');
  } catch (e) {
    console.log(`[embeddings] could not save cache: ${e.message}`);
  }
}

async function fetchEmbedding(text, prefix = 'search_query: ') {
  try {
    const res = await fetch(`${EMBEDDINGS_URL}/embeddings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: `${prefix}${text}` })
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.data?.[0]?.embedding || null;
  } catch (e) {
    return null;
  }
}

function cosineSimilarity(a, b) {
  let dot = 0.0, normA = 0.0, normB = 0.0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  if (normA === 0 || normB === 0) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

async function indexSymbolsForSemanticSearch(symbols) {
  let newIndexed = 0;
  for (const s of symbols) {
    const id = `${s.file}:${s.line}:${s.name}`;
    if (!vectorCache.has(id)) {
      const codeContext = extractCodeContext(s.rawFile || s.file, s.line, s.endLine);

      let textToEmbed = `${s.kind || 'Symbol'} ${s.name} in ${s.file}`;
      if (s.signature) textToEmbed += `\nSignature: ${s.signature}`;
      if (s.docstring) textToEmbed += `\nDocstring: ${s.docstring}`;
      if (codeContext) textToEmbed += `\nContext:\n${codeContext}`;

      const vec = await fetchEmbedding(textToEmbed, 'search_document: ');
      if (vec) {
        // Build clean snippet: prefer docstring, then first comment line, then signature
        let cleanSnippet = s.docstring ? s.docstring.slice(0, 200).replace(/\s+/g, ' ').trim() : null;
        if (!cleanSnippet && codeContext) {
          const commentLine = codeContext.split('\n').find((l) => {
            const t = l.trim();
            return t.startsWith('//') || t.startsWith('#') || t.startsWith('*') || t.startsWith('"""') || t.startsWith("'''");
          });
          if (commentLine) {
            cleanSnippet = commentLine.trim().replace(/^(\/\/|\*|#|\/\*+|"{3}|'{3})\s*/, '').slice(0, 150);
          } else {
            cleanSnippet = s.signature || codeContext.split('\n')[0].trim().slice(0, 150);
          }
        }

        vectorCache.set(id, {
          ...s,
          snippet: cleanSnippet || s.snippet,
          vector: vec,
        });
        newIndexed++;
      }
    }
  }
  if (newIndexed > 0) {
    saveVectorCache();
    console.log(`[embeddings] indexed ${newIndexed} new symbol(s) with rich context, total=${vectorCache.size}`);
  }
}

async function runSemanticSearch(query, limit = 30) {
  const queryVec = await fetchEmbedding(query, 'search_query: ');
  if (!queryVec) return [];

  const matches = [];
  for (const item of vectorCache.values()) {
    if (item.vector) {
      const score = cosineSimilarity(queryVec, item.vector);
      if (score > 0.40) {
        matches.push({
          id: item.id,
          name: item.name,
          kind: item.kind,
          file: item.file,
          line: item.line,
          snippet: item.snippet,
          matchType: 'semantic',
          score: Math.round(score * 100) / 100,
        });
      }
    }
  }

  matches.sort((a, b) => b.score - a.score);
  return matches.slice(0, limit);
}

// ── Neighborhood Builder Helper ───────────────────────────────────────────────
function buildNeighborhood(symbol, depth = 1) {
  const MAX_NODES = 300;
  const nodes = new Map();
  const edges = [];
  const seenEdges = new Set();

  const symId = (s) => String(s.node_id ?? s.nodeId ?? s.id ?? s.symbol?.name ?? s.name ?? JSON.stringify(s).slice(0, 60));
  const symLabel = (s) => s.symbol?.name ?? s.name ?? symId(s);
  const symKind = (s) => s.symbol?.kind ?? s.kind ?? 'Unknown';
  const symFile = (s) => toRelativePath(s.symbol?.location?.file ?? s.location?.file ?? s.file ?? '');

  function addNode(s) {
    const id = symId(s);
    if (!nodes.has(id) && nodes.size < MAX_NODES) {
      nodes.set(id, { id, label: symLabel(s), kind: symKind(s), file: symFile(s) });
    }
    return id;
  }
  function addEdge(a, b, kind) {
    const key = a + '>' + b + ':' + kind;
    if (!seenEdges.has(key) && nodes.has(a) && nodes.has(b)) {
      seenEdges.add(key);
      edges.push({ source: a, target: b, kind });
    }
  }
  function collect(result) {
    if (!result || result.error) return [];
    const out = [];
    const push = (x) => { if (x && typeof x === 'object') out.push(x); };
    if (Array.isArray(result)) result.forEach(push);
    else {
      ['results', 'symbols', 'callers', 'callees', 'nodes', 'data'].forEach((k) => {
        if (Array.isArray(result[k])) result[k].forEach(push);
      });
    }
    return out;
  }

  const searchRes = runCodeGraph('codegraph_symbol_search', { query: symbol });
  const candidates = collect(searchRes);
  if (!candidates.length) return { center: symbol, nodes: [], edges: [], note: 'no matches' };
  const centerRaw = candidates.find((c) => c.match_reason === 'SymbolName') || candidates[0];
  const centerId = addNode(centerRaw);
  const centerName = symLabel(centerRaw);

  function expand(name, hop) {
    if (nodes.size >= MAX_NODES) return;
    const callers = collect(runCodeGraph('codegraph_get_callers', { symbol: name }));
    const callees = collect(runCodeGraph('codegraph_get_callees', { symbol: name }));
    const selfId = [...nodes.values()].find((n) => n.label === name)?.id;
    if (!selfId) return;
    callers.slice(0, 50).forEach((c) => {
      const id = addNode(c);
      if (nodes.has(id)) addEdge(id, selfId, 'calls');
    });
    callees.slice(0, 50).forEach((c) => {
      const id = addNode(c);
      if (nodes.has(id)) addEdge(selfId, id, 'calls');
    });
    if (hop < depth) {
      const frontier = [...callers.slice(0, 10), ...callees.slice(0, 10)];
      frontier.forEach((c) => {
        if (nodes.size < MAX_NODES) expand(symLabel(c), hop + 1);
      });
    }
  }
  expand(centerName, 1);
  return { center: centerName, centerId, nodes: [...nodes.values()], edges, truncated: nodes.size >= MAX_NODES };
}

// ==============================================================================
// ── CANONICAL API ENDPOINTS ───────────────────────────────────────────────────
// ==============================================================================

// Liveness check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', workspace: WORKSPACE });
});

// 1. Unified Multi-Modal Search
// GET /search?q=...&type=hybrid|symbol|text|semantic&limit=30
app.get('/search', async (req, res) => {
  const query = (req.query.q || req.query.query || '').trim();
  if (!query || query.length < 2) {
    return res.status(400).json({ error: 'Query (?q=) must be at least 2 characters' });
  }

  const type = (req.query.type || 'hybrid').toLowerCase();
  const limit = Math.min(parseInt(req.query.limit || '30', 10) || 30, 100);
  const started = Date.now();

  let results = [];

  if (type === 'symbol') {
    results = runSymbolSearch(query, limit);
    indexSymbolsForSemanticSearch(results).catch(() => {});
  } else if (type === 'text') {
    results = runRipgrep(query, limit);
  } else if (type === 'semantic') {
    results = await runSemanticSearch(query, limit);
  } else {
    // Default: 'hybrid' (combines AST symbols, semantic vectors, and ripgrep text matches)
    const symbols = runSymbolSearch(query, limit);
    indexSymbolsForSemanticSearch(symbols).catch(() => {});
    const textMatches = runRipgrep(query, limit);
    const semanticMatches = await runSemanticSearch(query, limit);

    // Merge & deduplicate by file:line
    const seen = new Set();
    symbols.forEach((s) => {
      seen.add(`${s.file}:${s.line}:${s.name}`);
      results.push(s);
    });

    semanticMatches.forEach((m) => {
      const key = `${m.file}:${m.line}:${m.name}`;
      if (!seen.has(key)) {
        seen.add(key);
        results.push(m);
      }
    });

    textMatches.forEach((t) => {
      const key = `${t.file}:${t.line}:${t.name}`;
      if (!seen.has(key)) {
        seen.add(key);
        results.push(t);
      }
    });

    // Rank: symbol exact matches first, then semantic matches, then text matches
    results.sort((a, b) => (b.score || 0) - (a.score || 0));
    results = results.slice(0, limit);
  }

  console.log(`[search] q="${query}" type=${type} returned=${results.length} took=${Date.now() - started}ms`);
  res.json({
    query,
    type,
    count: results.length,
    tookMs: Date.now() - started,
    items: results,
  });
});

// 2. Full Symbol Intelligence
// GET /symbols/:name?view=all|context|callers|callees|graph&depth=1|2
app.get('/symbols/:name', (req, res) => {
  const name = req.params.name;
  const view = (req.query.view || 'all').toLowerCase();
  const depth = Math.min(parseInt(req.query.depth || '1', 10) || 1, 2);

  if (view === 'context') {
    return res.json(runCodeGraph('codegraph_get_ai_context', { symbol: name }));
  }
  if (view === 'callers') {
    return res.json(runCodeGraph('codegraph_get_callers', { symbol: name }));
  }
  if (view === 'callees') {
    return res.json(runCodeGraph('codegraph_get_callees', { symbol: name }));
  }
  if (view === 'graph') {
    return res.json(buildNeighborhood(name, depth));
  }

  // view === 'all': Consolidated symbol intelligence
  const context = runCodeGraph('codegraph_get_ai_context', { symbol: name });
  const callers = runCodeGraph('codegraph_get_callers', { symbol: name });
  const callees = runCodeGraph('codegraph_get_callees', { symbol: name });
  const graph = buildNeighborhood(name, depth);

  res.json({
    symbol: name,
    context,
    callers,
    callees,
    graph,
  });
});

// 3. Blast Radius / Impact Analysis
// GET /impact/:path(*)
app.get('/impact/:path(*)', (req, res) => {
  let filePath = req.params.path;
  if (!filePath.startsWith('/') && !filePath.startsWith(WORKSPACE)) {
    filePath = path.join(WORKSPACE, filePath);
  }
  const result = runCodeGraph('codegraph_analyze_impact', { filePath });
  res.json(result);
});

// 4. Module Architecture Summary
// GET /map
app.get('/map', (req, res) => {
  const result = runCodeGraph('codegraph_get_module_summary');
  res.json(result);
});

// 5. Explicit Reindex Trigger
// POST /reindex
app.post('/reindex', (req, res) => {
  console.log(`[codegraph] workspace reindex requested`);
  if (req.query.clear_cache === 'true' || req.body?.clear_cache) {
    vectorCache.clear();
    saveVectorCache();
    console.log(`[embeddings] vector cache cleared on reindex`);
  }
  const result = runCodeGraph('codegraph_reindex_workspace', req.body || {});
  res.json({ status: 'ok', vectorCacheSize: vectorCache.size, result });
});

// Cache management
app.post('/cache/clear', (req, res) => {
  vectorCache.clear();
  saveVectorCache();
  console.log(`[embeddings] vector cache cleared via /cache/clear`);
  res.json({ status: 'ok', message: 'Vector cache cleared', vectorCacheSize: 0 });
});

// 6. Memory Stats & Diagnostics
// GET /stats
app.get('/stats', (req, res) => {
  const result = runCodeGraph('codegraph_memory_stats');
  res.json({ workspace: WORKSPACE, stats: result });
});

// ==============================================================================
// ── BACKWARD-COMPATIBILITY ALIASES ────────────────────────────────────────────
// ==============================================================================

// /symbols?q=... -> alias to /search?type=symbol (used by viz typeahead)
app.get('/symbols', (req, res) => {
  const query = req.query.q || req.query.prefix || '';
  if (query.length < 2) return res.status(400).json({ error: 'Pass ?q= with at least 2 characters' });
  const limit = Math.min(parseInt(req.query.limit || '30', 10) || 30, 100);
  const items = runSymbolSearch(query, limit);
  res.json({ query, count: items.length, items });
});

// Legacy /context/:symbol
app.get('/context/:symbol', (req, res) => {
  res.json(runCodeGraph('codegraph_get_ai_context', { symbol: req.params.symbol }));
});

// Legacy /callers/:symbol
app.get('/callers/:symbol', (req, res) => {
  res.json(runCodeGraph('codegraph_get_callers', { symbol: req.params.symbol }));
});

// Legacy /callees/:symbol
app.get('/callees/:symbol', (req, res) => {
  res.json(runCodeGraph('codegraph_get_callees', { symbol: req.params.symbol }));
});

// Legacy /neighborhood/:symbol
app.get('/neighborhood/:symbol', (req, res) => {
  const depth = Math.min(parseInt(req.query.depth || '1', 10) || 1, 2);
  res.json(buildNeighborhood(req.params.symbol, depth));
});

// Legacy generic /query (used by fs-notifier.sh)
app.post('/query', (req, res) => {
  const { tool, args = {} } = req.body;
  if (!tool) return res.status(400).json({ error: 'Missing "tool" in request body' });
  const result = runCodeGraph(tool, args);
  res.json(result);
});

loadVectorCache();

app.listen(PORT, '0.0.0.0', () => {
  console.log(`CodeGraph API server listening on port ${PORT} (workspace: ${WORKSPACE}, embeddings: ${EMBEDDINGS_URL})`);
});
