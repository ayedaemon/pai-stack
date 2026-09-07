const express = require('express');
const { execSync } = require('child_process');
const app = express();
const PORT = 20128;

app.use(express.json());

function runCodeGraph(tool, args = {}) {
  const argsJson = JSON.stringify(args);
  try {
    const result = execSync(
      `codegraph-server --run-tool ${tool} --tool-args '${argsJson}' --graph-only --workspace /codebase --exclude node_modules --exclude .git --exclude __pycache__ --exclude .venv --exclude dist --exclude build 2>/dev/null`,
      { encoding: 'utf-8', timeout: 120000, maxBuffer: 10 * 1024 * 1024 }
    );
    return JSON.parse(result.trim());
  } catch (e) {
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

app.get('/map', (req, res) => {
  const result = runCodeGraph('codegraph_get_module_summary');
  res.json(result);
});

app.get('/stats', (req, res) => {
  const result = runCodeGraph('codegraph_stats');
  res.json(result);
});

app.post('/query', (req, res) => {
  const { tool, args = {} } = req.body;
  if (!tool) return res.status(400).json({ error: 'Missing "tool" in request body' });
  const result = runCodeGraph(tool, args);
  res.json(result);
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`CodeGraph API server listening on port ${PORT}`);
});
