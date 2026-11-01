// Hoja de fotogramas de una escena animada de la landing (para revisar las capas).
// Monta app/img/anim/<escena>/escena.html con landing.css + landing-anim.css (+ escena.css si existe),
// congela todas las animaciones en N instantes y arma una cuadrícula PNG.
// Uso: node scripts/capas-landing/vista.mjs <escena> [segundos=8] [cuadros=8] [salida.png]
// Requiere el servidor local (app/server.py) en VISTA_URL (por defecto http://localhost:8084/).
// VISTA_ANCHO fija el ancho en px (por defecto 420; usa el ancho real en la landing para revisar tamaños).
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, '../../app/package.json'));
const { chromium } = require('playwright');

const [nombre, segs = '8', cuadros = '8', salida = `/tmp/vista-${process.argv[2]}.png`] = process.argv.slice(2);
if (!nombre) { console.error('falta el nombre de la escena'); process.exit(1); }
const url = process.env.VISTA_URL || 'http://localhost:8084/';
const ancho = Number(process.env.VISTA_ANCHO || 420);
const dir = path.join(here, '../../app/img/anim', nombre);
const escena = fs.readFileSync(path.join(dir, 'escena.html'), 'utf8').replaceAll('loading="lazy"', 'loading="eager"');
const css = fs.existsSync(path.join(dir, 'escena.css')) ? `<link rel="stylesheet" href="img/anim/${nombre}/escena.css?v=${Date.now()}">` : '';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
await page.setContent(`<!doctype html><html><head><base href="${url}">
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@500;600;700;800&family=Patrick+Hand&display=swap" rel="stylesheet">
<link rel="stylesheet" href="landing.css?v=${Date.now()}"><link rel="stylesheet" href="landing-anim.css?v=${Date.now()}">${css}
</head><body style="margin:0;background:#f3efe8"><div id="vista" style="width:${ancho}px;background:#f3efe8">${escena}</div></body></html>`,
{ waitUntil: 'networkidle' });
const sel = '#vista .scene';
await page.evaluate(sel => document.querySelector(sel).classList.add('on'), sel);
await page.waitForFunction(sel => [...document.querySelectorAll(sel + ' img')].every(i => i.complete && i.naturalWidth), sel);
await page.evaluate(() => document.fonts.ready);

const n = Number(cuadros), T = Number(segs) * 1000;
const fotos = [];
for (let i = 0; i < n; i++) {
  const t = (T * i) / n;
  await page.evaluate(([sel, t]) => {
    for (const a of document.querySelector(sel).getAnimations({ subtree: true })) { a.pause(); a.currentTime = t; }
  }, [sel, t]);
  fotos.push({ t, png: (await page.locator('#vista').screenshot()).toString('base64') });
}

// cuadrícula con la hora de cada cuadro
const cols = Math.min(4, n);
const hoja = await browser.newPage({ viewport: { width: cols * (ancho + 8), height: 400 } });
await hoja.setContent(`<body style="margin:0;background:#222;display:grid;grid-template-columns:repeat(${cols},${ancho}px);gap:8px;padding:4px;font:bold 14px sans-serif;color:#fff">` +
  fotos.map(f => `<div><div>${(f.t / 1000).toFixed(2)} s</div><img style="display:block;width:${ancho}px" src="data:image/png;base64,${f.png}"></div>`).join('') + '</body>');
await hoja.screenshot({ path: salida, fullPage: true });
await browser.close();
console.log(salida);
