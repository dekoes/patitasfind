// Renderiza los videos de GuauWoow cuadro por cuadro (Playwright + ffmpeg).
// Uso:
//   node tools/render.mjs adopcion                      -> out/guauwoow-adopcion.mp4 (60 s, 30 fps)
//   node tools/render.mjs perdido --from 10 --to 20     -> solo un tramo
//   node tools/render.mjs adopcion --stills 1,5.5,12    -> PNG de esos segundos en build/stills/
//   node tools/render.mjs instagram                     -> out/guauwoow-instagram-30s.mp4 (30 s)
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.resolve(ROOT, '../../app/package.json'));
const { chromium } = require('playwright');

const args = process.argv.slice(2);
const video = args[0] || 'adopcion';
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const FPS = Number(opt('fps', 30));
const from = Number(opt('from', 0));
// duración y nombre de salida por video (los de 60 s usan los valores por omisión)
const DUR = { instagram: 30 }[video] || 60;
const NOMBRE = { instagram: 'guauwoow-instagram-30s' }[video] || `guauwoow-${video}`;
const to = Number(opt('to', DUR));
const stills = opt('stills', null);

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
page.on('pageerror', e => console.error('ERROR EN PÁGINA:', e.message));
await page.goto(`http://127.0.0.1:${port}/build/video.html?v=${video}`);
await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });

if (args.includes('--cues')) {
  // Marcas de sonido (tiempo, tipo, posición) para tools/sonido.py
  const cues = await page.evaluate(() => window.PF.cues.slice().sort((a, b) => a.t - b.t));
  const out = path.join(ROOT, 'build', `cues-${video}.json`);
  fs.writeFileSync(out, JSON.stringify(cues, null, 1));
  console.log(`${cues.length} marcas en ${out}`);
} else if (stills) {
  const dir = path.join(ROOT, 'build', 'stills');
  fs.mkdirSync(dir, { recursive: true });
  for (const s of stills.split(',').map(Number)) {
    await page.evaluate(t => window.renderFrame(t), s);
    await page.screenshot({ path: path.join(dir, `${video}-${String(s.toFixed(2)).padStart(5, '0')}.png`) });
  }
  console.log('fotogramas en', dir);
} else {
  fs.mkdirSync(path.join(ROOT, 'out'), { recursive: true });
  const out = path.join(ROOT, 'out', from === 0 && to === DUR ? `${NOMBRE}.mp4` : `${NOMBRE}-${from}-${to}.mp4`);
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-shortest',
    '-vf', 'scale=in_range=full:out_range=tv,format=yuv420p', '-color_range', 'tv',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-r', String(FPS),
    '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const total = Math.round((to - from) * FPS);
  const t0 = Date.now();
  for (let f = 0; f < total; f++) {
    const t = from + f / FPS;
    await page.evaluate(tt => window.renderFrame(tt), t);
    const buf = await page.screenshot({ type: 'jpeg', quality: 94 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (f % 150 === 0) console.log(`${video}: ${(t).toFixed(1)} s · ${Math.round(((Date.now() - t0) / 1000))} s transcurridos`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  console.log('listo:', out);
}
await browser.close();
server.close();
