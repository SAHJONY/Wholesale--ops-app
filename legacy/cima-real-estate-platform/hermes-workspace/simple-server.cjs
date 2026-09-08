import http from 'http';
import fs from 'fs';
import path from 'path';

const PORT = process.env.PORT || 3000;

// Simple static file server for the Hermes Workspace
const server = http.createServer((req, res) => {
  // Set CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  
  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }
  
  // Simple routing
  if (req.url === '/' || req.url === '/index.html') {
    // Serve basic landing page
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(`
      <!DOCTYPE html>
      <html>
        <head>
          <title>Hermes Workspace - Operational Command Center</title>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body>
          <div id="root">
            <h1>Hermes Workspace Operational Command Center</h1>
            <p>Real-time AI-powered business management platform</p>
            <p>Status: Development environment ready - Vite server configured</p>
            <p>API Endpoints: HERMES_API_URL=${process.env.HERMES_API_URL || 'http://127.0.0.1:8642'}</p>
            <p>Dashboard URL: HERMES_DASHBOARD_URL=${process.env.HERMES_DASHBOARD_URL || 'http://127.0.0.1:9119'}</p>
            <p>Port: ${PORT}</p>
          </div>
        </body>
      </html>
    `);
  } else if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', timestamp: new Date().toISOString() }));
  } else {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Hermes Workspace Operational Command Center running on http://0.0.0.0:${PORT}`);
  console.log(`Health check available at http://0.0.0.0:${PORT}/health`);
});