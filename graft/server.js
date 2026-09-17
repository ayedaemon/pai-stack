import express from 'express';
import { spawn } from 'child_process';
import crypto from 'crypto';
import { createProxyMiddleware } from 'http-proxy-middleware';

const app = express();
app.use((req, res, next) => {
    console.error(`[HTTP] ${req.method} ${req.url}`);
    next();
});
app.use(express.json({ limit: '50mb' }));

// Start the graft MCP server via stdio
const workspacePath = process.env.WORKSPACE_PATH || '/opt/data/workspace';
// Store the index in the graft-cache volume, NOT in WORKSPACE_DIR
const graftIndexDir = process.env.GRAFT_INDEX_DIR || '/data/graft-index';

const graftMcpProc = spawn('npx', ['graft', 'mcp', workspacePath, '--dir', graftIndexDir], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: process.env
});

// Start the graft interactive visualizer on port 20129
const graftVizProc = spawn('npx', ['graft', 'viz', workspacePath, '--port', '20129', '--no-open', '--dir', graftIndexDir], {
    stdio: 'ignore',
    env: process.env
});

// Set up SSE clients map
const clients = new Map();

// Route for healthcheck
app.get('/health', (req, res) => {
    res.json({ status: 'ok' });
});

// SSE Endpoint for MCP stream
app.get('/mcp', (req, res) => {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');

    const sessionId = crypto.randomUUID();
    console.error(`[GET /mcp] new SSE connection, sessionId=${sessionId}`);
    
    // Send the POST endpoint for messages to the client (fully qualified URL to be safe)
    res.write(`event: endpoint\ndata: http://${req.headers.host}/mcp/message?sessionId=${sessionId}\n\n`);
    
    clients.set(sessionId, res);

    req.on('close', () => {
        clients.delete(sessionId);
    });
});

// Handle incoming JSON-RPC messages from the client
app.post('*', (req, res) => {
    const sessionId = req.query.sessionId;
    if (!sessionId || !clients.has(sessionId)) {
        return res.status(400).send('Invalid session');
    }

    const messageStr = JSON.stringify(req.body) + '\n';
    console.error(`[POST /mcp/message] req: ${messageStr.trim()}`);
    graftMcpProc.stdin.write(messageStr);
    res.status(202).end();
});

// Proxy everything else to the interactive visualizer
app.use(createProxyMiddleware({
    target: 'http://127.0.0.1:20129',
    changeOrigin: true,
    ws: true
}));

// Read responses from Graft MCP and forward them to the correct SSE client
let buffer = '';
graftMcpProc.stdout.on('data', (data) => {
    buffer += data.toString();
    const lines = buffer.split('\n');
    buffer = lines.pop(); // Keep the last incomplete line in the buffer

    for (const line of lines) {
        if (!line.trim()) continue;
        console.error(`[graft mcp out] ${line}`);
        
        // Broadcast to all connected clients (in a real implementation, you'd match by request ID if needed, 
        // but MCP clients ignore responses with unknown IDs)
        for (const [sessionId, clientRes] of clients.entries()) {
            clientRes.write(`event: message\ndata: ${line}\n\n`);
        }
    }
});

graftMcpProc.stderr.on('data', (data) => {
    console.error(`[graft mcp stderr] ${data.toString().trim()}`);
});

app.listen(20128, '0.0.0.0', () => {
    console.log('Graft MCP SSE Proxy & Visualizer listening on http://0.0.0.0:20128');
});
