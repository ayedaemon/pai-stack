const express = require('express');
const path = require('path');
const { execSync } = require('child_process');
const app = express();
const PORT = 20128;

app.use(express.json());
app.use('/viz', express.static(path.join(__dirname, 'viz')));

function runCodeGraph(tool, args = {}) {
  const argsJson = JSON.stringify(args);
  const started = Date.now();
  console.log(`[codegraph] start tool=${tool} args=${argsJson.slice(0, 200)}`);
  try {
    const result = execSync(
      `codegraph-server --run-tool ${tool} --tool-args '${argsJson}' --graph-only --workspace /stack_root --exclude node_modules --exclude .git --exclude __pycache__ --exclude .venv --exclude dist --exclude build`,
      { encoding: 'utf-8', timeout: 120000, maxBuffer: 10 * 1024 * 1024 }
    );
    console.log(`[codegraph] done tool=${tool} took=${Date.now() - started}ms bytes=${result.length}`);
    return JSON.parse(result.trim());
  } catch (e) {
    console.log(`[codegraph] FAIL tool=${tool} took=${Date.now() - started}ms err=${String(e.message).slice(0, 300)}`);
    return { error: e.message, stdout: e.stdout?.slice(0, 500) };
  }
}

app.get('/health', (req, res) => {
  // lightweight liveness — don't run heavy graph tool here (previous codegraph_stats is unknown and ETIMEDOUT on RPi)
  res.json({ status: 'ok' });
});

app.get('/context/:symbol', (req, res) => {
  const result = runCodeGraph('codegraph_get_ai_context', { symbol: req.params.symbol });
  res.json(result);
});

app.get('/callers/:symbol', (req, res) => {
  const result = runCodeGraph('codegraph_get_callers', { symbol: req.params.symbol });
  res.json(result);
});

app.get('/callees/:symbol', (req, res) => {
  const result = runCodeGraph('codegraph_get_callees', { symbol: req.params.symbol });
  res.json(result);
});

app.get('/impact/:path(*)', (req, res) => {
  const result = runCodeGraph('codegraph_analyze_impact', { filePath: req.params.path });
  res.json(result);
});

app.get('/search', (req, res) => {
  const query = req.query.q;
  if (!query) return res.status(400).json({ error: 'Missing ?q= query parameter' });
  const result = runCodeGraph('codegraph_symbol_search', { query });
  res.json(result);
});

// Trimmed symbol list for the viz picker — same verified search tool,
// shaped into small clickable rows.
app.get('/symbols', (req, res) => {
  const query = req.query.q || req.query.prefix || '';
  if (query.length < 2) return res.status(400).json({ error: 'Pass ?q= with at least 2 characters' });
  const limit = Math.min(parseInt(req.query.limit || '30', 10) || 30, 100);
  const started = Date.now();
  const result = runCodeGraph('codegraph_symbol_search', { query });
  const raw = Array.isArray(result) ? result : (result.results || result.symbols || []);
  const items = (Array.isArray(raw) ? raw : []).slice(0, limit).map((r) => ({
    id: String(r.node_id ?? r.nodeId ?? r.id ?? ''),
    name: r.symbol?.name ?? r.name ?? '',
    kind: r.symbol?.kind ?? r.kind ?? '',
    file: (r.symbol?.location?.file ?? r.location?.file ?? r.file ?? '').replace('/stack_root/', '').replace('/codebase/', ''),
    score: r.score ?? null,
  })).filter((x) => x.name);
  console.log(`[symbols] q=${query} returned=${items.length} took=${Date.now() - started}ms`);
  res.json({ query, count: items.length, items });
});

app.get('/map', (req, res) => {
  const result = runCodeGraph('codegraph_get_module_summary');
  res.json(result);
});

app.get('/stats', (req, res) => {
  const result = runCodeGraph('codegraph_memory_stats');
  res.json(result);
});

app.post('/query', (req, res) => {
  const { tool, args = {} } = req.body;
  if (!tool) return res.status(400).json({ error: 'Missing "tool" in request body' });
  const result = runCodeGraph(tool, args);
  res.json(result);
});

// Scoped neighborhood explorer for quick browsing — aggregates callers/callees
// into D3-ready {nodes, edges}, capped so the browser never chokes.
app.get('/neighborhood/:symbol', (req, res) => {
  const symbol = req.params.symbol;
  const depth = Math.min(parseInt(req.query.depth || '1', 10) || 1, 2);
  const MAX_NODES = 300;
  const t0 = Date.now();
  console.log(`[neighborhood] start symbol=${symbol} depth=${depth}`);

  const nodes = new Map(); // id -> {id,label,kind,file}
  const edges = [];
  const seenEdges = new Set();

  const symId = (s) => String(s.node_id ?? s.nodeId ?? s.id ?? s.symbol?.name ?? s.name ?? JSON.stringify(s).slice(0, 60));
  const symLabel = (s) => s.symbol?.name ?? s.name ?? symId(s);
  const symKind = (s) => s.symbol?.kind ?? s.kind ?? 'Unknown';
  const symFile = (s) => s.symbol?.location?.file ?? s.location?.file ?? s.file ?? '';

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
  // codegraph tool responses vary in shape — collect symbol-like entries defensively
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

  // Resolve center via search (first SymbolName match wins, else first result)
  const searchRes = runCodeGraph('codegraph_symbol_search', { query: symbol });
  const candidates = collect(searchRes);
  if (!candidates.length) return res.json({ center: symbol, nodes: [], edges: [], note: 'no matches — try GET /search?q= first' });
  const centerRaw = candidates.find((c) => c.match_reason === 'SymbolName') || candidates[0];
  const centerId = addNode(centerRaw);
  const centerName = symLabel(centerRaw);

  function expand(name, hop) {
    if (nodes.size >= MAX_NODES) return;
    const callers = collect(runCodeGraph('codegraph_get_callers', { symbol: name }));
    const callees = collect(runCodeGraph('codegraph_get_callees', { symbol: name }));
    console.log(`[neighborhood] hop=${hop} name=${name} callers=${callers.length} callees=${callees.length} nodes=${nodes.size} elapsed=${Date.now() - t0}ms`);
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

  console.log(`[neighborhood] finish center=${centerName} nodes=${nodes.size} edges=${edges.length} total=${Date.now() - t0}ms`);
  res.json({ center: centerName, centerId, nodes: [...nodes.values()], edges, truncated: nodes.size >= MAX_NODES });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`CodeGraph API server listening on port ${PORT}`);
});
