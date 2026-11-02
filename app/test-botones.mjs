// Recorrido exhaustivo de botones: entra a cada pantalla de la app (y del panel /admin/ si hay
// credenciales), pulsa cada control visible y registra:
//   - excepciones de JavaScript no atrapadas (pageerror)
//   - respuestas 5xx del backend
//   - botones "muertos": el clic no cambia el DOM, no navega y no hace ninguna petición
// Uso:  BASE=http://localhost:8082 E2E_USER=lucia@patitas.com E2E_PASSWORD=... node app/test-botones.mjs
// Opcional: E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD para recorrer también el panel.
// Sale con código 1 si hay excepciones JS o 5xx. Los botones muertos se listan como aviso (algunos son
// legítimos: p. ej. un botón deshabilitado a propósito).
import { chromium } from 'playwright';

const BASE = process.env.BASE || 'http://localhost:8082';
const USER = process.env.E2E_USER || 'lucia@patitas.com';
const PASS = process.env.E2E_PASSWORD || process.env.SEED_PASSWORD || '';
const ADMIN = process.env.E2E_ADMIN_EMAIL, ADMIN_PASS = process.env.E2E_ADMIN_PASSWORD;

// Controles que no se pulsan: cierran la sesión, borran datos reales o salen del sitio
const SKIP = /cerrar sesi[oó]n|salir|eliminar (mi )?cuenta|borrar cuenta|todos los dispositivos|logout|pagar|donar \$|confirmar pago/i;
// Peticiones externas que la red de pruebas puede bloquear (mapas, fuentes, analítica)
const EXTERNAL = /openstreetmap|googleapis|gstatic|sentry|posthog|mercadopago|facebook|google\.com/;

const SCREENS = ['home', 'discover', 'list', 'map', 'shop', 'ranking', 'notifications', 'chat-list', 'profile',
  'edit-profile', 'preferences', 'appearance', 'help', 'publish', 'report', 'report-form', 'photo-search',
  'refuge-register', 'foster-register', 'my-refuge'];

async function login(email, password) {
  const r = await fetch(BASE + '/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: email, password }) });
  if (!r.ok) throw new Error(`login ${email}: ${r.status} ${await r.text()}`);
  return (await r.json()).access_token;
}

const findings = { pageErrors: [], serverErrors: [], dead: [], clicked: 0, screens: 0 };

async function crawl(page, label, enter, scope) {
  await enter();
  await page.waitForTimeout(600);
  const count = await page.locator(scope).locator('button:visible, [role=button]:visible, a[data-go]:visible, [data-action]:visible').count();
  findings.screens++;
  for (let i = 0; i < count; i++) {
    await enter();
    await page.waitForTimeout(350);
    const btns = page.locator(scope).locator('button:visible, [role=button]:visible, a[data-go]:visible, [data-action]:visible');
    if (i >= await btns.count()) break;
    const b = btns.nth(i);
    const text = ((await b.innerText().catch(() => '')) || (await b.getAttribute('aria-label').catch(() => '')) || (await b.getAttribute('id').catch(() => '')) || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    if (SKIP.test(text)) continue;
    if (await b.isDisabled().catch(() => false)) continue;
    const before = await page.evaluate(() => document.body.innerHTML.length + '|' + location.href + '|' + (document.querySelector('.screen.active')?.dataset.s || ''));
    let requests = 0;
    const onReq = req => { if (!EXTERNAL.test(req.url())) requests++; };
    page.on('request', onReq);
    try { await b.click({ timeout: 2500 }); } catch (e) { page.off('request', onReq); continue; }
    await page.waitForTimeout(700);
    page.off('request', onReq);
    findings.clicked++;
    const after = await page.evaluate(() => document.body.innerHTML.length + '|' + location.href + '|' + (document.querySelector('.screen.active')?.dataset.s || ''));
    if (before === after && requests === 0) findings.dead.push(`${label} → «${text || '(sin texto)'}»`);
    // cierra hojas/modales abiertos para el siguiente clic
    await page.keyboard.press('Escape').catch(() => {});
  }
}

async function run() {
  if (!PASS) throw new Error('Define E2E_PASSWORD o SEED_PASSWORD');
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const token = await login(USER, PASS);
  await ctx.addInitScript(([t]) => {
    localStorage.setItem('patitas_token', t);
    localStorage.setItem('patitas_onboarded', '1');
  }, [token]);
  // En el panel no inyectamos token aquí: se agrega abajo si hay credenciales de admin
  await ctx.route(EXTERNAL, r => r.abort());
  const page = await ctx.newPage();
  let where = 'inicio';
  page.on('pageerror', e => findings.pageErrors.push(`${where}: ${e.message}`));
  page.on('response', r => { if (r.status() >= 500) findings.serverErrors.push(`${where}: ${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
  // Peticiones del mismo origen que fallan por red (no externas): proxy caído, CORS, etc.
  page.on('requestfailed', r => { if (!EXTERNAL.test(r.url())) findings.serverErrors.push(`${where}: FALLÓ ${r.request?.().method?.() || r.method()} ${r.url().replace(BASE, '')} (${r.failure()?.errorText})`); });

  if (!process.env.ONLY_ADMIN) {  // ONLY_ADMIN=1: solo el panel
    await page.goto(BASE + '/app/');
    // Usuarios sembrados sin Términos aceptados: se aceptan como lo haría una persona (modal + casillas)
    await page.waitForFunction(() => document.querySelector('.screen.active')?.dataset.s === 'home'
      || document.querySelector('#terms-modal.open'), null, { timeout: 15000 });
    // El aviso de cookies queda encima del modal de Términos en un dispositivo nuevo: se decide primero
    if (await page.locator('#cookie-banner #pfc-reject').isVisible().catch(() => false)) await page.click('#cookie-banner #pfc-reject');
    if (await page.locator('#terms-modal.open').count()) {
      if (await page.locator('#tm-birth').isVisible()) await page.fill('#tm-birth', '1990-05-17');
      if (await page.locator('#tm-adult').isVisible()) await page.check('#tm-adult');
      await page.check('#tm-terms');
      await page.click('#tm-accept');
    }
    // Puertas de cumplimiento (nuevas versiones, avisos) y verificación de teléfono opcional
    for (let i = 0; i < 6; i++) {
      if (await page.evaluate(() => document.querySelector('.screen.active')?.dataset.s === 'home')) break;
      const skip = page.locator('.modal.open button:visible, #verify-skip:visible').filter({ hasText: /aceptar|entendido|continuar|después|omitir|ahora no/i }).first();
      if (await skip.count()) await skip.click().catch(() => {});
      await page.waitForTimeout(800);
    }
    await page.waitForFunction(() => document.querySelector('.screen.active')?.dataset.s === 'home', null, { timeout: 15000 });
    for (const s of SCREENS) {
      where = 'app#' + s;
      const ok = await page.evaluate(n => typeof navigate === 'function' && !!document.querySelector(`.screen[data-s="${n}"]`), s);
      if (!ok) { findings.dead.push(`pantalla ${s} no existe`); continue; }
      await crawl(page, 'app#' + s, async () => {
        await page.evaluate(n => navigate(n, { reset: true }), s).catch(() => {});
      }, `.screen[data-s="${s}"]`);
    }

    // Páginas públicas: landing, centro legal, veterinarias, 404
    for (const path of ['/', '/app/legal/', '/app/legal/privacidad.html', '/app/veterinarias-solicitud.html', '/no-existe']) {
      where = path;
      await crawl(page, path, async () => { await page.goto(BASE + path); }, 'body');
    }
  }

  if (ADMIN && ADMIN_PASS) {
    const at = await login(ADMIN, ADMIN_PASS);
    const actx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await actx.addInitScript(([t]) => { localStorage.setItem('patitasfind_admin_token', t); }, [at]);
    await actx.route(EXTERNAL, r => r.abort());
    const ap = await actx.newPage();
    ap.on('pageerror', e => findings.pageErrors.push(`${where}: ${e.message}`));
    ap.on('response', r => { if (r.status() >= 500) findings.serverErrors.push(`${where}: ${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
    where = '/admin/';
    ap.on('dialog', d => d.dismiss());  // confirm()/prompt() de acciones destructivas: se cancelan
    await crawl(ap, '/admin/', async () => { await ap.goto(BASE + '/admin/'); await ap.waitForTimeout(800); }, 'nav');
    await ap.goto(BASE + '/admin/');
    const sections = await ap.$$eval('.nav-btn[data-section]', bs => bs.map(b => b.dataset.section));
    for (const sec of sections) {
      where = '/admin/#' + sec;
      await crawl(ap, where, async () => {
        await ap.goto(BASE + '/admin/');
        await ap.click(`.nav-btn[data-section="${sec}"]`);
        await ap.waitForTimeout(900);
      }, `section#${sec}`);
    }
  }

  await browser.close();
  console.log(`\nPantallas recorridas: ${findings.screens} · controles pulsados: ${findings.clicked}`);
  console.log('\n=== EXCEPCIONES JS ===\n' + ([...new Set(findings.pageErrors)].join('\n') || '(ninguna)'));
  console.log('\n=== 5xx / PETICIONES FALLIDAS ===\n' + ([...new Set(findings.serverErrors)].join('\n') || '(ninguna)'));
  console.log('\n=== BOTONES SIN EFECTO (revisar) ===\n' + ([...new Set(findings.dead)].join('\n') || '(ninguno)'));
  if (findings.pageErrors.length || findings.serverErrors.length) process.exitCode = 1;
}

run().catch(e => { console.error(e); process.exit(2); });
