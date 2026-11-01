// Servidor mínimo para revisar los videos: solo sirve marketing/videos/out, con soporte de rangos (iOS lo necesita).
// Uso: node tools/servir-videos.mjs [puerto]
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'out');
const PORT = Number(process.argv[2] || 8095);
const TYPES = { '.html': 'text/html; charset=utf-8', '.mp4': 'video/mp4', '.jpg': 'image/jpeg' };

http.createServer((req, res) => {
  let rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (rel === '/') rel = '/index.html';
  const file = path.join(DIR, rel);
  if (!file.startsWith(DIR + path.sep) || !TYPES[path.extname(file)] || !fs.existsSync(file)) {
    res.writeHead(404);
    return res.end('No encontrado');
  }
  const size = fs.statSync(file).size;
  const headers = { 'Content-Type': TYPES[path.extname(file)], 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store' };
  const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range || '');
  if (range) {
    const start = range[1] ? Number(range[1]) : size - Number(range[2]);
    const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    if (start >= size || start > end) { res.writeHead(416, { 'Content-Range': `bytes */${size}` }); return res.end(); }
    res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
    return fs.createReadStream(file, { start, end }).pipe(res);
  }
  res.writeHead(200, { ...headers, 'Content-Length': size });
  if (req.method === 'HEAD') return res.end();
  fs.createReadStream(file).pipe(res);
}).listen(PORT, '127.0.0.1', () => console.log(`Videos en http://127.0.0.1:${PORT}/`));
