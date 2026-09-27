#!/usr/bin/env node
// Tiny dependency-free static file server for dist/ (local testing only, binds 127.0.0.1).
// Usage: node tools/serve.mjs [--port 8080] [--root dist] [--host 127.0.0.1]
// Without --port (and without PORT in the environment) the OS picks a free port.

import http from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.htm': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.glb': 'model/gltf-binary',
  '.gltf': 'model/gltf+json',
  '.bin': 'application/octet-stream',
  '.wasm': 'application/wasm',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.avif': 'image/avif',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.ktx2': 'image/ktx2',
  '.hdr': 'application/octet-stream',
  '.mp3': 'audio/mpeg',
  '.ogg': 'audio/ogg',
  '.wav': 'audio/wav',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

export function contentType(file) {
  return MIME[path.extname(file).toLowerCase()] || 'application/octet-stream';
}

/**
 * Starts the server. Resolves with { server, port, url, close }.
 * @param {{root?:string, port?:number, host?:string, quiet?:boolean}} opts
 */
export function startServer({ root, port = 0, host = '127.0.0.1', quiet = true } = {}) {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const base = path.resolve(root || path.join(here, '..', 'dist'));
  const server = http.createServer(async (req, res) => {
    try {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.writeHead(405, { Allow: 'GET, HEAD' });
        res.end();
        return;
      }
      const url = new URL(req.url, 'http://localhost');
      let rel = decodeURIComponent(url.pathname);
      if (rel.includes('\0')) throw new Error('bad path');
      let file = path.resolve(base, '.' + rel);
      if (file !== base && !file.startsWith(base + path.sep)) {
        res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('Forbidden');
        return;
      }
      let st = await stat(file).catch(() => null);
      if (st && st.isDirectory()) {
        file = path.join(file, 'index.html');
        st = await stat(file).catch(() => null);
      }
      if (!st || !st.isFile()) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('Not found');
        if (!quiet) console.log(`404 ${rel}`);
        return;
      }
      res.writeHead(200, {
        'Content-Type': contentType(file),
        'Content-Length': st.size,
        'Cache-Control': 'no-cache',
        'X-Content-Type-Options': 'nosniff',
      });
      if (req.method === 'HEAD') {
        res.end();
        return;
      }
      createReadStream(file).pipe(res);
      if (!quiet) console.log(`200 ${rel}`);
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Server error');
      if (!quiet) console.error(err);
    }
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      const actual = server.address().port;
      resolve({
        server,
        port: actual,
        url: `http://${host}:${actual}/`,
        close: () => new Promise((r) => server.close(() => r())),
      });
    });
  });
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const args = process.argv.slice(2);
  const opt = (name) => {
    const i = args.indexOf(`--${name}`);
    return i >= 0 ? args[i + 1] : undefined;
  };
  const port = Number(opt('port') ?? process.env.PORT ?? 0);
  const root = opt('root');
  const host = opt('host') ?? '127.0.0.1';
  startServer({ root, port, host, quiet: !args.includes('--verbose') })
    .then(({ url }) => {
      console.log(`Iron Valley běží na ${url}  (Ctrl+C ukončí)`);
    })
    .catch((err) => {
      console.error(`Server se nepodařilo spustit: ${err.message}`);
      process.exit(1);
    });
}
