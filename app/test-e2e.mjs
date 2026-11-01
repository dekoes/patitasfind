// E2E de GuauWoow: recorre la app real contra el backend local.
// Uso: BASE=http://localhost:8082 node test-e2e.mjs   (capturas en ./e2e-shots)
// Foto de prueba: PHOTO=/ruta/foto.jpg, o la primera .jpg de ../backend/uploads; si no hay, se genera una.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE || 'http://localhost:8082';
const SHOTS = path.join(HERE, 'e2e-shots');
fs.mkdirSync(SHOTS, { recursive: true });

function findUploadJpg() {
  const dir = path.join(HERE, '../backend/uploads');
  try {
    const f = fs.readdirSync(dir).find(n => /\.jpe?g$/i.test(n) && !/_thumb\.jpg$/i.test(n));
    return f ? path.join(dir, f) : null;
  } catch { return null; }
}

/* Genera un JPEG de 800x600 con un perrito dibujado (canvas del propio navegador, sin dependencias) */
async function generatePhoto(browser) {
  const out = path.join(SHOTS, 'foto-prueba.jpg');
  const page = await browser.newPage();
  const dataUrl = await page.evaluate(() => {
    const c = document.createElement('canvas'); c.width = 800; c.height = 600;
    const g = c.getContext('2d');
    g.fillStyle = '#86E0D4'; g.fillRect(0, 0, 800, 600);
    g.fillStyle = '#B5763F'; g.beginPath(); g.ellipse(260, 230, 70, 130, -0.3, 0, Math.PI * 2); g.ellipse(540, 230, 70, 130, 0.3, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#FFF6EC'; g.beginPath(); g.arc(400, 320, 190, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#1D2233'; g.beginPath(); g.arc(330, 290, 18, 0, Math.PI * 2); g.arc(470, 290, 18, 0, Math.PI * 2); g.fill();
    g.beginPath(); g.ellipse(400, 370, 34, 24, 0, 0, Math.PI * 2); g.fill();
    return c.toDataURL('image/jpeg', 0.9);
  });
  await page.close();
  fs.writeFileSync(out, Buffer.from(dataUrl.split(',')[1], 'base64'));
  return out;
}

const errors = [];
let step = 0;
let expectLogin401 = false;  // el último paso comprueba que la cuenta eliminada ya no puede entrar
const results = [];
/* Tienda: endpoints del contrato S1–S6 que responden 404 cuando todavía no hay datos (pedido sin factura,
   perfil fiscal sin capturar) o mientras el backend no los publica. Se listan como aviso, no como error. */
const SHOP_404 = /^\/(orders\/\d+\/(invoice|invoice-request|cancel|confirm-delivery|return)|refuges\/me\/(fiscal|payments\/(status|connect)|statements(\/export)?))$/;
const shopPending = new Set();
/* Páginas legales que aún no se generan (veterinarias.js las prueba con HEAD y enlaza a los Términos mientras tanto) */
const LEGAL_404 = /^\/app\/legal\/[a-z0-9-]+\.html$/;
const legalPending = new Set();
const pathOf = u => { try { return new URL(u).pathname; } catch { return ''; } };

async function run() {
  const browser = await chromium.launch({ headless: true });
  const PHOTO = process.env.PHOTO || findUploadJpg() || await generatePhoto(browser);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, geolocation: { latitude: 19.4326, longitude: -99.1332 }, permissions: ['geolocation'] });
  const page = await ctx.newPage();
  page.on('pageerror', e => errors.push('PAGE ERROR: ' + e.message));
  // Las miniaturas que aún no existen caen a la foto completa (listener de "error"), no es un fallo
  page.on('console', m => {
    if (m.type() !== 'error' || /favicon|tile\.openstreetmap|nominatim/.test(m.text())) return;
    const where = (m.location() || {}).url || '';
    if (/_thumb\.jpg/.test(where)) return;
    if (expectLogin401 && /\/auth\/login$/.test(where) && /401/.test(m.text())) return;
    if (/404/.test(m.text()) && SHOP_404.test(pathOf(where))) { shopPending.add(pathOf(where).replace(/\d+/g, '{id}')); return; }
    if (/404/.test(m.text()) && LEGAL_404.test(pathOf(where))) { legalPending.add(pathOf(where)); return; }
    errors.push('CONSOLE: ' + m.text() + (where ? ` [${where.replace(BASE, '')}]` : ''));
  });
  page.on('dialog', d => d.accept());

  const shot = async name => page.screenshot({ path: path.join(SHOTS, `${String(++step).padStart(2, '0')}-${name}.png`) });
  const active = s => page.waitForSelector(`[data-s="${s}"].active`, { timeout: 15000 });
  const toastIs = async (re, timeout = 6000) => page.waitForFunction(src => new RegExp(src, 'i').test(document.querySelector('#toast-msg').textContent), re.source, { timeout });
  const t = async (name, fn) => {
    try { await fn(); results.push(['OK', name]); }
    catch (e) { console.log('FAIL', name, e.message.split('\n')[0]); results.push(['FAIL', name, e.message.split('\n')[0]]); await shot('FAIL-' + name.replace(/\W+/g, '_')); }
  };
  const toNav = async () => { while (!(await page.isVisible('#nav'))) { await page.click('.screen.active .nav-back'); await page.waitForTimeout(500); } };
  const email = `e2e${Date.now()}@guauwoow.com`;

  await t('splash + onboarding', async () => {
    await page.goto(BASE + '/app/');
    await page.waitForTimeout(700); await shot('splash');
    await active('onboarding'); await shot('onboarding');
    // Aviso de cookies (/app/legal/js/cookies.js): «Necesarias» siempre, «Analítica» apagada hasta aceptarla
    await page.waitForSelector('#cookie-banner #pfc-reject', { timeout: 10000 });
    await shot('aviso-cookies');
    await page.click('#pfc-reject');
    const consent = await page.evaluate(() => JSON.parse(localStorage.getItem('patitas_consent') || 'null'));
    if (!consent || consent.analytics !== false || !consent.v || !consent.at) throw new Error('patitas_consent sin versión o fecha');
    await page.click('#ob-skip');
    await active('auth');
  });

  await t('registro', async () => {
    await page.click('#auth-toggle');
    await page.fill('#auth-name', 'Prueba E2E');
    await page.fill('#auth-email', email);
    await page.fill('#auth-password', 'Patitas123!');
    await page.fill('#auth-phone', '55' + String(Date.now()).slice(-8));
    // Edad (L-edad): fecha de nacimiento + casilla de 18+ separada de Términos, sin marcar de inicio
    if (await page.isChecked('#auth-adult')) throw new Error('la casilla de 18+ viene marcada');
    await page.fill('#auth-birth', '2012-05-17');
    await page.check('#auth-terms');
    await page.check('#auth-adult');
    await page.click('#auth-submit'); await toastIs(/18 años o más/);
    const minor = await (async () => {  // directo al backend (fuera del navegador: el 400 no es un error de consola)
      const r = await fetch(BASE + '/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: `menor${Date.now()}@pruebas.mx`, password: 'Patitas123!', full_name: 'Menor de Edad',
          phone: '55' + String(Date.now()).slice(-8), accepted_terms: true, is_adult: true, birth_date: '2012-05-17' }) });
      return { status: r.status, detail: (await r.json().catch(() => ({}))).detail };
    })();
    if (minor.status !== 400 || !/18 años/.test(String(minor.detail))) throw new Error('el backend no rechazó a un menor de edad: ' + JSON.stringify(minor));
    await page.fill('#auth-birth', '1990-05-17');  // fecha de nacimiento (18+)
    await page.uncheck('#auth-adult');
    await page.click('#auth-submit'); await toastIs(/Marca la casilla/);
    await page.check('#auth-adult');  // casilla separada de mayoría de edad
    await shot('registro');
    await page.click('#auth-submit');
    await active('verify-phone');
    await page.waitForFunction(() => [...document.querySelectorAll('.code-box')].filter(b => b.value).length >= 4, null, { timeout: 15000 });
    await shot('verificar-telefono');
    await page.click('#verify-submit');
    await active('home');
    await page.waitForTimeout(1500); await shot('home');
  });

  await t('ubicación GPS', async () => {
    await page.click('#home-loc');
    await page.click('#loc-gps');
    await page.waitForTimeout(2500);
  });

  await t('descubrir + like + cuestionario', async () => {
    await page.click('.cat[data-cat="adopt"]');
    await active('discover');
    await page.waitForSelector('#tcard', { timeout: 15000 });
    await page.waitForTimeout(600); await shot('discover');
    await page.click('#like-btn');
    await page.waitForSelector('#match-modal.show', { timeout: 10000 });
    await page.waitForTimeout(900); await shot('match');
    await page.click('#match-questionnaire');
    await active('questionnaire');
    for (const q of ['housing', 'experience', 'children', 'other_pets', 'budget', 'hours_alone']) await page.click(`[data-q="${q}"] .chip >> nth=0`);
    await page.fill('#q-why', 'Tengo patio y mucho tiempo para pasear.');
    await page.check('#q-commit');
    await shot('cuestionario');
    await page.click('#questionnaire-form button[type=submit]');
    await page.waitForSelector('#success-pop.show', { timeout: 10000 }); await shot('exito');
    await active('home');
  });

  await t('reportar contenido (modal)', async () => {
    await active('home');
    const card = await page.waitForSelector('#home-carousel [data-dog]', { timeout: 15000 });
    await card.click();
    await active('dog');
    await page.waitForSelector('#dog-flag:not(.hidden)', { timeout: 10000 });
    await page.click('#dog-flag');
    await page.waitForSelector('#flag-modal.open');
    await page.click('#flag-reasons [data-v="datos_falsos"]');
    await page.fill('#flag-details', 'Prueba E2E: la descripción no coincide con las fotos.');
    await shot('reportar-contenido');
    const [res] = await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === '/reports' && r.request().method() === 'POST', { timeout: 15000 }),
      page.click('#flag-submit'),
    ]);
    if (![200, 201].includes(res.status())) throw new Error('POST /reports respondió ' + res.status());
    await page.waitForSelector('#flag-modal:not(.open)', { state: 'attached', timeout: 10000 });
    await page.click('[data-s="dog"] .nav-back');
    await active('home');
  });

  await t('publicar en adopción', async () => {
    await page.click('#nav-fab');
    await page.click('[data-pub="adopt"]');
    await active('publish');
    await page.setInputFiles('[data-photos="pub"] + input', PHOTO);
    await page.fill('#pub-name', 'Firulais E2E');
    await page.fill('#pub-description', 'Juguetón y cariñoso');
    await shot('publicar');
    await page.click('#publish-submit');
    await active('dog');
    await page.waitForTimeout(800); await shot('perfil-perro');
  });

  await t('reporte perdido + coincidencias', async () => {
    await page.click('[data-s="dog"] .nav-back');
    await page.click('#nav-fab');
    await page.click('[data-pub="lost"]');
    await active('report-form');
    await page.setInputFiles('[data-photos="rf"] + input', PHOTO);
    await page.fill('#rf-name', 'Rocky E2E');
    await page.fill('#rf-city', 'Roma Norte, CDMX');
    await page.click('[data-loc="rf"] [data-loc-btn]');
    await page.waitForTimeout(1500);
    await page.click('#rf-submit');
    await active('report');
    await page.waitForTimeout(2500); await shot('reporte');
  });

  await t('buscar por foto', async () => {
    await page.click('[data-s="report"] .nav-back');
    await active('home');
    await page.click('#home-photo-btn');
    await active('photo-search');
    await page.setInputFiles('#ps-gallery', PHOTO);
    await page.click('#ps-go');
    await page.waitForTimeout(1200); await shot('escaneo');
    await page.waitForSelector('#ps-results:not(.hidden)', { timeout: 20000 });
    await page.waitForTimeout(600); await shot('resultados-foto');
  });

  await t('mapa', async () => {
    await page.click('[data-s="photo-search"] .nav-back');
    await active('home');
    await page.click('#home-map');
    await active('map');
    await page.waitForTimeout(2500); await shot('mapa');
  });

  // ---------- Tienda (tienda.js): carrito de un refugio, checkout con dirección estructurada y pedido ----------
  let orderId = null;
  await t('tienda + pedido', async () => {
    await page.click('[data-s="map"] .nav-back');
    await page.click('#home-shop');
    await active('shop');
    await page.waitForSelector('#shop-list [data-add]', { timeout: 15000 });
    await page.waitForTimeout(600); await shot('tienda');
    const add = await page.$('#shop-list [data-add]:not([disabled])');
    if (!add) {
      // Refugios sin Mercado Pago conectado: los productos se ven pero no se pueden comprar (S1)
      if (!(await page.$('#shop-list .shop-note'))) throw new Error('No hay productos con stock');
      results.push(['AVISO', 'tienda: ningún refugio tiene cobros activos; se omite el pedido real']);
      return;
    }
    await add.click();
    await page.click('#cart-btn');
    await page.waitForSelector('#cart-modal.open #cart-items .card', { timeout: 10000 });
    await shot('carrito');
    await page.click('#cart-checkout');
    await active('checkout');
    // Estado al que se envía el primer producto (si no envía a todo México)
    const dest = await page.evaluate(() => { const i = state.cart.find(x => x.ships_nationwide === false && x.ships_states.length); return i ? i.ships_states[0] : 'Ciudad de México'; });
    await page.fill('#co-name', 'Prueba E2E');
    await page.fill('#co-phone', '5512345678');
    await page.fill('#co-street', 'Av. Álvaro Obregón');
    await page.fill('#co-ext', '123');
    await page.fill('#co-int', '');
    await page.fill('#co-neigh', 'Roma Norte');
    await page.fill('#co-cp', '06700');
    await page.fill('#co-city', 'Cuauhtémoc');
    await page.selectOption('#co-state', dest);
    await page.check('#co-terms');
    await page.check('#co-prepay');
    await shot('checkout');
    const [res] = await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === '/orders' && r.request().method() === 'POST', { timeout: 15000 }),
      page.click('#co-pay'),
    ]);
    if (![200, 201].includes(res.status())) throw new Error(`POST /orders respondió ${res.status()}: ${(await res.text()).slice(0, 200)}`);
    const o = await res.json();
    orderId = o.id;
    if (o.checkout_url) {
      // Mercado Pago real configurado: no se paga en el E2E, se vuelve a la app
      results.push(['AVISO', `tienda: el pedido #${o.id} quedó en pago pendiente (Mercado Pago real configurado)`]);
      await page.goto(BASE + '/app/');
      await active('home');
      return;
    }
    await active('order');
    await page.waitForSelector('#order-body .tl .tl-item', { timeout: 15000 });
    await page.waitForTimeout(600); await shot('pedido');
  });

  await t('tienda: validación del checkout (dirección y estado atendido)', async () => {
    // Carrito de ejemplo que solo envía a Jalisco: todo se valida en el navegador, no se crea ningún pedido
    let posted = 0;
    const onReq = r => { if (r.method() === 'POST' && new URL(r.url()).pathname === '/orders') posted++; };
    page.on('request', onReq);
    const saved = await page.evaluate(() => {
      const prev = JSON.stringify(state.cart);
      state.cart = [{ product_id: -1, refuge_id: -1, refuge_name: 'Refugio de prueba', name: 'Playera E2E', price: 199, quantity: 1, photo: '', stock: 3, shipping_cost: 80, ships_nationwide: false, ships_states: ['Jalisco'], handling_days: 2 }];
      Tienda.openCheckout();
      return prev;
    });
    try {
      await active('checkout');
      if (!/279/.test(await page.textContent('#co-pay'))) throw new Error('el botón no muestra el total con envío: ' + await page.textContent('#co-pay'));
      // consumidor-ecommerce-17/20/26: comisión visible, casilla de guardar dirección sin marcar y aviso de 18+
      if (!/GuauWoow (recibe|no cobra)/.test(await page.textContent('#co-fee'))) throw new Error('el checkout no muestra la comisión de GuauWoow');
      if (await page.isChecked('#co-save-address')) throw new Error('"Guardar esta dirección" viene marcada');
      if (!/mayores de 18/.test(await page.textContent('[data-s="checkout"]'))) throw new Error('falta el aviso de 18+');
      for (const id of ['co-name', 'co-phone', 'co-street', 'co-ext', 'co-int', 'co-neigh', 'co-cp', 'co-city', 'co-refs']) await page.fill('#' + id, '');
      await page.selectOption('#co-state', '');
      await page.click('#co-pay'); await toastIs(/nombre de quien recibe/);
      await page.fill('#co-name', 'Prueba E2E');
      await page.fill('#co-phone', '33 1234');
      await page.click('#co-pay'); await toastIs(/10 d[ií]gitos/);
      await page.fill('#co-phone', '33 1234 5678');
      await page.fill('#co-street', 'Av. Juárez');
      await page.fill('#co-ext', '100');
      await page.fill('#co-neigh', 'Centro');
      await page.fill('#co-city', 'Guadalajara');
      await page.click('#co-pay'); await toastIs(/Elige tu estado/);
      await page.selectOption('#co-state', 'Ciudad de México');
      await page.fill('#co-cp', '441');
      await page.click('#co-pay'); await toastIs(/c[oó]digo postal/);
      await page.fill('#co-cp', '44100');
      await page.click('#co-pay'); await toastIs(/no se env[ií]a a Ciudad de M[eé]xico/);
      await page.selectOption('#co-state', 'Jalisco');
      await page.click('#co-pay'); await toastIs(/condiciones de compra/);
      await page.check('#co-terms');
      await page.click('#co-pay'); await toastIs(/Autoriza el cobro/);
      await shot('checkout-validacion');
      if (posted) throw new Error('se envió un pedido con datos inválidos');
    } finally {
      page.off('request', onReq);
      await page.evaluate(prev => { state.cart = JSON.parse(prev); try { localStorage.setItem('patitas_cart', prev); } catch { } }, saved);
    }
    await page.click('[data-s="checkout"] .nav-back');
  });

  await t('tienda: línea de tiempo del pedido', async () => {
    const S3 = ['pending_payment', 'paid', 'preparing', 'shipped', 'delivered', 'completed', 'cancelled', 'return_requested', 'return_approved', 'return_rejected', 'refunded', 'refund_pending', 'amount_mismatch'];
    const missing = await page.evaluate(list => list.filter(s => !Tienda.ORDER_STATUS[s]), S3);
    if (missing.length) throw new Error('estados sin etiqueta en español: ' + missing.join(', '));
    if (orderId) {
      // Perfil → Mis pedidos → el pedido recién creado
      await toNav();
      await page.click('#nav .nav-item[data-go="profile"]');
      await active('profile');
      await page.click('[data-act="orders"]');
      await active('list');
      await page.click(`[data-order-open="${orderId}"]`);
      await active('order');
      await page.waitForSelector('#order-body .tl .tl-item', { timeout: 15000 });
      // ¿Necesitas factura? valida el RFC en el navegador antes de enviar
      if (await page.$('#od-invoice')) {
        await page.click('#od-invoice');
        await page.waitForSelector('#invoice-modal.open');
        await page.fill('#inv-rfc', 'ABC12');
        await page.click('#inv-submit'); await toastIs(/RFC v[aá]lido/);
        await page.click('#invoice-modal [data-close-modal]');
      }
    } else {
      // Sin pedido real (ningún refugio cobra todavía): se pinta un pedido de ejemplo con devolución y reembolso
      await page.evaluate(() => {
        navigate('order');
        const at = (d, h) => `2026-10-${String(d).padStart(2, '0')}T${String(h).padStart(2, '0')}:00:00`;
        Tienda.renderOrder({
          id: 999999, status: 'refunded', total: '279.00', subtotal: '199.00', shipping_total: '80.00', refuge_name: 'Refugio de prueba', created_at: at(1, 10),
          items: [{ product_id: 1, quantity: 1, unit_price: '199.00', product_name: 'Playera E2E' }], shipping_street: 'Av. Juárez', shipping_ext_number: '100',
          shipping_neighborhood: 'Centro', shipping_city: 'Guadalajara', shipping_state: 'Jalisco', shipping_postal_code: '44100', return_reason: 'defectuoso',
          timeline: [['pending_payment', 1, 10], ['paid', 1, 11], ['preparing', 2, 9], ['shipped', 2, 15], ['delivered', 4, 12], ['return_requested', 5, 9], ['return_approved', 5, 18], ['refunded', 6, 10]]
            .map(([status, d, h]) => ({ status, at: at(d, h), note: '' })),
        });
      });
      await active('order');
      results.push(['AVISO', 'tienda: línea de tiempo revisada con un pedido de ejemplo (no hubo pedido real)']);
    }
    const labels = await page.$$eval('#order-body .tl .tl-item b', bs => bs.map(b => b.textContent.trim()));
    if (!labels.length) throw new Error('la línea de tiempo está vacía');
    const raw = labels.find(l => /^[a-z_]+$/.test(l));
    if (raw) throw new Error('estado sin traducir en la línea de tiempo: ' + raw);
    await page.waitForTimeout(400); await shot('pedido-linea-de-tiempo');
  });

  await t('refugios + ranking', async () => {
    while (!(await page.isVisible('#nav'))) { await page.click('.screen.active .nav-back'); await page.waitForTimeout(500); }
    await page.click('#nav .nav-item[data-go="home"]');
    await page.click('.cat[data-cat="refuges"]');
    await active('list');
    await page.waitForTimeout(1200); await shot('refugios');
    const r = await page.$('[data-refuge]');
    if (r) { await r.click(); await active('refuge'); await page.waitForTimeout(800); await shot('refugio'); }
  });

  // ---------- Veterinarias: directorio, registro con validaciones, verificación en el panel y detalle ----------
  // El panel necesita una cuenta de admin: E2E_ADMIN_EMAIL y E2E_ADMIN_PASSWORD (si faltan, ese paso se omite)
  const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || '';
  const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || '';
  const vetName = `Clínica E2E ${String(Date.now()).slice(-6)}`;
  let vetId = null, vetVerified = false;
  const toastHas = re => page.waitForFunction(src => document.querySelector('#toast').classList.contains('show')
    && new RegExp(src, 'i').test(document.querySelector('#toast-msg').textContent), re.source, { timeout: 6000 });
  // Un server.py arrancado antes de agregar "/veterinaries" a PROXIED_PREFIXES responde la página 404: se omiten
  // los pasos con el motivo en lugar de marcarlos como fallas de la app
  const vetsProxy = await page.evaluate(async () => {
    try { const r = await fetch('/veterinaries/meta'); return r.ok && /json/.test(r.headers.get('content-type') || ''); } catch { return false; }
  });
  const tv = (name, fn) => vetsProxy ? t(name, fn) : results.push(['SKIP', `${name} (el servidor de desarrollo no reenvía /veterinaries: reinicia app/server.py)`]);

  await tv('veterinarias: lista y filtros', async () => {
    // Un paso anterior fallido puede dejar un modal abierto (p. ej. el carrito): se cierra antes de empezar
    await page.evaluate(() => document.querySelectorAll('.modal.open').forEach(m => m.classList.remove('open')));
    await toNav();
    await page.click('#nav .nav-item[data-go="home"]');
    await active('home');
    await page.click('#home-vets');
    await active('vets');
    await page.waitForSelector('#vets-list [data-vet], #vets-list .empty, #vets-list .card', { timeout: 15000 });
    if (/se está activando/.test(await page.textContent('#vets-list'))) throw new Error('el backend de veterinarias no responde (¿falta /veterinaries en PROXIED_PREFIXES?)');
    await page.click('#vets-emergency');
    await page.waitForSelector('#vets-emergency.on[aria-pressed="true"]');
    await page.waitForSelector('#vets-list [data-vet], #vets-list .empty', { timeout: 15000 });
    await page.click('#vets-emergency');
    await page.waitForSelector('#vets-emergency:not(.on)');
    await shot('veterinarias');
  });

  await tv('veterinarias: registro (validaciones y envío)', async () => {
    await page.click('#vets-register');
    await active('vet-form');
    const expectError = async re => { await page.click('#vf-submit'); await toastHas(re); };
    await expectError(/nombre de la clínica/);
    await page.fill('#vf-name', vetName);
    await page.fill('#vf-address', 'Av. Álvaro Obregón 100, Col. Roma Norte');
    await page.fill('#vf-city', 'Ciudad de México');
    await page.selectOption('#vf-state', 'Ciudad de México');
    await page.fill('#vf-cp', '06700');
    await expectError(/teléfono o WhatsApp/);
    await page.fill('#vf-phone', '55 1234 5678');
    await page.click('#vf-services [data-service="Vacunas"]');
    await page.click('#vf-services [data-service="Consulta general"]');
    await page.check('#vf-hours [data-day="sat"] [data-closed]');
    if (!(await page.isDisabled('#vf-hours [data-day="sat"] [data-open]'))) throw new Error('el sábado cerrado no desactiva sus horas');
    // Turno partido: segundo horario del lunes (hasta 4 por día)
    await page.click('#vf-hours [data-day="mon"] [data-add-range]');
    await page.fill('#vf-hours [data-day="mon"] [data-range]:nth-of-type(1) [data-close]', '14:00');
    await expectError(/cada horario del lunes/);
    await page.fill('#vf-hours [data-day="mon"] [data-range]:nth-of-type(2) [data-open]', '16:00');
    await page.fill('#vf-hours [data-day="mon"] [data-range]:nth-of-type(2) [data-close]', '20:00');
    await page.fill('#vf-vet', 'MVZ. Ana López Pérez');
    await page.fill('#vf-cedula', '12ab');
    await expectError(/cédula profesional son de 5 a 10/);
    await page.fill('#vf-cedula', '12345678');
    await expectError(/foto o el PDF de la cédula/);
    await page.setInputFiles('#vf-cedula-file', PHOTO);
    await page.waitForSelector('#vf-cedula-box .doc-item');
    await expectError(/Ubica la clínica/);
    await page.click('[data-loc="vf"] [data-loc-btn]');
    await page.waitForSelector('[data-loc="vf"].ok', { timeout: 10000 });
    await expectError(/consentimiento/);
    await page.check('#vf-consent');
    await shot('veterinaria-registro');
    const [res] = await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === '/veterinaries' && r.request().method() === 'POST', { timeout: 20000 }),
      page.click('#vf-submit'),
    ]);
    if (res.status() !== 201) throw new Error(`POST /veterinaries respondió ${res.status()}: ${(await res.text()).slice(0, 200)}`);
    vetId = (await res.json()).id;
    await active('my-vet');
    await page.waitForFunction(() => /En revisión/.test(document.querySelector('#my-vet-body').textContent), null, { timeout: 10000 });
    await shot('mi-veterinaria');
  });

  if (ADMIN_EMAIL && ADMIN_PASSWORD) {
    await tv('veterinarias: panel admin (cola, cédula y verificación)', async () => {
      if (!vetId) throw new Error('no se registró la clínica');
      const admin = await ctx.newPage();
      admin.on('pageerror', e => errors.push('ADMIN PAGE ERROR: ' + e.message));
      admin.on('dialog', d => d.accept());
      try {
        await admin.goto(BASE + '/admin/');
        await admin.fill('#email', ADMIN_EMAIL);
        await admin.fill('#password', ADMIN_PASSWORD);
        await admin.click('#login-form button[type=submit]');
        await admin.waitForSelector('#app-view:not(.hidden)', { timeout: 15000 });
        await admin.click('.nav-btn[data-section="veterinaries"]');
        await admin.waitForSelector('#veterinaries-table table, #veterinaries-table .empty', { timeout: 15000 });
        await admin.fill('#vets-filter-q', vetName);  // la cola puede tener muchas pendientes de corridas anteriores
        await admin.click('#vets-filter-btn');
        const row = admin.locator('#veterinaries-table tr', { hasText: vetName });
        await row.waitFor({ timeout: 15000 });
        await admin.screenshot({ path: path.join(SHOTS, `${String(++step).padStart(2, '0')}-admin-veterinarias.png`), fullPage: true });
        const [popup, ced] = await Promise.all([
          ctx.waitForEvent('page', { timeout: 15000 }),
          admin.waitForResponse(r => new URL(r.url()).pathname === `/admin/veterinaries/${vetId}/cedula`, { timeout: 15000 }),
          row.getByRole('button', { name: 'Ver cédula' }).click(),
        ]);
        if (ced.status() !== 200) throw new Error('la cédula respondió ' + ced.status());
        await popup.close().catch(() => {});
        // Verificar exige la evidencia del cotejo: carrera del RNP y captura privada
        await row.getByRole('button', { name: 'Verificar' }).click();
        await admin.waitForSelector('#vet-verify-form', { timeout: 10000 });
        await admin.fill('#vv-carrera', 'Médico Veterinario Zootecnista');
        await admin.setInputFiles('#vv-file', PHOTO);
        await admin.check('#vv-ok');
        const [ver] = await Promise.all([
          admin.waitForResponse(r => new URL(r.url()).pathname === `/admin/veterinaries/${vetId}/verify`, { timeout: 15000 }),
          admin.click('#vv-send'),
        ]);
        if (ver.status() !== 200) throw new Error('verificar respondió ' + ver.status());
        vetVerified = true;
        await admin.waitForSelector('#vet-reviews-table table, #vet-reviews-table .empty', { timeout: 15000 });  // reseñas retenidas
      } finally { await admin.close(); }
    });
  } else results.push(['SKIP', 'veterinarias: panel admin (define E2E_ADMIN_EMAIL y E2E_ADMIN_PASSWORD)']);

  // Verificación en dos pasos del personal (L-seguridad): el alta con código QR existe. No se confirma (la cuenta
  // de admin del E2E sigue entrando con contraseña en desarrollo, donde la MFA es opcional).
  if (ADMIN_EMAIL && ADMIN_PASSWORD) {
    await t('admin: alta de la verificación en dos pasos (QR y clave)', async () => {
      const admin = await ctx.newPage();
      admin.on('pageerror', e => errors.push('ADMIN PAGE ERROR: ' + e.message));
      try {
        await admin.goto(BASE + '/admin/');
        if (!(await admin.$('#mfa-form'))) throw new Error('el inicio de sesión del panel no tiene el segundo paso (#mfa-form)');
        // Panel (sesión del paso anterior) o formulario de acceso, el que se vea (selector CSS con «,» toma el primero del DOM)
        await admin.waitForFunction(() => ['#app-view', '#login-form']
          .some(sel => { const el = document.querySelector(sel); return !!(el && el.getClientRects().length); }), null, { timeout: 15000 });
        if (!(await admin.isVisible('#app-view'))) {  // la sesión del paso anterior puede seguir abierta
          await admin.fill('#email', ADMIN_EMAIL);
          await admin.fill('#password', ADMIN_PASSWORD);
          await admin.click('#login-form button[type=submit]');
        }
        await admin.waitForSelector('#app-view:not(.hidden), #mfa-form:not(.hidden), #mfa-enroll:not(.hidden)', { timeout: 15000 });
        if (await admin.isVisible('#mfa-form') || await admin.isVisible('#mfa-enroll')) {
          // Entorno con MFA obligatoria: el propio inicio de sesión pide el código o el alta
          if (await admin.isVisible('#mfa-enroll')) await admin.waitForSelector('#mfa-enroll img.mfa-qr, #mfa-enroll code.mfa-secret', { timeout: 10000 });
          return;
        }
        await admin.click('.nav-btn[data-section="seguridad"]');
        await admin.waitForSelector('#sec-mfa-me button, #sec-mfa-me p', { timeout: 15000 });
        const enabled = /Activa desde/.test(await admin.textContent('#sec-mfa-me'));
        if (!enabled) {
          await admin.click('#sec-mfa-me button:has-text("Activar ahora")');
          await admin.waitForSelector('#sec-mfa-me img.mfa-qr', { timeout: 10000 });
          const secret = (await admin.textContent('#sec-mfa-me code.mfa-secret')).replace(/\s+/g, '');
          if (!/^[A-Z2-7]{16,}$/.test(secret)) throw new Error('clave TOTP inesperada: ' + secret);
          if (!(await admin.$('#mfa-enroll-code'))) throw new Error('falta el campo del primer código');
          await admin.screenshot({ path: path.join(SHOTS, `${String(++step).padStart(2, '0')}-admin-mfa-alta.png`), fullPage: true });
        }
        await admin.waitForSelector('#sec-mfa-admins table', { timeout: 10000 });
      } finally { await admin.close(); }
    });
  } else results.push(['SKIP', 'admin: alta de la verificación en dos pasos (define E2E_ADMIN_EMAIL y E2E_ADMIN_PASSWORD)']);

  await tv('veterinarias: detalle y pin en el mapa', async () => {
    if (!vetId) throw new Error('no se registró la clínica');
    if (vetVerified) {
      await toNav();
      await page.click('#nav .nav-item[data-go="home"]');
      await page.click('#home-vets');
      await active('vets');
      await page.fill('#vets-q', vetName);
      await page.click('#vets-search-form button[type=submit]');
      await page.click(`#vets-list [data-vet="${vetId}"]`, { timeout: 15000 });
    } else await page.evaluate(id => window.VET.open(id), vetId);  // la dueña ve su clínica aunque esté en revisión
    await active('vet');
    await page.waitForFunction(n => (document.querySelector('#vet-body h1') || {}).textContent === n, vetName, { timeout: 15000 });
    if (!/No puedes reseñar tu propia clínica/.test(await page.textContent('#vet-body'))) throw new Error('falta el aviso de la propia clínica');
    if (await page.isVisible('#vet-flag')) throw new Error('la dueña no debería ver «Reportar»');
    if (vetVerified) {
      await page.click('#vet-badge');
      await page.waitForSelector('#vet-badge-tip:not(.hidden)');
    }
    await shot('veterinaria-detalle');
    if (vetVerified) {
      await toNav();
      await page.click('#nav .nav-item[data-go="home"]');
      await page.click('#home-map');
      await active('map');
      await page.waitForSelector('#map-filters [data-k="vet"]');
      await page.waitForSelector('.leaflet-marker-icon[src*="vet-marker"]', { timeout: 15000 });
      await shot('mapa-veterinarias');
    }
  });

  // Sin GOOGLE_MAPS_API_KEY en desarrollo el bloque de Google es null: se simula la respuesta (datos de prueba)
  // para comprobar la atribución que piden las políticas de Places (logotipo, autor, enlaces y avisos)
  await tv('veterinarias: bloque de Google Maps (respuesta simulada)', async () => {
    if (!vetId) throw new Error('no se registró la clínica');
    const detailUrl = u => new URL(u).pathname === `/veterinaries/${vetId}`;
    await page.route(detailUrl, async route => {
      const res = await route.fetch();
      const body = await res.json();
      body.google = {
        place_id: 'ChIJprueba_e2e_0001', available: true, rating: 4.5, ratings_total: 1234,
        maps_url: 'https://www.google.com/maps/search/?api=1&query=Prueba&query_place_id=ChIJprueba_e2e_0001',
        attribution: 'Google Maps', order_notice: 'Reseñas de Google Maps ordenadas por relevancia según Google (máximo 5).',
        reviews: [
          { author_name: 'Autora de prueba', author_url: 'https://www.google.com/maps/contrib/1', rating: 5, relative_time: 'hace un mes',
            text: 'Texto traducido de prueba.', original_text: 'Original test text.', language: 'es',
            google_maps_url: 'https://www.google.com/maps/reviews/1', flag_content_url: 'https://www.google.com/local/review/rap/report?postId=1' },
          { author_name: 'Autor sin enlace', rating: 3, relative_time: 'hace 2 semanas', text: 'Segunda reseña <b>sin</b> HTML.' },
        ],
      };
      await route.fulfill({ response: res, json: body });
    });
    try {
      await page.evaluate(id => window.VET.open(id), vetId);
      await active('vet');
      const g = await page.waitForSelector('#vet-body .gplaces', { timeout: 15000 });
      if (!(await g.$('img.gm-logo[alt="Google Maps"][translate="no"]'))) throw new Error('falta el logotipo de Google Maps');
      if ((await g.$$('.g-review')).length !== 2) throw new Error('no se muestran las reseñas tal cual llegan');
      if (!(await g.$('a[href="https://www.google.com/maps/contrib/1"]'))) throw new Error('falta el enlace al perfil del autor');
      for (const txt of ['Ver en Google Maps', 'Reportar a Google', 'Ver todas las reseñas en Google Maps', 'Traducida por Google']) {
        if (!(await g.textContent()).includes(txt)) throw new Error('falta: ' + txt);
      }
      if (!(await g.textContent()).includes('Segunda reseña <b>sin</b> HTML.')) throw new Error('el texto de la reseña no se escapó');
      await g.scrollIntoViewIfNeeded();
      await shot('veterinaria-google');
    } finally { await page.unroute(detailUrl); }
  });

  await t('notificaciones', async () => {
    while (!(await page.isVisible('#nav'))) { await page.click('.screen.active .nav-back'); await page.waitForTimeout(500); }
    await page.click('#nav .nav-item[data-go="notifications"]');
    await active('notifications');
    await page.waitForTimeout(1000); await shot('notificaciones');
  });

  await t('perfil + solicitudes', async () => {
    await page.click('#nav .nav-item[data-go="profile"]');
    await active('profile');
    await page.waitForTimeout(1000); await shot('perfil');
    await page.click('[data-act="matches"]');
    await active('list');
    await page.waitForTimeout(1000); await shot('solicitudes');
  });

  await t('chats', async () => {
    await page.click('[data-s="list"] .nav-back');
    await page.click('#nav .nav-item[data-go="chat-list"]');
    await active('chat-list');
    await page.waitForTimeout(1000); await shot('chats');
  });

  await t('ayuda (FAQ, contacto y legales)', async () => {
    await toNav();
    await page.click('#nav .nav-item[data-go="profile"]');
    await active('profile');
    await page.click('[data-act="help"]');
    await active('help');
    const n = await page.$$eval('[data-s="help"] details', ds => ds.length);
    if (n < 5) throw new Error(`solo hay ${n} preguntas frecuentes`);
    await page.click('[data-s="help"] details >> nth=3 >> summary');
    await page.waitForSelector('[data-s="help"] details[open]');
    for (const href of ['/app/legal/centro-legal.html', '/app/legal/terminos.html', '/app/legal/privacidad.html']) {
      if (!(await page.$(`[data-s="help"] a[href="${href}"]`))) throw new Error('falta el enlace ' + href);
    }
    await page.waitForSelector('#help-problem', { state: 'visible' });
    await shot('ayuda');
    await page.click('[data-s="help"] .nav-back');
    await active('profile');
  });

  await t('centro legal: rutas, atajos y security.txt', async () => {
    const get = (u, opts = {}) => fetch(BASE + u, { redirect: 'manual', ...opts });
    const hub = await get('/app/legal/');
    if (hub.status !== 200 || !(await hub.text()).includes('Centro legal y de transparencia')) throw new Error('/app/legal/ no muestra el centro legal');
    for (const [from, to] of [['/legal', '/app/legal/'], ['/legal/terminos', '/app/legal/terminos.html'], ['/security.txt', '/.well-known/security.txt']]) {
      const r = await get(from);
      if (![301, 302].includes(r.status) || !String(r.headers.get('location')).endsWith(to)) throw new Error(`${from} no redirige a ${to} (${r.status})`);
    }
    const sec = await get('/.well-known/security.txt');
    if (sec.status !== 200 || !/text\/plain/.test(sec.headers.get('content-type') || '') || !(await sec.text()).includes('Contact:')) throw new Error('security.txt no se sirve');
    if ((await get('/app/legal/plantillas/terminos.html')).status !== 404) throw new Error('las plantillas legales no deben servirse');
    const sitemap = await (await get('/sitemap.xml')).text();
    if (!sitemap.includes('/app/legal/centro-legal.html')) throw new Error('el sitemap no lista el centro legal');
  });

  await t('conservación y estado del servicio (tablas en vivo)', async () => {
    // En otra pestaña: la app sigue abierta para las pruebas siguientes
    const legal = await browser.newPage({ viewport: { width: 390, height: 844 } });
    try {
      await legal.goto(`${BASE}/app/legal/conservacion.html`);
      await legal.waitForSelector('#tabla-conservacion tbody tr', { timeout: 10000 });
      const rows = await legal.$$eval('#tabla-conservacion tbody tr', (r) => r.length);
      if (rows < 20) throw new Error(`la tabla de conservación solo trae ${rows} filas`);
      await legal.fill('#ct-q', 'cédula');
      if (!(await legal.$$eval('#tabla-conservacion tbody tr:not([hidden])', (r) => r.length))) throw new Error('el buscador de la tabla no filtra');
      await legal.goto(`${BASE}/app/legal/estado-del-servicio.html`);
      await legal.waitForSelector('#estado-servicio .es-component', { timeout: 10000 });
      const wide = await legal.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      if (wide) throw new Error('el tablero de estado se desborda en el teléfono');
    } finally {
      await legal.close();
    }
  });

  await t('centro legal: reporte público, solicitud ARCO con folio y seguimiento (sin cuenta)', async () => {
    // Otra pestaña sin sesión (los formularios no piden cuenta). Una IP propia por corrida para no chocar con el
    // límite por IP de los formularios públicos al repetir la prueba en local.
    const lctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const fakeIp = `10.77.${Math.floor(Math.random() * 250)}.${1 + Math.floor(Math.random() * 250)}`;
    await lctx.route('**/*', r => (r.request().url().startsWith(BASE)
      ? r.continue({ headers: { ...r.request().headers(), 'x-real-ip': fakeIp } }) : r.continue()));
    const legal = await lctx.newPage();
    legal.on('pageerror', e => errors.push('LEGAL PAGE ERROR: ' + e.message));
    const legalShot = name => legal.screenshot({ path: path.join(SHOTS, `${String(++step).padStart(2, '0')}-${name}.png`), fullPage: true });
    const mail = `legal${Date.now()}@pruebas.mx`;
    try {
      // Centro legal (hub)
      await legal.goto(`${BASE}/legal`);
      if (!/\/app\/legal\/$/.test(new URL(legal.url()).pathname)) throw new Error('/legal no abre el centro legal: ' + legal.url());
      if (!/Centro legal/i.test(await legal.textContent('h1'))) throw new Error('el centro legal no tiene su título');
      if ((await legal.$$('a[href$=".html"]')).length < 20) throw new Error('el centro legal no enlaza las páginas legales');
      await legal.click('#pfc-reject').catch(() => {});  // aviso de cookies de esta pestaña
      // Reporte público (moderacion.html)
      await legal.goto(`${BASE}/app/legal/moderacion.html`);
      const rep = legal.locator('#form-reporte-publico form.rep-form').first();
      await rep.locator('select[name=reason]').selectOption('spam');
      await rep.locator('[name=target_url]').fill(`${BASE}/app/?dog=1`);
      await rep.locator('[name=details]').fill('Publicación repetida muchas veces (prueba E2E).');
      await rep.locator('[name=email]').first().fill(mail);
      await rep.locator('button[type=submit]').first().click();
      await legal.waitForSelector('#form-reporte-publico .rep-folio strong', { timeout: 15000 });
      const repFolio = (await legal.textContent('#form-reporte-publico .rep-folio strong')).trim();
      if (!/^REP-/.test(repFolio)) throw new Error('folio de reporte inesperado: ' + repFolio);
      const repStatus = await legal.evaluate(async ([f, m]) => (await fetch(`/cumplimiento/reportes-publicos/${f}?email=${encodeURIComponent(m)}`)).status, [repFolio, mail]);
      if (repStatus !== 200) throw new Error('el reporte no se puede consultar con folio y correo: ' + repStatus);
      await legalShot('reporte-publico');
      // Solicitud ARCO sin cuenta (derechos-arco.html) y seguimiento con folio + correo
      await legal.goto(`${BASE}/app/legal/derechos-arco.html`);
      const arco = legal.locator('#form-solicitud form');
      await arco.locator('[name=nombre]').fill('Persona Prueba E2E');
      await arco.locator('[name=email]').fill(mail);
      await arco.locator('[name=tipo]').selectOption('acceso');
      await arco.locator('[name=descripcion]').fill('Quiero saber qué datos personales tienen de mí (prueba E2E).');
      await arco.locator('[name=acepta_privacidad]').check();
      await arco.locator('button[type=submit]').click();
      await legal.waitForSelector('#form-solicitud .sol-ack', { timeout: 15000 });
      const folio = (await legal.textContent('#form-solicitud .sol-folio strong')).trim();
      if (!/^PF-\d{4}-\d{5,}$/.test(folio)) throw new Error('folio ARCO inesperado: ' + folio);
      if (!/Fecha límite de respuesta/.test(await legal.textContent('#form-solicitud .sol-ack'))) throw new Error('el acuse no dice la fecha límite');
      const track = legal.locator('#seguimiento-folio form');
      if ((await track.locator('[name=folio]').inputValue()) !== folio) throw new Error('el seguimiento no quedó prellenado');
      await track.locator('button[type=submit]').click();
      await legal.waitForFunction(f => (document.querySelector('#seguimiento-folio .sol-result') || {}).textContent?.includes(f), folio, { timeout: 15000 });
      await legalShot('solicitud-arco-seguimiento');
    } finally {
      await lctx.close();
    }
  });

  await t('voluntario: enviar publicación de Facebook (share)', async () => {
    // Ayuda → «Botón para voluntarios»: bookmarklet javascript: armado con el origen de la app
    await page.click('[data-act="help"]');
    await active('help');
    await page.click('#help-volunteer > summary');
    const bm = await page.getAttribute('#volunteer-bookmarklet', 'href');
    if (!bm || !bm.startsWith('javascript:') || !decodeURIComponent(bm).includes(JSON.stringify(new URL(BASE).origin + '/app/'))) {
      throw new Error('bookmarklet inválido: ' + String(bm).slice(0, 80));
    }
    // Enlace del botón / share_target: abre «Enviar publicación» prellenado y limpia la URL
    const postUrl = 'https://www.facebook.com/groups/ejemplo/posts/1';
    await page.goto(BASE + '/app/?share=1&url=' + postUrl + '&text=Se%20perdio%20perrito');
    await active('share');
    if ((await page.inputValue('#sh-url')) !== postUrl) throw new Error('no se prellenó el enlace');
    if (!(await page.inputValue('#sh-text')).includes('Se perdio perrito')) throw new Error('no se prellenó el texto');
    if (new URL(page.url()).search) throw new Error('los parámetros siguen en la URL');
    if (!(await page.isVisible('#sh-type [data-v="lost"].on'))) throw new Error('no se detectó «Se perdió»');
    await page.waitForTimeout(800);
    if (!(await page.inputValue('#sh-state'))) await page.selectOption('#sh-state', 'Ciudad de México');
    await page.setInputFiles('[data-photos="sh"] + input', PHOTO);
    await page.check('#sh-consent');
    await shot('compartir-publicacion');
    // El enlace del prellenado ya existe en la base de corridas anteriores (409): para cubrir la creación (201)
    // se envía una publicación nueva en cada corrida
    const newPostUrl = `https://www.facebook.com/groups/ejemplo/posts/${Date.now()}`;
    await page.fill('#sh-url', newPostUrl);
    const [res] = await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === '/facebook/volunteer-import' && r.request().method() === 'POST', { timeout: 30000 }),
      page.click('#sh-submit'),
    ]);
    const sent = res.request().postDataJSON();
    if (sent.url !== newPostUrl || sent.report_type !== 'lost' || !sent.state || sent.consent !== true
      || !Array.isArray(sent.photos) || sent.photos.length !== 1) {
      throw new Error('cuerpo inesperado: ' + JSON.stringify(sent).slice(0, 200));
    }
    if (res.status() !== 201) throw new Error('POST /facebook/volunteer-import respondió ' + res.status());
    const created = await res.json();
    await page.waitForSelector('#share-done:not(.hidden)', { timeout: 20000 });
    const doneText = await page.textContent('#sh-done-text');
    if (!doneText.includes(`Creamos el reporte #${created.id}`)) throw new Error('pantalla final inesperada: ' + doneText.slice(0, 120));
    if (!(await page.isVisible('#sh-done-view'))) throw new Error('falta «Ver el reporte»');
    await page.waitForTimeout(600); await shot('compartir-gracias');
    // Detalle: etiqueta de contenido importado con enlace al original y «Soy el autor: retirar» (sin cuenta)
    await page.click('#sh-done-view');
    await active('report');
    await page.waitForSelector('#rp-imported', { timeout: 15000 });
    if ((await page.getAttribute('#rp-original', 'href')) !== newPostUrl) throw new Error('falta el enlace a la publicación original');
    if ((await page.getAttribute('#rp-original', 'rel') || '').indexOf('noopener') < 0) throw new Error('el enlace al original no lleva rel=noopener');
    // Contrato L-fb: «Soy el autor: retirar o reclamar» lleva al centro de solicitudes con el reporte prellenado
    const claimHref = await page.getAttribute('#rp-author-link', 'href') || '';
    if (!claimHref.startsWith('/app/legal/contenido-importado.html?report_id=') || !claimHref.endsWith('#form-solicitud')) throw new Error('falta el enlace «Soy el autor» al centro de solicitudes: ' + claimHref);
    if (!(await page.textContent('#rp-imported')).includes('Importado de una publicación pública; su autor no es usuario de GuauWoow')) throw new Error('falta la etiqueta de contenido importado');
    await page.click('#rp-author');
    await page.waitForSelector('#rp-author-form:not(.hidden)');
    await shot('contenido-importado-retiro');
    await toNav();
    await page.click('#nav .nav-item[data-go="profile"]');
    await active('profile');
  });

  await t('Perfil -> Preferencias: alertas cercanas apagadas hasta activarlas (K-PREF)', async () => {
    await page.click('[data-s="profile"] [data-act="preferences"]');
    await active('preferences');
    await page.waitForSelector('#pref-notify_nearby', { state: 'attached', timeout: 10000 });
    for (const p of ['notify_nearby', 'whatsapp_alerts', 'email_marketing']) {
      if (await page.isChecked('#pref-' + p)) throw new Error(p + ' debería venir apagado');
    }
    const isPatch = r => new URL(r.url()).pathname === '/cumplimiento/preferencias' && r.request().method() === 'PATCH';
    const [res] = await Promise.all([page.waitForResponse(isPatch, { timeout: 10000 }), page.click('label[for="pref-notify_nearby"]')]);
    if (!res.ok()) throw new Error('PATCH /cumplimiento/preferencias respondió ' + res.status());
    const prefs = await res.json();
    if (prefs.notify_nearby !== true) throw new Error('notify_nearby no cambió en el servidor');
    await shot('preferencias');
    await page.waitForFunction(() => !document.querySelector('#pref-notify_nearby').disabled);
    await Promise.all([page.waitForResponse(isPatch, { timeout: 10000 }), page.click('label[for="pref-notify_nearby"]')]);
    await page.click('[data-s="preferences"] .nav-back');
    await active('profile');
  });

  await t('botón "cerrar sesión en todos los dispositivos"', async () => {
    await page.waitForSelector('#logout-all-btn', { state: 'visible', timeout: 10000 });
    const txt = await page.textContent('#logout-all-btn');
    if (!/todos los dispositivos/i.test(txt)) throw new Error('texto inesperado: ' + txt);
  });

  await t('cuenta: contraseña y exportar', async () => {
    await page.click('#nav .nav-item[data-go="profile"]');
    await active('profile');
    await page.click('[data-act="password"]');
    await page.fill('#pw-current', 'Patitas123!');
    await page.fill('#pw-new', 'Patitas456!');
    await page.fill('#pw-new2', 'Patitas456!');
    await page.click('#password-form button[type=submit]');
    await page.waitForSelector('#password-modal:not(.open)', { state: 'attached', timeout: 10000 });
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }), page.click('[data-act="export"]')]);
    if (!(await dl.suggestedFilename()).endsWith('.json')) throw new Error('export no es JSON');
  });

  await t('tienda: panel del vendedor (Mi tienda)', async () => {
    // El usuario del E2E registra un refugio (rol "refuge") y, con la cuenta de admin, se aprueba por API
    const reg = await page.evaluate(async () => {
      try { return await api('/refuges/register', { method: 'POST', body: { name: `Refugio E2E ${Date.now() % 100000}`, description: 'Refugio de prueba del E2E', city: 'Guadalajara', country: 'México' } }); }
      catch (e) { return { error: e.message }; }
    });
    if (reg.error) throw new Error('registro del refugio: ' + reg.error);
    let approved = false;
    if (ADMIN_EMAIL && ADMIN_PASSWORD) {
      const login = await fetch(BASE + '/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ username: ADMIN_EMAIL, password: ADMIN_PASSWORD }) });
      if (!login.ok) throw new Error('login de admin respondió ' + login.status);
      const { access_token } = await login.json();
      const ap = await fetch(`${BASE}/admin/refuges/${reg.id}/approve`, { method: 'POST', headers: { Authorization: `Bearer ${access_token}` } });
      if (!ap.ok) throw new Error('aprobar el refugio respondió ' + ap.status);
      approved = true;
    }
    await toNav();
    await page.click('#nav .nav-item[data-go="home"]');
    await page.click('#nav .nav-item[data-go="profile"]');
    await active('profile');
    await page.waitForSelector('[data-act="my-shop"]', { timeout: 10000 });
    await page.click('[data-act="my-shop"]');
    await active('my-shop');
    if (!approved) {
      await page.waitForSelector('#ms-body .empty', { timeout: 10000 });
      await shot('mi-tienda-en-revision');
      results.push(['AVISO', 'Mi tienda: sin E2E_ADMIN_EMAIL/E2E_ADMIN_PASSWORD el refugio queda en revisión y no se prueban las pestañas']);
      await page.click('[data-s="my-shop"] .nav-back');  // los pasos siguientes usan la barra de navegación
      return;
    }
    await page.waitForSelector('#ms-tabs:not(.hidden) [data-ms-tab="productos"].on', { timeout: 10000 });
    await page.waitForSelector('#ms-add-product', { timeout: 10000 });
    await page.waitForTimeout(500); await shot('mi-tienda');
    // Alta de producto con costo de envío y estados atendidos; después se da de baja
    await page.click('#ms-add-product');
    await page.waitForSelector('#product-modal.open');
    await page.setInputFiles('[data-photos="pm"] + input', PHOTO);
    await page.fill('#pm-name', 'Placa QR E2E');
    await page.fill('#pm-desc', 'Placa de identificación con código QR (prueba E2E)');
    await page.fill('#pm-price', '149');
    await page.fill('#pm-stock', '3');
    await page.fill('#pm-shipping', '60');
    await page.fill('#pm-handling', '2');
    // Categoría de la lista de productos permitidos (obligatoria; las de esta clave no se retienen para revisión)
    await page.selectOption('#pm-category', 'accesorios_juguetes');
    await page.click('label[for="pm-nationwide"]');
    await page.waitForSelector('#pm-states-wrap:not(.hidden)');
    await page.click('#product-form button[type=submit]'); await toastIs(/al menos un estado/);
    await page.click('#pm-states .chip[data-state="Jalisco"]');
    await page.click('#pm-states .chip[data-state="México"]');
    await shot('mi-tienda-producto');
    const [pr] = await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === '/products' && r.request().method() === 'POST', { timeout: 20000 }),
      page.click('#product-form button[type=submit]'),
    ]);
    if (pr.status() !== 201) throw new Error(`POST /products respondió ${pr.status()}: ${(await pr.text()).slice(0, 200)}`);
    const prod = await pr.json();
    await page.waitForSelector(`[data-edit-product="${prod.id}"]`, { timeout: 10000 });
    if ('ships_states' in prod && !(prod.ships_states || []).includes('Jalisco')) throw new Error('el producto no guardó los estados de envío');
    await page.click(`[data-edit-product="${prod.id}"]`);
    await page.waitForSelector('#product-modal.open #pm-delete:not(.hidden)');
    await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === `/products/${prod.id}` && r.request().method() === 'DELETE', { timeout: 10000 }),
      page.click('#pm-delete'),
    ]);
    // Pestañas: pedidos, facturas, datos fiscales (con validación de RFC), cobros y estado de cuenta
    const tab = async (k, sel) => { await page.click(`#ms-tabs [data-ms-tab="${k}"]`); await page.waitForSelector(sel, { timeout: 10000 }); };
    await tab('pedidos', '#ms-orders > p, #ms-orders > .card');
    await tab('facturas', '#ms-body .h2, #ms-body > p');
    await tab('fiscal', '#fiscal-form, #ms-body > p');
    if (await page.$('#fiscal-form')) {
      await page.fill('#fp-rfc', 'XYZ');
      await page.click('#fp-save'); await toastIs(/RFC v[aá]lido/);
      await shot('mi-tienda-fiscal');
    }
    await tab('cobros', '#mp-status, #ms-body > p');
    await shot('mi-tienda-cobros');
    await tab('cuenta', '#ms-period');
    await page.waitForSelector('#ms-stmt > p, #ms-stmt .sum', { timeout: 10000 });
    await shot('mi-tienda-estado-de-cuenta');
    await page.click('[data-s="my-shop"] .nav-back');
  });

  await t('logout', async () => {
    await page.click('#nav .nav-item[data-go="profile"]');
    await page.click('#logout-btn');
    await active('auth');
  });

  await t('eliminar cuenta', async () => {
    await page.fill('#auth-email', email);
    await page.fill('#auth-password', 'Patitas456!');
    await page.click('#auth-submit');
    await active('home');
    await page.click('#nav .nav-item[data-go="profile"]');
    await page.click('#delete-account-btn');
    await page.fill('#del-pass', 'Patitas456!');
    await page.fill('#del-confirm', 'ELIMINAR');
    await shot('eliminar-cuenta');
    await page.click('#delete-form button[type=submit]');
    await active('auth');
    await page.fill('#auth-email', email);
    await page.fill('#auth-password', 'Patitas456!');
    expectLogin401 = true;
    await page.click('#auth-submit');
    await page.waitForTimeout(2000);
    if (await page.isVisible('[data-s="home"].active')) throw new Error('la cuenta eliminada todavía puede entrar');
  });

  await browser.close();
  console.log('\n=== RESULTADOS ===');
  results.forEach(r => console.log(r.join(' | ')));
  console.log('\n=== ERRORES DE CONSOLA ===');
  console.log(errors.length ? errors.join('\n') : '(ninguno)');
  if (shopPending.size) console.log('\n=== AVISO: endpoints de la tienda que respondieron 404 ===\n' + [...shopPending].join('\n'));
  if (legalPending.size) console.log('\n=== AVISO: páginas legales todavía sin generar ===\n' + [...legalPending].join('\n'));
  if (results.some(r => r[0] === 'FAIL') || errors.length) process.exitCode = 1;
}

run();
