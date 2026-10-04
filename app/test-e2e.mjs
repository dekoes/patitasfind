// E2E de PatitasFind: recorre la app real contra el backend local.
// Uso: BASE=http://localhost:8082 node test-e2e.mjs   (capturas en ./e2e-shots)
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:8082';
const SHOTS = path.resolve('e2e-shots');
const PHOTO = process.env.PHOTO || path.resolve('../backend/uploads', fs.readdirSync('../backend/uploads').find(f => f.endsWith('.jpg')));
fs.mkdirSync(SHOTS, { recursive: true });

const errors = [];
let step = 0;
const results = [];

async function run() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, geolocation: { latitude: 19.4326, longitude: -99.1332 }, permissions: ['geolocation'] });
  const page = await ctx.newPage();
  page.on('pageerror', e => errors.push('PAGE ERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !/favicon|tile\.openstreetmap|nominatim/.test(m.text())) errors.push('CONSOLE: ' + m.text()); });
  page.on('dialog', d => d.accept());

  const shot = async name => page.screenshot({ path: path.join(SHOTS, `${String(++step).padStart(2, '0')}-${name}.png`) });
  const active = s => page.waitForSelector(`[data-s="${s}"].active`, { timeout: 15000 });
  const t = async (name, fn) => {
    try { await fn(); results.push(['OK', name]); }
    catch (e) { console.log('FAIL', name, e.message.split('\n')[0]); results.push(['FAIL', name, e.message.split('\n')[0]]); await shot('FAIL-' + name.replace(/\W+/g, '_')); }
  };
  const email = `e2e${Date.now()}@patitasfind.mx`;

  await t('splash + onboarding', async () => {
    await page.goto(BASE + '/app/');
    await page.waitForTimeout(700); await shot('splash');
    await active('onboarding'); await shot('onboarding');
    await page.click('#ob-skip');
    await active('auth');
  });

  await t('registro', async () => {
    await page.click('#auth-toggle');
    await page.fill('#auth-name', 'Prueba E2E');
    await page.fill('#auth-email', email);
    await page.fill('#auth-password', 'Patitas123!');
    await page.fill('#auth-phone', '55' + String(Date.now()).slice(-8));
    await page.check('#auth-terms');
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

  await t('tienda + pedido', async () => {
    await page.click('[data-s="map"] .nav-back');
    await page.click('#home-shop');
    await active('shop');
    await page.waitForTimeout(1000); await shot('tienda');
    const add = await page.$('[data-add]:not([disabled])');
    if (!add) throw new Error('No hay productos con stock');
    await add.click();
    await page.click('#cart-btn');
    await page.fill('#cart-address', 'Av. Álvaro Obregón 123, Roma Norte, 06700 CDMX');
    await shot('carrito');
    await page.click('#cart-checkout');
    await page.waitForSelector('[data-s="list"].active, #success-pop.show', { timeout: 15000 });
    await page.waitForTimeout(2000); await shot('pedido');
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
    await page.click('#auth-submit');
    await page.waitForTimeout(2000);
    if (await page.isVisible('[data-s="home"].active')) throw new Error('la cuenta eliminada todavía puede entrar');
  });

  await browser.close();
  console.log('\n=== RESULTADOS ===');
  results.forEach(r => console.log(r.join(' | ')));
  console.log('\n=== ERRORES DE CONSOLA ===');
  console.log(errors.length ? errors.join('\n') : '(ninguno)');
  if (results.some(r => r[0] === 'FAIL') || errors.length) process.exitCode = 1;
}

run();
