/* ============================================================
   GuauWoow — App web (SPA sin framework)
   ============================================================ */
'use strict';

const API = '';
const $ = (s, c = document) => c.querySelector(s);
const $$ = (s, c = document) => [...c.querySelectorAll(s)];
const device = $('#device');

const CITIES = [
  ['Ciudad de México', 19.4326, -99.1332], ['Guadalajara', 20.6597, -103.3496], ['Monterrey', 25.6866, -100.3161],
  ['Puebla', 19.0414, -98.2063], ['Querétaro', 20.5888, -100.3899], ['Tijuana', 32.5149, -117.0382],
  ['Mérida', 20.9674, -89.5926], ['León', 21.1250, -101.6860], ['Cancún', 21.1619, -86.8515], ['Toluca', 19.2826, -99.6557],
];
const SPLASH_TIPS = [
  'Los perros perdidos suelen alejarse hasta 3.5 km 🐾',
  'Una foto clara de la cara aumenta las coincidencias',
  'Adoptar libera un lugar en el refugio para otro rescate',
  'Placa con tu teléfono = reencuentro más rápido',
];
const NAV_SCREENS = ['home', 'chat-list', 'notifications', 'profile', 'shop'];
const STATUS_LABEL = {
  available: 'Disponible', adopted: 'Adoptado', in_foster: 'En casa de paso', unavailable: 'No disponible', in_process: 'En proceso',
  pending_application: 'Pendiente', approved: 'Aprobada', rejected: 'Rechazada', completed: '¡Adoptado!',
  active: 'Activo', resolved: 'Resuelto', pending: 'En revisión', created: 'Creado', pending_payment: 'Pago pendiente', paid: 'Pagado', cancelled: 'Cancelado',
  expired: 'Expirado', shipped: 'Enviado', delivered: 'Entregado', closed: 'Cerrado',
};

const state = {
  token: localStorage.getItem('patitas_token') || '',
  me: null,
  config: { google_enabled: false, demo_enabled: false, otp_enabled: false, payments_enabled: false, ai_enabled: false, shop_enabled: true, support_email: null, support_whatsapp: null },
  coords: JSON.parse(localStorage.getItem('patitas_coords') || 'null'),
  city: localStorage.getItem('patitas_city') || 'Ciudad de México',
  country: 'México',
  cart: JSON.parse(localStorage.getItem('patitas_cart') || '[]'),
  deck: [], deckIdx: 0, deckSize: '',
  matchId: null, matchDog: null,
  conv: null, ws: null, wsAttempt: 0, wsRetry: null, typingTimer: null, lastTypingSent: 0,
  reportType: 'lost', psType: '', psFile: null,
  products: [], authMode: 'login', resetToken: null,
  map: null, mapLayers: {},
};

/* ============================================================
   Utilidades
   ============================================================ */
function esc(t) { return String(t ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function parseDate(iso) { if (!iso) return null; return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z'); }
function timeAgo(iso) {
  const d = parseDate(iso); if (!d) return '';
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'hace un momento';
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  if (s < 604800) return `hace ${Math.floor(s / 86400)} d`;
  return d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
}
function fmtDate(iso) { const d = parseDate(iso); return d ? d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }
function fmtTime(iso) { const d = parseDate(iso); return d ? d.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' }) : ''; }
function money(n) { return '$' + Number(n || 0).toLocaleString('es-MX', { minimumFractionDigits: 0, maximumFractionDigits: 2 }); }
function age(y, m) {
  const p = [];
  if (y) p.push(`${y} año${y > 1 ? 's' : ''}`);
  if (m) p.push(`${m} mes${m > 1 ? 'es' : ''}`);
  return p.join(' y ') || 'Sin dato';
}
function dist(km) { if (km == null) return ''; return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`; }
function initials(n) { return (n || '?').trim().split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase(); }
function photo(o) { return (o && o.photos && o.photos.length) ? o.photos[0] : ''; }
/* Solo se usan en src/href rutas /uploads/ del sitio, blob: (vistas previas locales) y https: */
function safeUrl(u) {
  const s = String(u ?? '').trim();
  return /^(\/uploads\/|blob:|https:\/\/)[^\s"'<>`]+$/i.test(s) ? s : '';
}
/* Miniatura que genera el backend: /uploads/<nombre>.<ext> -> /uploads/<nombre>_thumb.jpg */
function thumbUrl(u) {
  const s = safeUrl(u);
  return /^\/uploads\/[^/]+\.(jpe?g|png|webp)$/i.test(s) && !/_thumb\.jpg$/i.test(s) ? s.replace(/\.(jpe?g|png|webp)$/i, '_thumb.jpg') : s;
}
/* <img> perezosa; con thumb usa la miniatura y data-full para volver a la imagen completa si falla
   (lo hace un listener global de "error": la CSP no permite onerror en línea) */
function imgTag(src, { thumb = true, alt = '', id = '' } = {}) {
  const full = safeUrl(src);
  if (!full) return '';
  const shown = thumb ? thumbUrl(full) : full;
  return `<img${id ? ` id="${id}"` : ''} src="${esc(shown)}"${shown !== full ? ` data-full="${esc(full)}"` : ''} alt="${esc(alt)}" loading="lazy" decoding="async">`;
}
function avatarHtml(u, size = 46) {
  const st = `width:${size}px;height:${size}px`;
  const img = u && imgTag(u.avatar_url);
  if (img) return `<div class="avatar" style="${st}">${img}</div>`;
  return `<div class="avatar" style="${st}">${esc(initials(u && u.full_name))}</div>`;
}
function imgOrDog(src, size = 40) { return imgTag(src) || `<svg width="${size}" height="${size}"><use href="#dogface"/></svg>`; }
function shopOn() { return state.config.shop_enabled !== false; }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function locParams(extra = {}) {
  const p = new URLSearchParams();
  if (state.coords) { p.set('lat', state.coords.lat); p.set('lon', state.coords.lon); }
  else if (state.city) p.set('city', state.city);
  Object.entries(extra).forEach(([k, v]) => { if (v !== '' && v != null) p.set(k, v); });
  return p.toString();
}

let toastTimer;
function toast(msg, type = 'info') {
  const t = $('#toast');
  $('#toast-msg').textContent = msg;
  t.className = type === 'error' ? 'err' : type === 'ok' ? 'ok' : '';
  void t.offsetWidth;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let body = opts.body;
  if (body && !(body instanceof FormData) && !(body instanceof URLSearchParams) && typeof body !== 'string') {
    body = JSON.stringify(body);
    headers['Content-Type'] = 'application/json';
  }
  let res;
  try { res = await fetch(API + path, { method: opts.method || 'GET', headers, body }); }
  catch { throw new Error('Sin conexión. Revisa tu internet 🐾'); }
  if (res.status === 401 && !opts.noLogout) {
    sessionExpired();
    const err = new Error('Tu sesión expiró. Vuelve a entrar 🐾');
    err.status = 401;
    throw err;
  }
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  // Si no es JSON (p. ej. la página de error de Nginx) no se muestra tal cual al usuario
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map(e => e.msg).join(', ');
    if (typeof d !== 'string' || !d) {
      d = res.status === 429 ? 'Vas muy rápido 🐾 Espera un momento e inténtalo de nuevo.'
        : res.status >= 500 ? 'Algo falló de nuestro lado. Inténtalo de nuevo en un momento.' : `Error ${res.status}`;
    }
    const err = new Error(d);
    err.status = res.status;
    err.code = data && data.code;
    err.data = data;  // cuerpo del error (p. ej. report_id de una publicación ya enviada)
    if (err.code === 'phone_verification_required' && !opts.noVerifyRedirect && current !== 'verify-phone') {
      setTimeout(() => startPhoneVerify(), 50);
      err.message = 'Primero verifica tu teléfono 📲';
    }
    // Edad (verificación reforzada o fecha de nacimiento) y anexos de aliados: cumplimiento.js abre la ventana
    if (err.code && window.Cumplimiento) Cumplimiento.onApiError(err);
    throw err;
  }
  return data;
}

/* Reduce las fotos en el teléfono antes de subirlas: máximo 1600 px, JPEG ~0.85, respetando la
   orientación EXIF. Al volver a codificar también se descartan los metadatos (GPS). */
const MAX_PHOTO_PX = 1600;
const shrunkCache = new WeakMap();
function loadImgEl(file) {
  return new Promise((ok, fail) => {
    const url = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => { URL.revokeObjectURL(url); ok(im); };
    im.onerror = () => { URL.revokeObjectURL(url); fail(new Error('imagen')); };
    im.src = url;
  });
}
async function shrinkImage(file, maxPx = MAX_PHOTO_PX) {
  if (!file || !file.type || !file.type.startsWith('image/') || file.type === 'image/gif') return file;
  const key = shrunkCache.get(file);
  if (key && key.maxPx === maxPx) return key.out;
  let out = file;
  try {
    let src = null;
    if (window.createImageBitmap) {
      try { src = await createImageBitmap(file, { imageOrientation: 'from-image' }); } catch { src = null; }
    }
    if (!src) src = await loadImgEl(file);  // <img> ya aplica la orientación EXIF en navegadores actuales
    const w = src.width || src.naturalWidth, h = src.height || src.naturalHeight;
    const k = Math.min(1, maxPx / Math.max(w, h));
    const cw = Math.max(1, Math.round(w * k)), ch = Math.max(1, Math.round(h * k));
    const canvas = document.createElement('canvas');
    canvas.width = cw; canvas.height = ch;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cw, ch);
    ctx.drawImage(src, 0, 0, cw, ch);
    if (src.close) src.close();
    const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.85));
    if (blob && blob.size) out = new File([blob], (file.name || 'foto').replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg', lastModified: Date.now() });
  } catch { out = file; }
  shrunkCache.set(file, { maxPx, out });
  return out;
}

async function uploadFiles(files) {
  if (!files || !files.length) return [];
  const fd = new FormData();
  (await Promise.all(files.map(f => shrinkImage(f)))).forEach(f => fd.append('files', f));
  const data = await api('/upload/multiple', { method: 'POST', body: fd });
  return data.urls || [];
}

/* Documentos privados del refugio (C2): cada archivo va a POST /upload/document y se guarda su id.
   Las fotos de documentos se reducen menos (2400 px) para que sigan siendo legibles. */
async function uploadDocuments(files) {
  const ids = [];
  for (const f of files || []) {
    const isPdf = f.type === 'application/pdf' || /\.pdf$/i.test(f.name || '');
    const fd = new FormData();
    fd.append('file', isPdf ? f : await shrinkImage(f, 2400));
    try {
      const r = await api('/upload/document', { method: 'POST', body: fd });
      ids.push(r.id);
    } catch (e) {
      // Servidor sin el endpoint todavía: las fotos se suben como antes, los PDF no se pueden
      if (e.status !== 404 || e.message !== 'Not Found') throw e;
      if (isPdf) throw new Error('Por ahora solo puedes subir fotos de tus documentos');
      ids.push(...await uploadFiles([f]));
    }
  }
  return ids;
}

// fn puede devolver KEEP_LOADING cuando ya se va a otra página (p. ej. Mercado Pago): el botón sigue ocupado y un
// segundo clic no crea otro donativo pendiente mientras el navegador cambia de página.
const KEEP_LOADING = Symbol('keep-loading');
async function withBtn(btn, fn) {
  if (btn.dataset.busy === '1') return;
  btn.dataset.busy = '1';
  FX.setLoading(btn, true);
  let keep = false;
  try { const r = await fn(); keep = r === KEEP_LOADING; return r; }
  catch (e) { toast(e.message, 'error'); }
  finally { if (!keep) { FX.setLoading(btn, false); delete btn.dataset.busy; } }
}
// Al volver con «Atrás» desde Mercado Pago (caché del navegador) el botón no se queda ocupado
window.addEventListener('pageshow', (ev) => {
  if (!ev.persisted) return;
  $$('[data-busy="1"]').forEach((b) => { FX.setLoading(b, false); delete b.dataset.busy; });
  FX.hideLoading && FX.hideLoading();
});

function getPosition(timeout = 8000) {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error('Tu navegador no permite ubicación'));
    navigator.geolocation.getCurrentPosition(
      p => resolve({ lat: +p.coords.latitude.toFixed(5), lon: +p.coords.longitude.toFixed(5) }),
      () => reject(new Error('No pudimos obtener tu ubicación. Revisa los permisos')),
      { enableHighAccuracy: true, timeout, maximumAge: 60000 });
  });
}
async function reverseGeocode(c) {
  try {
    const r = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${c.lat}&lon=${c.lon}&zoom=14&accept-language=es`);
    const d = await r.json();
    const a = d.address || {};
    return { area: a.suburb || a.neighbourhood || a.city_district || '', city: a.city || a.town || a.state || '', state: a.state || '', country: a.country || 'México' };
  } catch { return null; }
}

/* ============================================================
   Navegación
   ============================================================ */
const screens = {};
$$('.screen').forEach(s => { screens[s.dataset.s] = s; });
let current = 'splash';
let stack = [];

function navigate(name, opts = {}) {
  if (!screens[name]) return;
  if (name === 'shop' && !shopOn()) { toast('La tienda no está disponible por ahora.', 'error'); return; }
  if (name !== current) track('$pageview', { $current_url: `${location.origin}/app/#${name}`, screen: name });
  const prev = screens[current];
  const next = screens[name];
  if (name === current) { onEnter(name, opts); return; }
  if (opts.push !== false && !opts.back && current !== 'splash') stack.push(current);
  if (opts.reset) stack = [];
  if (opts.back) {
    next.style.transition = 'none';
    next.classList.add('enter-back');
    void next.offsetWidth;
    next.style.transition = '';
    next.classList.remove('enter-back');
  } else if (prev) {
    prev.classList.add('leave-left');
    setTimeout(() => prev.classList.remove('leave-left'), 450);
  }
  prev && prev.classList.remove('active');
  next.classList.add('active');
  current = name;
  if (name !== 'chat') closeWS();
  updateNav(name);
  onEnter(name, opts);
}
function back() {
  const prev = stack.pop();
  navigate(prev || (state.me ? 'home' : 'auth'), { back: true, push: false });
}

function updateNav(name) {
  const nav = $('#nav');
  const show = NAV_SCREENS.includes(name);
  nav.classList.toggle('hidden', !show);
  if (!show) return;
  let active = null;
  $$('.nav-item', nav).forEach(i => { const on = i.dataset.go === name; i.classList.toggle('on', on); if (on) active = i; });
  const ind = $('#nav-ind');
  if (active) {
    ind.style.opacity = 1;
    ind.style.left = (active.offsetLeft + active.offsetWidth / 2 - 7) + 'px';
    const svg = ind.querySelector('svg'); svg.style.animation = 'none'; void svg.offsetWidth; svg.style.animation = '';
  } else ind.style.opacity = 0;
}

function onEnter(name, opts) {
  const fn = {
    home: loadHome, discover: loadDiscover, 'chat-list': loadChatList, notifications: loadNotifications,
    profile: loadProfile, shop: loadShop, ranking: loadRanking, map: loadMap, 'edit-profile': loadEditProfile,
    'my-refuge': loadMyRefuge, appearance: () => Theme.mount($('#appearance-body')), help: loadHelp,
  }[name] || (window.screenLoaders || {})[name];  // pantallas de módulos aparte (p. ej. veterinarias.js)
  if (fn) fn(opts);
  FX.decorate(screens[name]);
}

/* ============================================================
   Splash / Onboarding / Auth
   ============================================================ */
function runSplash() {
  $('#splash-title').innerHTML = [...'GuauWoow'].map((c, i) => `<span style="--i:${i}">${c}</span>`).join('');
  $('#splash-run').innerHTML = FX.runDog();
  const steps = $('#splash-steps');
  for (let i = 0; i < 9; i++) steps.insertAdjacentHTML('beforeend', `<i style="left:${8 + i * 10}%;bottom:${i % 2 ? 22 : 8}px;transform:rotate(90deg);animation-delay:${i * .45}s">${FX.PAW}</i>`);
  let t = 0;
  const tip = $('#splash-tip');
  tip.textContent = SPLASH_TIPS[Math.floor(Math.random() * SPLASH_TIPS.length)];
  const bar = $('#splash-bar');
  const iv = setInterval(() => { t = Math.min(92, t + FX.rand(6, 16)); bar.style.width = t + '%'; }, 220);
  return () => { clearInterval(iv); bar.style.width = 'calc(100% - 4px)'; };
}

let obIdx = 0;
function showOnboarding() {
  $('#ob-art-0').innerHTML = FX.sniffDog();
  $('#ob-art-1').innerHTML = FX.dogFace(150);
  $('#ob-art-2').innerHTML = FX.bone('#fff', 120, 'bone-spin');
  navigate('onboarding', { push: false });
}
function obGo(i) {
  if (i > 2) { localStorage.setItem('patitas_onboarded', '1'); return showAuth('login'); }
  obIdx = i;
  $$('.ob-slide').forEach(s => { const n = +s.dataset.i; s.classList.toggle('on', n === i); s.classList.toggle('past', n < i); });
  $$('#ob-dots i').forEach((d, n) => d.classList.toggle('on', n === i));
  $('#ob-next .btn-label').textContent = i === 2 ? '¡Comenzar!' : 'Siguiente';
}

function showAuth(mode = 'login') {
  setAuthMode(mode);
  $('#auth-dog').innerHTML = FX.dogFace(96);
  navigate('auth', { push: false, reset: true });
}
function setAuthMode(mode) {
  state.authMode = mode;
  const reg = mode === 'register', login = mode === 'login', forgot = mode === 'forgot', reset = mode === 'reset';
  $('#f-name').classList.toggle('hidden', !reg);
  $('#f-phone').classList.toggle('hidden', !reg);
  $('#f-consent').classList.toggle('hidden', !reg);
  $('#f-email').classList.toggle('hidden', reset);
  $('#f-pass').classList.toggle('hidden', forgot);
  $('#f-forgot').classList.toggle('hidden', !login);
  $('#f-toggle').classList.toggle('hidden', forgot || reset);
  $('#f-back').classList.toggle('hidden', !(forgot || reset));
  $('#f-social').classList.toggle('hidden', forgot || reset);
  $('#google-login').classList.toggle('hidden', !state.config.google_enabled);
  $('#demo-login').classList.toggle('hidden', !state.config.demo_enabled);
  $('#auth-password').autocomplete = login ? 'current-password' : 'new-password';
  const T = {
    login: ['¡Hola de nuevo!', 'Inicia sesión para seguir ayudando', 'Entrar'],
    register: ['Únete a la manada', 'Crea tu cuenta gratis en segundos', 'Crear cuenta'],
    forgot: ['¿Olvidaste tu contraseña?', 'Te enviamos un enlace para crear una nueva', 'Enviar enlace'],
    reset: ['Nueva contraseña', 'Elige una contraseña de al menos 8 caracteres', 'Guardar contraseña'],
  }[mode];
  $('#auth-title').textContent = T[0];
  $('#auth-sub').textContent = T[1];
  const lbl = $('#auth-submit .btn-label');
  (lbl || $('#auth-submit')).textContent = T[2];
  $('#auth-toggle-text').textContent = reg ? '¿Ya tienes cuenta?' : '¿No tienes cuenta?';
  $('#auth-toggle').textContent = reg ? 'Inicia sesión' : 'Regístrate';
}

async function setToken(tk) {
  state.token = tk;
  localStorage.setItem('patitas_token', tk);
  state.me = await api('/users/me');
  if (state.me.latitude != null && !state.coords) setCoords({ lat: state.me.latitude, lon: state.me.longitude }, state.me.city);
  else if (state.me.city && !localStorage.getItem('patitas_city')) state.city = state.me.city;
}

async function submitAuth(e) {
  e.preventDefault();
  const btn = $('#auth-submit');
  const email = $('#auth-email').value.trim().toLowerCase();
  const password = $('#auth-password').value;
  const mode = state.authMode;
  if (mode !== 'reset' && !/^\S+@\S+\.\S+$/.test(email)) return toast('Escribe un correo válido', 'error');
  if ((mode === 'register' || mode === 'reset') && password.length < 8) return toast('La contraseña debe tener al menos 8 caracteres', 'error');
  if (mode === 'login' && !password) return toast('Escribe tu contraseña', 'error');

  await withBtn(btn, async () => {
    if (mode === 'forgot') {
      const r = await api('/auth/forgot-password', { method: 'POST', body: { email } });
      if (r && r.dev_link) console.info('Enlace de recuperación (dev):', r.dev_link);
      toast('Si el correo existe, te llegará un enlace 📬', 'ok');
      setAuthMode('login');
      return;
    }
    if (mode === 'reset') {
      await api('/auth/reset-password', { method: 'POST', body: { token: state.resetToken, password } });
      state.resetToken = null;
      toast('¡Listo! Ya puedes entrar con tu nueva contraseña', 'ok');
      setAuthMode('login');
      return;
    }
    if (mode === 'register') {
      const full_name = $('#auth-name').value.trim();
      const phone = $('#auth-phone').value.trim();
      if (full_name.length < 2) throw new Error('Escribe tu nombre');
      if (phone.replace(/\D/g, '').length < 10) throw new Error('Escribe tu celular a 10 dígitos');
      if (!$('#auth-terms').checked) throw new Error('Para crear tu cuenta acepta los Términos y el Aviso de Privacidad');
      // Fecha de nacimiento + casilla separada «Declaro que tengo 18 años o más» (cumplimiento.js)
      const age = window.Cumplimiento ? Cumplimiento.signupPayload() : {};
      const tk = await api('/auth/register', { method: 'POST', body: {
        email, password, full_name, phone, city: state.city, country: state.country,
        accepted_terms: true, marketing_opt_in: $('#auth-marketing').checked, ...age,
      }, noLogout: true });
      await setToken(tk.access_token);
      track('signup', { method: 'email' });
      await FX.success(`¡Bienvenido, ${state.me.full_name.split(' ')[0]}!`, 'Solo falta verificar tu celular 📲');
      return startPhoneVerify();
    }
    const form = new URLSearchParams({ username: email, password });
    let tk = await api('/auth/login', { method: 'POST', body: form, headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, noLogout: true });
    if (tk && tk.mfa_required) {
      // Personal administrador: verificación en dos pasos (el alta se hace en el panel /admin/)
      if (tk.mfa_enrollment_required) { location.href = `/admin/#mfa=${encodeURIComponent(tk.mfa_token)}&enroll=1`; return; }
      const code = (prompt('Escribe el código de 6 dígitos de tu app de autenticación (o un código de recuperación):') || '').trim();
      if (!code) throw new Error('Necesitas el código de tu app de autenticación para entrar');
      tk = await api('/auth/mfa/verify', { method: 'POST', body: { mfa_token: tk.mfa_token, code }, noLogout: true });
    }
    await setToken(tk.access_token);
    toast(`¡Hola, ${state.me.full_name.split(' ')[0]}! 🐶`, 'ok');
    afterLogin();
  });
}

async function demoLogin() {
  await withBtn($('#demo-login'), async () => {
    const tk = await api('/auth/demo-login', { method: 'POST', noLogout: true });
    await setToken(tk.access_token);
    toast('Entraste en modo demo 🐶', 'ok');
    afterLogin();
  });
}

function logout(silent = false) {
  state.token = ''; state.me = null; state.conv = null;
  try { window.posthog && posthog.reset(); } catch { }
  localStorage.removeItem('patitas_token');
  stopPolling();
  closeWS();
  $$('.modal.open').forEach(m => m.classList.remove('open'));
  FX.hideLoading();
  updateEmailBanner();
  if (!silent) toast('Sesión cerrada. ¡Vuelve pronto! 👋');
  showAuth('login');
}
/* Cualquier 401 (token vencido, contraseña cambiada o "cerrar sesión en todos lados") saca al usuario una sola vez */
function sessionExpired() {
  if (!state.token) return;
  logout(true);
  toast('Tu sesión expiró. Vuelve a entrar 🐾', 'error');
}
async function logoutAll(btn) {
  if (!confirm('¿Cerrar tu sesión en todos tus dispositivos, incluido este?')) return;
  await withBtn(btn, async () => {
    await api('/auth/logout-all', { method: 'POST', noLogout: true });
    logout(true);
    toast('Cerramos tu sesión en todos tus dispositivos 🔒', 'ok');
  });
}

/* ---------- verificación de correo (aviso no bloqueante) ---------- */
const EMAIL_SNOOZE_KEY = 'patitas_email_banner';
function updateEmailBanner() {
  const b = $('#email-banner');
  if (!b) return;
  let until = 0;
  try { until = +localStorage.getItem(EMAIL_SNOOZE_KEY) || 0; } catch { }
  const show = !!(state.me && state.me.email_verified === false && Date.now() > until);
  b.classList.toggle('hidden', !show);
  if (show) $('#email-banner-addr').textContent = state.me.email;
}
function snoozeEmailBanner() {
  try { localStorage.setItem(EMAIL_SNOOZE_KEY, String(Date.now() + 3 * 86400000)); } catch { }
  updateEmailBanner();
}
async function resendVerification() {
  try {
    const r = await api('/auth/resend-verification', { method: 'POST' });
    if (r && r.email_verified) {
      if (state.me) state.me.email_verified = true;
      updateEmailBanner();
      return toast('Tu correo ya está verificado ✅', 'ok');
    }
    if (r && r.dev_link) console.info('Enlace de verificación (dev):', r.dev_link);
    toast('Te enviamos un nuevo enlace. Revisa tu correo 📬', 'ok');
  } catch (e) { toast(e.message, 'error'); }
}
async function verifyEmailToken(token) {
  try {
    await api('/auth/verify-email', { method: 'POST', body: { token }, noLogout: true });
    if (state.me) state.me.email_verified = true;
    updateEmailBanner();
    track('email_verified');
    await FX.success('¡Correo verificado!', 'Gracias por confirmar tu cuenta ✅');
  } catch (e) { toast(e.message, 'error'); }
}

/* Aplica la configuración pública (/auth/config): tienda encendida o apagada */
function applyConfig() {
  document.documentElement.classList.toggle('shop-off', !shopOn());
}

function needsPhoneVerification() {
  return state.config.require_phone_verification && state.me && !state.me.phone_verified && !['admin', 'superadmin'].includes(state.me.role);
}
function afterLogin(gated = false) {
  identify();
  const staff = state.me && ['admin', 'superadmin'].includes(state.me.role);
  if (state.me && !staff && (!state.me.terms_accepted_at || state.me.age_declared === false)) {
    if (window.Cumplimiento) Cumplimiento.prepareTermsModal(state.me);
    $('#terms-modal').classList.add('open'); FX.decorate($('#terms-modal')); return;
  }
  // Nuevas versiones de documentos, verificación de edad y avisos (cumplimiento.js)
  if (!gated && window.Cumplimiento) return Cumplimiento.gate(() => afterLogin(true));
  if (needsPhoneVerification()) return startPhoneVerify();
  enterApp();
}

function enterApp() {
  stack = [];
  navigate('home', { push: false, reset: true });
  startPolling();
  updateEmailBanner();
  if (window.Cumplimiento) Cumplimiento.homeNotices();  // aviso de 30 días, anexos e invitación a las alertas
  handleDeepLinks();
}

/* ---------- verificación de teléfono ---------- */
let cooldownTimer;
function startPhoneVerify() {
  const required = state.config.require_phone_verification;
  $('#verify-skip-wrap').classList.toggle('hidden', !!required);
  $('#verify-why').classList.toggle('hidden', !required);
  $('[data-s="verify-phone"] .nav-back').classList.toggle('hidden', !!required);
  $('#verify-art').innerHTML = FX.dogFace(110, { fur: '#86E0D4' });
  $$('.code-box').forEach(b => { b.value = ''; });
  navigate('verify-phone', { push: false, reset: true });
  if (!state.me.phone) return showPhoneEdit(true);
  showPhoneEdit(false);
  sendCode();
}
function showPhoneEdit(on) {
  $('#verify-phone-edit').classList.toggle('hidden', !on);
  $('#verify-intro').classList.toggle('hidden', on);
  $('#verify-phone-num').textContent = state.me && state.me.phone || '';
  if (on) { $('#verify-phone-input').value = state.me && state.me.phone || ''; setTimeout(() => $('#verify-phone-input').focus(), 300); }
  FX.decorate(screens['verify-phone']);
}
async function savePhoneAndSend() {
  const phone = $('#verify-phone-input').value.trim();
  if (phone.replace(/\D/g, '').length < 10) return toast('Escribe tu celular a 10 dígitos', 'error');
  await withBtn($('#verify-phone-save'), async () => {
    state.me = await api('/users/me', { method: 'PATCH', body: { phone }, noVerifyRedirect: true });
    showPhoneEdit(false);
    await sendCode();
  });
}
function startCooldown(sec) {
  const btn = $('#verify-resend'), cd = $('#verify-countdown');
  clearInterval(cooldownTimer);
  let t = sec;
  btn.disabled = true; btn.style.opacity = .5;
  const tick = () => {
    if (t <= 0) { clearInterval(cooldownTimer); btn.disabled = false; btn.style.opacity = 1; cd.textContent = ''; return; }
    cd.textContent = ` (${t}s)`; t--;
  };
  tick();
  cooldownTimer = setInterval(tick, 1000);
}
async function sendCode() {
  try {
    const r = await api('/users/me/phone/send-code', { method: 'POST', noVerifyRedirect: true });
    if (r && r.phone) { state.me.phone = r.phone; $('#verify-phone-num').textContent = r.phone; }
    startCooldown((r && r.cooldown) || 60);
    if (r && r.dev_code) {
      toast(`Código de prueba: ${r.dev_code}`);
      [...String(r.dev_code)].forEach((c, i) => { const b = $$('.code-box')[i]; if (b) b.value = c; });
    } else toast('Te enviamos un SMS con tu código 📲', 'ok');
    const first = $$('.code-box').find(b => !b.value); if (first) first.focus();
  } catch (e) {
    toast(e.message, 'error');
    if (e.status === 409 || e.status === 400) showPhoneEdit(true);
  }
}
async function verifyCode() {
  const code = $$('.code-box').map(b => b.value).join('');
  if (code.length < 4) return toast('Escribe el código completo', 'error');
  await withBtn($('#verify-submit'), async () => {
    try { await api('/users/me/phone/verify', { method: 'POST', body: { code }, noVerifyRedirect: true }); }
    catch (e) { $$('.code-box').forEach(b => { b.value = ''; }); $$('.code-box')[0].focus(); const row = $('.code-row'); row.style.animation = 'shakeNo .4s'; setTimeout(() => row.style.animation = '', 400); throw e; }
    state.me.phone_verified = true;
    track('phone_verified');
    await FX.success('¡Teléfono verificado!', 'Tu perfil ahora es de confianza ✅');
    enterApp();
  });
}

/* ============================================================
   Ubicación
   ============================================================ */
function setCoords(c, city) {
  state.coords = c;
  localStorage.setItem('patitas_coords', JSON.stringify(c));
  if (city) { state.city = city; localStorage.setItem('patitas_city', city); }
}
function openLocation() {
  $('#loc-cities').innerHTML = CITIES.map(([n], i) => `<div class="card p row tap" data-city="${i}" style="padding:10px 14px"><svg width="18" height="18"><use href="#pin"/></svg><b class="grow">${n}</b>${state.city === n ? '<span class="badge b-teal">Actual</span>' : ''}</div>`).join('');
  $('#location-modal').classList.add('open');
  FX.decorate($('#location-modal'));
}
async function saveLocation(c, city) {
  setCoords(c, city);
  $('#location-modal').classList.remove('open');
  $('#home-location').textContent = state.city;
  // La ubicación precisa se guarda en la cuenta solo con las alertas cercanas encendidas (privacidad.html §8); si no, solo la ciudad
  if (state.me) api('/users/me', { method: 'PATCH', body: state.me.notify_nearby ? { latitude: c.lat, longitude: c.lon, city: state.city } : { city: state.city } }).catch(() => {});
  toast(`📍 ${state.city}`, 'ok');
  if (current === 'home') loadHome();
}

/* ============================================================
   Home
   ============================================================ */
async function loadHome() {
  $('#home-location').textContent = state.city;
  if (!$('#home-dog').innerHTML) $('#home-dog').innerHTML = FX.dogFace(92);
  const car = $('#home-carousel');
  car.innerHTML = FX.skeletonCards(3);
  $('#home-alerts').innerHTML = FX.skeletonList(2);
  refreshBadges();
  try {
    const [dogs, reports] = await Promise.all([
      api(`/dogs/featured?${locParams({ limit: 10 })}`),
      api(`/lost-reports?${locParams({ radius_km: 30 })}`),
    ]);
    car.innerHTML = dogs.length ? dogs.map((d, i) => `
      <div class="card dog-card tap pop-in" data-dog="${d.id}" style="animation-delay:${i * 60}ms">
        <div class="ph">${imgOrDog(photo(d), 70)}<span class="badge b-yellow">${esc(d.size || 'Adopción')}</span></div>
        <div class="nm">${esc(d.name)}</div>
        <div class="mt"><svg width="12" height="12"><use href="#pin"/></svg>${esc(d.distance_km != null ? dist(d.distance_km) : (d.city || ''))}</div>
      </div>`).join('')
      : `<div style="width:100%">${FX.empty('Aún no hay perritos cerca', 'Sé el primero en publicar uno')}</div>`;
    const al = reports.slice(0, 4);
    $('#home-alerts').innerHTML = al.length ? al.map(reportRow).join('') : `<div class="card p small center muted">Sin alertas activas en tu zona 💚</div>`;
  } catch (e) { toast(e.message, 'error'); car.innerHTML = ''; $('#home-alerts').innerHTML = ''; }
}

function reportRow(r) {
  const lost = r.report_type === 'lost';
  const st = r.is_hidden ? '<span class="badge b-gray">OCULTO</span>' : r.status === 'expired' ? '<span class="badge b-gray">EXPIRADO</span>' : r.status === 'resolved' ? '<span class="badge b-teal">REUNIDO</span>' : '';
  return `<div class="card alert-row tap" data-report="${r.id}">
    <div class="thumb">${imgOrDog(photo(r), 34)}</div>
    <div class="grow"><div class="row" style="gap:6px"><span class="badge ${lost ? 'b-red' : 'b-green'}">${lost ? 'PERDIDO' : 'ENCONTRADO'}</span>${st}<span class="small muted">${timeAgo(r.created_at)}</span></div>
    <div style="font-weight:800" class="ellipsis">${esc(r.dog_name)}</div><div class="small muted ellipsis">${esc([r.city, dist(r.distance_km)].filter(Boolean).join(' · '))}</div></div>
    <b>→</b></div>`;
}

/* ============================================================
   Discover (deck tipo swipe)
   ============================================================ */
async function loadDiscover() {
  const deck = $('#deck');
  deck.innerHTML = `<div class="center" style="padding-top:90px">${FX.tailChase().replace('class="tail-chase"', 'class="tail-chase" style="margin:0 auto"')}<p class="small muted mt12">Olfateando perritos cerca...</p></div>`;
  $('#discover-sub').textContent = state.coords ? `Cerca de ${state.city}` : state.city;
  try {
    state.deck = await api(`/dogs/discover?${locParams({ size: state.deckSize, limit: 40, radius_km: 80 })}`);
    state.deckIdx = 0;
    renderDeck();
  } catch (e) { toast(e.message, 'error'); deck.innerHTML = ''; }
}

function renderDeck() {
  const deck = $('#deck');
  const dog = state.deck[state.deckIdx];
  if (!dog) {
    deck.innerHTML = FX.empty('No hay más perritos por ahora', 'Vuelve más tarde o amplía tu búsqueda', { action: 'reload-discover', label: 'Volver a buscar' });
    FX.decorate(deck);
    return;
  }
  const photos = dog.photos && dog.photos.length ? dog.photos : [''];
  const hasNext = state.deck[state.deckIdx + 1], hasNext2 = state.deck[state.deckIdx + 2];
  deck.innerHTML = `
    <div class="under-wrap">${hasNext2 ? '<div class="card-under u2"></div>' : ''}${hasNext ? '<div class="card-under"></div>' : ''}</div>
    <div class="tcard pop-in" id="tcard">
      <div class="tph" id="tph">
        ${photos.length > 1 ? `<div class="dots">${photos.map((_, i) => `<i class="${i ? '' : 'on'}"></i>`).join('')}</div>` : ''}
        ${imgTag(photos[0], { thumb: false, id: 'tph-img', alt: dog.name }) || FX.dogFace(150)}
        <div class="grad"></div>
        <div class="stamp like" id="st-like">ME GUSTA</div><div class="stamp nope" id="st-nope">PASO</div>
      </div>
      <div class="tinfo">
        <div class="between"><div class="tname">${esc(dog.name)}</div>${dog.distance_km != null ? `<span class="badge b-blue">📍 ${dist(dog.distance_km)}</span>` : ''}</div>
        <div class="small muted mt8">${esc([dog.breed || 'Mestizo', age(dog.age_years, dog.age_months), dog.city].filter(Boolean).join(' · '))}</div>
        <div class="chips mt8">${dog.size ? `<span class="badge b-lila">${esc(dog.size)}</span>` : ''}${dog.color ? `<span class="badge b-yellow">${esc(dog.color)}</span>` : ''}${dog.owner ? `<span class="badge">🛡️ ${esc(dog.owner.full_name.split(' ')[0])}</span>` : ''}</div>
        <p class="small muted mt8" style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${esc(dog.description || '')}</p>
      </div>
    </div>
    <div class="deck-actions">
      <button class="round nope-btn" id="skip-btn" style="width:58px;height:58px;background:#fff" aria-label="Pasar"><svg width="24" height="24" style="color:var(--orange-d)"><use href="#close"/></svg></button>
      <button class="round" id="info-btn" style="width:46px;height:46px;background:var(--blue)" aria-label="Ver perfil"><svg width="20" height="20"><use href="#search"/></svg></button>
      <button class="round like-btn" id="like-btn" style="width:66px;height:66px;background:var(--orange)" aria-label="Me gusta"><svg width="30" height="30" style="color:#fff"><use href="#heart"/></svg></button>
    </div>`;
  bindCard(dog, photos);
}

function bindCard(dog, photos) {
  const card = $('#tcard');
  let pi = 0, sx = 0, sy = 0, dx = 0, dy = 0, dragging = false, moved = false;
  card.addEventListener('pointerdown', e => {
    dragging = true; moved = false; sx = e.clientX; sy = e.clientY;
    card.style.transition = 'none';
    try { card.setPointerCapture(e.pointerId); } catch { }
  });
  card.addEventListener('pointermove', e => {
    if (!dragging) return;
    dx = e.clientX - sx; dy = e.clientY - sy;
    if (Math.abs(dx) + Math.abs(dy) > 6) moved = true;
    card.style.transform = `translate(${dx}px,${dy * .4}px) rotate(${dx * .06}deg)`;
    $('#st-like').style.opacity = Math.min(1, Math.max(0, dx / 100));
    $('#st-nope').style.opacity = Math.min(1, Math.max(0, -dx / 100));
  });
  const end = e => {
    if (!dragging) return;
    dragging = false;
    card.style.transition = 'transform .35s var(--bounce)';
    if (dx > 110) swipeOut(1);
    else if (dx < -110) swipeOut(-1);
    else if (dy < -90) { card.style.transform = ''; openDog(dog.id); }
    else {
      card.style.transform = '';
      $('#st-like').style.opacity = 0; $('#st-nope').style.opacity = 0;
      if (!moved && photos.length > 1 && e.target.closest('#tph')) {
        const r = card.getBoundingClientRect();
        pi = (pi + (e.clientX - r.left > r.width / 2 ? 1 : photos.length - 1)) % photos.length;
        const im = $('#tph-img'), next = safeUrl(photos[pi]);
        if (im && next) im.src = next;
        $$('#tph .dots i').forEach((d, i) => d.classList.toggle('on', i === pi));
      } else if (!moved && !e.target.closest('#tph')) openDog(dog.id);
    }
    dx = dy = 0;
  };
  card.addEventListener('pointerup', end);
  card.addEventListener('pointercancel', end);
  $('#like-btn').onclick = () => swipeOut(1);
  $('#skip-btn').onclick = () => swipeOut(-1);
  $('#info-btn').onclick = () => openDog(dog.id);
}

async function swipeOut(dir) {
  const dog = state.deck[state.deckIdx];
  const card = $('#tcard');
  if (!dog || !card || card.dataset.out) return;
  card.dataset.out = '1';
  const btn = dir > 0 ? $('#like-btn') : $('#skip-btn');
  btn.classList.remove('boom'); void btn.offsetWidth; btn.classList.add('boom');
  $(dir > 0 ? '#st-like' : '#st-nope').style.opacity = 1;
  card.style.transition = 'transform .45s ease-in, opacity .45s';
  card.style.transform = `translate(${dir * 520}px,-40px) rotate(${dir * 28}deg)`;
  card.style.opacity = '0';
  if (dir > 0) FX.heartBurst(btn, 10);
  const req = dir > 0 ? api(`/dogs/${dog.id}/like`, { method: 'POST' }) : api(`/dogs/${dog.id}/pass`, { method: 'POST' });
  setTimeout(() => { state.deckIdx++; renderDeck(); FX.decorate($('#deck')); }, 380);
  try {
    const r = await req;
    if (dir > 0 && r) openMatchModal(r.id, dog);
  } catch (e) { toast(e.message, 'error'); }
}

function openMatchModal(matchId, dog) {
  state.matchId = matchId; state.matchDog = dog;
  $('#match-dog-name').textContent = dog.name;
  let li = 0;
  $('#mm-title').innerHTML = `¡${dog.name}!`.split(' ').map(w => `<span class="mm-word">${[...w].map(c => `<span style="--i:${li++}">${esc(c)}</span>`).join('')}</span>`).join(' ');
  $('#mm-dog').innerHTML = imgTag(photo(dog)) || FX.dogFace(80);
  $('#mm-me').innerHTML = (state.me && imgTag(state.me.avatar_url)) || `<b style="font-size:30px">${esc(initials(state.me && state.me.full_name))}</b>`;
  const m = $('#match-modal');
  m.classList.add('open');
  FX.decorate(m);
  requestAnimationFrame(() => m.classList.add('show'));
  setTimeout(() => FX.confetti(40), 250);
}
function closeMatchModal() { const m = $('#match-modal'); m.classList.remove('show'); setTimeout(() => m.classList.remove('open'), 250); }

/* ============================================================
   Perfil del perro
   ============================================================ */
async function openDog(id, nav = {}) {
  const body = $('#dog-body');
  body.innerHTML = `<div class="skel" style="height:290px"><i class="skel-paw">${FX.PAW}</i></div>${FX.skeletonList(2)}`;
  navigate('dog', nav);
  try {
    const d = await api(`/dogs/${id}`);
    state.dog = d;
    const photos = d.photos && d.photos.length ? d.photos : [''];
    const mine = state.me && d.owner_id === state.me.id;
    $('#dog-flag').classList.toggle('hidden', !!mine || !state.me);
    body.innerHTML = `
      <div class="gallery pop-in"><div class="track">${photos.map(p => `<div>${imgTag(p, { thumb: false, alt: d.name }) || FX.dogFace(160)}</div>`).join('')}</div></div>
      ${photos.length > 1 ? `<p class="small muted center mt8">← Desliza para ver ${photos.length} fotos →</p>` : ''}
      <div class="between mt16"><div><div class="h1">${esc(d.name)}</div><div class="small muted row" style="gap:4px"><svg width="13" height="13"><use href="#pin"/></svg>${esc([d.city, d.country].filter(Boolean).join(', '))}${d.distance_km != null ? ' · ' + dist(d.distance_km) : ''}</div></div><span class="badge ${d.status === 'available' ? 'b-green' : 'b-yellow'}">${esc(STATUS_LABEL[d.status] || d.status)}</span></div>
      <div class="pill facts mt16"><div><small>EDAD</small><b>${esc(age(d.age_years, d.age_months))}</b></div><div><small>RAZA</small><b>${esc(d.breed || 'Mestizo')}</b></div><div><small>TAMAÑO</small><b>${esc(d.size || '—')}</b></div></div>
      ${mine && d.review ? `<div class="card p small mt12 shop-note">🔎 <b>${d.review.status === 'rechazado' ? 'No aprobada' : 'En revisión'}:</b> ${esc(d.review.message || '')}</div>` : mine && d.is_hidden ? HIDDEN_NOTE : ''}
      ${mine && d.found_hold ? foundHoldCard(d) : ''}
      ${d.color ? `<div class="chips mt12"><span class="badge b-yellow">🎨 ${esc(d.color)}</span></div>` : ''}
      <div class="card p mt16"><div class="small muted" style="font-weight:800">SOBRE ${esc(d.name.toUpperCase())}</div><p class="body mt8" style="white-space:pre-line">${esc(d.description || 'Sin descripción todavía.')}</p></div>
      ${d.owner ? `<div class="card p row mt12">${avatarHtml(d.owner)}<div class="grow"><b class="row" style="gap:5px;flex-wrap:wrap">${esc(d.owner.full_name)} <svg width="16" height="16"><use href="#shield"/></svg> <span class="badge ${d.owner.role === 'refuge' ? 'b-lila' : d.owner.role === 'foster' ? 'b-blue' : 'b-green'}">${d.owner.role === 'refuge' ? 'Refugio' : d.owner.role === 'foster' ? 'Casa de paso' : 'Particular / Rescatista'}</span></b><div class="small muted">Publicado ${timeAgo(d.created_at)}</div></div></div>` : ''}
      ${mine ? `<div class="col mt16"><span class="lbl">Gestionar publicación</span>
        <div class="chips">${['available', 'in_process', 'adopted', 'in_foster'].map(s => `<span class="chip ${d.status === s ? 'on' : ''}" data-dog-status="${s}">${STATUS_LABEL[s]}</span>`).join('')}</div>
        <button class="btn btn-sm btn-ghost" id="dog-delete">Retirar publicación</button></div>` : ''}`;
    const cta = $('#dog-cta');
    cta.classList.toggle('hidden', mine || d.status !== 'available' || !state.me);
    FX.decorate(body);
    $$('[data-dog-status]', body).forEach(c => c.onclick = async () => {
      try { await api(`/dogs/${d.id}/status`, { method: 'PATCH', body: { status: c.dataset.dogStatus } }); toast('Estado actualizado', 'ok'); if (c.dataset.dogStatus === 'adopted') FX.success('¡Encontró hogar!', `${d.name} ya tiene familia 💚`); openDog(d.id, { push: false }); }
      catch (e) { toast(e.message, 'error'); }
    });
    const del = $('#dog-delete');
    if (del) del.onclick = async () => { if (!confirm(`¿Retirar la publicación de ${d.name}?`)) return; try { await api(`/dogs/${d.id}`, { method: 'DELETE' }); toast('Publicación retirada'); back(); } catch (e) { toast(e.message, 'error'); } };
    // Lista de revisión de un perro encontrado (microchip y aviso a la autoridad): PATCH /dogs/{id}
    const fh = (body2, msg) => async () => { try { await api(`/dogs/${d.id}`, { method: 'PATCH', body: body2 }); toast(msg, 'ok'); openDog(d.id, { push: false }); } catch (e) { toast(e.message, 'error'); } };
    const chipBtn = $('#fh-chip');
    if (chipBtn) chipBtn.onclick = fh({ microchip_checked: true }, 'Microchip revisado ✔');
    const authBtn = $('#fh-authority');
    if (authBtn) authBtn.onclick = () => { const notice = (prompt('¿A qué autoridad avisaste? Escribe también el folio de la constancia, si te lo dieron:') || '').trim(); if (notice.length >= 3) fh({ authority_notified: true, authority_notice: notice }, 'Aviso a la autoridad registrado ✔')(); else if (notice) toast('Escribe a qué autoridad avisaste', 'error'); };
  } catch (e) { toast(e.message, 'error'); back(); }
}
/* Resguardo de un perro encontrado (perdidos-y-encontrados §6): lo que falta para ofrecerlo en adopción */
function foundHoldCard(d) {
  const h = d.found_hold;
  if (!h.active) return `<div class="card p small mt12" style="background:var(--green)">✔ Cumplió el resguardo de perro encontrado: ya puede ofrecerse en adopción.</div>`;
  return `<div class="card p small mt12" style="background:var(--blue)">🏠 <b>En resguardo.</b> ${esc(h.message || '')}
    <div class="row mt8" style="flex-wrap:wrap;gap:8px">${!h.microchip_checked_at ? '<button type="button" class="btn btn-sm" id="fh-chip">Ya le revisaron el microchip</button>' : ''}${!h.authority_notified_at ? '<button type="button" class="btn btn-sm btn-ghost" id="fh-authority">Ya avisé a la autoridad</button>' : ''}</div></div>`;
}

async function adoptCurrentDog() {
  const d = state.dog; if (!d) return;
  await withBtn($('#dog-adopt'), async () => {
    const m = await api(`/dogs/${d.id}/like`, { method: 'POST' });
    state.matchId = m.id; state.matchDog = d;
    openQuestionnaire();
  });
}

function openQuestionnaire() {
  if (!state.matchDog) return;
  $('#q-dog-name').textContent = state.matchDog.name;
  $('#questionnaire-form').reset();
  $$('#questionnaire-form .chip').forEach(c => c.classList.remove('on'));
  navigate('questionnaire');
}

async function submitQuestionnaire(e) {
  e.preventDefault();
  const answers = {};
  let missing = false;
  const budgetOk = $('#q-budget-consent').checked;
  $$('#questionnaire-form [data-q]').forEach(g => {
    const on = $('.chip.on', g);
    if (g.dataset.optional) { if (budgetOk && on) answers[g.dataset.q] = on.dataset.v; return; }
    if (!on) missing = true; else answers[g.dataset.q] = on.dataset.v;
  });
  if (budgetOk && !answers.budget) return toast('Elige tu rango de presupuesto o desmarca la casilla', 'error');
  if (budgetOk) answers.budget_consent = true;
  if (missing) return toast('Responde todas las preguntas 🐾', 'error');
  if (!$('#q-commit').checked) return toast('Acepta el compromiso de adopción responsable', 'error');
  answers.why = $('#q-why').value.trim();
  answers.commitment = true;
  const btn = $('#questionnaire-form button[type=submit]');
  await withBtn(btn, async () => {
    await api(`/matches/${state.matchId}/apply`, { method: 'POST', body: { answers } });
    track('adoption_application_sent', { dog_id: state.matchDog && state.matchDog.id });
    await FX.success('¡Solicitud enviada!', `Te avisaremos cuando respondan por ${state.matchDog.name}`);
    state.matchId = null;
    navigate('home', { reset: true });
  });
}

/* ============================================================
   Selector de fotos y ubicación (componentes reutilizables)
   ============================================================ */
const photoStore = {};
const photoHooks = {};
function initPhotoDrops() {
  $$('[data-photos]').forEach(box => {
    const key = box.dataset.photos;
    photoStore[key] = [];
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'image/*'; input.multiple = true; input.className = 'hidden';
    box.after(input);
    input.addEventListener('change', () => {
      const room = 5 - photoStore[key].length;
      const added = [...input.files].filter(f => f.type.startsWith('image/')).slice(0, room);
      if (input.files.length > room) toast('Máximo 5 fotos', 'error');
      const big = added.find(f => f.size > 40 * 1024 * 1024);
      if (big) { toast('Esa foto es demasiado pesada. Prueba con otra', 'error'); input.value = ''; return; }
      const wasEmpty = !photoStore[key].length;
      photoStore[key].push(...added);
      input.value = '';
      renderPhotoDrop(key);
      if (wasEmpty && added.length && photoHooks[key]) photoHooks[key](added[0]);
    });
    box._input = input;
    renderPhotoDrop(key);
  });
}
function renderPhotoDrop(key) {
  const box = $(`[data-photos="${key}"]`);
  const files = photoStore[key];
  box.innerHTML = files.map((f, i) => `<div class="photo-prev"><img src="${URL.createObjectURL(f)}" alt=""><button type="button" data-rm="${i}" aria-label="Quitar">×</button></div>`).join('')
    + (files.length < 5 ? `<div class="photo-add" role="button" tabindex="0"><svg width="24" height="24"><use href="#camera"/></svg>Agregar</div>` : '');
  const add = $('.photo-add', box);
  if (add) add.onclick = () => box._input.click();
  $$('[data-rm]', box).forEach(b => b.onclick = () => { files.splice(+b.dataset.rm, 1); renderPhotoDrop(key); });
}
function clearPhotos(key) { photoStore[key] = []; renderPhotoDrop(key); }

const locStore = {};
function initLocPickers() {
  $$('[data-loc]').forEach(box => {
    const key = box.dataset.loc;
    $('[data-loc-btn]', box).addEventListener('click', async e => {
      const btn = e.currentTarget;
      await withBtn(btn, async () => {
        const c = await getPosition();
        locStore[key] = c;
        box.classList.add('ok');
        $('[data-loc-text]', box).textContent = '📍 Ubicación guardada';
        const g = await reverseGeocode(c);
        const cityInput = $(`#${key}-city`);
        if (g && cityInput && !cityInput.value) cityInput.value = [g.area, g.city].filter(Boolean).join(', ');
        if (g && window.Compartir) Compartir.onGeocode(key, g);  // estado de la República (compartir.js)
      });
    });
  });
}
function resetLoc(key) {
  delete locStore[key];
  if (window.Compartir) Compartir.clearGeo(key);
  const box = $(`[data-loc="${key}"]`);
  box.classList.remove('ok');
  $('[data-loc-text]', box).textContent = 'Usar mi ubicación actual';
}

/* IA: autocompletar formularios a partir de la foto */
async function aiAutofill(file, prefix) {
  if (!state.config.ai_enabled) return;
  const hint = $(`#${prefix}-ai`), txt = $(`#${prefix}-ai-text`);
  hint.classList.remove('hidden');
  txt.innerHTML = 'La IA está mirando la foto <span class="paw-dots">🐾</span>';
  try {
    const fd = new FormData(); fd.append('file', await shrinkImage(file));
    const a = await api('/ai/analyze-photo', { method: 'POST', body: fd });
    if (a && a.is_dog === false) { txt.textContent = 'Mmm... no parece un perrito. ¿Probamos con otra foto?'; return; }
    const set = (id, v) => { const el = $(id); if (el && v && !el.value) el.value = v; };
    set(`#${prefix}-breed`, a.breed_guess);
    set(`#${prefix}-color`, (a.colors || []).join(', '));
    const marks = (a.distinctive_marks || []).join(', ');
    set(`#${prefix}-description`, [a.description_es, marks && `Señas: ${marks}`].filter(Boolean).join('\n'));
    if (a.size) $$(`[data-single="${prefix}-size"] .chip`).forEach(c => c.classList.toggle('on', c.dataset.v === a.size));
    txt.textContent = `✨ Detectamos: ${[a.breed_guess, a.size, (a.colors || [])[0]].filter(Boolean).join(' · ')}. Revisa y ajusta.`;
  } catch { hint.classList.add('hidden'); }
}

/* ============================================================
   Publicar en adopción
   ============================================================ */
function openPublish(opts = {}) {
  $('#publish-form').reset();
  $('#pub-country').value = 'México';
  $('#pub-city').value = state.me && state.me.city || '';
  clearPhotos('pub'); resetLoc('pub');
  $('#pub-ai').classList.add('hidden');
  // Perro encontrado (perdidos-y-encontrados §6): liga su reporte y la lista de revisión; se queda en resguardo
  const foundReport = opts && opts.foundReportId ? +opts.foundReportId : null;
  $('#pub-found').checked = !!foundReport;
  $('#pub-found-wrap').classList.toggle('hidden', !foundReport);
  loadFoundReports(foundReport);
  donationRules().then(rules => { const days = rules && rules.adoption && rules.adoption.found_dog_hold_days; if (days) $$('[data-found-days]').forEach(el => el.textContent = days); });
  navigate('publish');
}
async function loadFoundReports(selected) {
  const sel = $('#pub-found-report'); if (!sel || !state.me) return;
  let mine = [];
  try { mine = (await api('/lost-reports/me')).filter(r => r.report_type === 'found' && r.status !== 'resolved'); } catch { mine = []; }
  sel.innerHTML = '<option value="">Aún no lo publico</option>' + mine.map(r => `<option value="${r.id}">#${r.id} · ${esc(r.dog_name)} · ${fmtDate(r.created_at)}</option>`).join('');
  if (selected) sel.value = String(selected);
}
function foundFields() {
  if (!$('#pub-found').checked) return {};
  const notice = $('#pub-authority-notice').value.trim();
  return {
    was_found: true, found_report_id: +$('#pub-found-report').value || null,
    microchip_checked: $('#pub-chip').checked || null, microchip_result: $('#pub-chip-result').value || null,
    authority_notified: $('#pub-authority').checked || null, authority_notice: notice || null,
  };
}
async function submitPublish(e) {
  e.preventDefault();
  const name = $('#pub-name').value.trim();
  if (!name) return toast('¿Cómo se llama el perrito?', 'error');
  if (!photoStore.pub.length) return toast('Agrega al menos una foto 📸', 'error');
  if ($('#pub-found').checked && $('#pub-authority').checked && $('#pub-authority-notice').value.trim().length < 3) return toast('Escribe a qué autoridad avisaste (y el folio, si te lo dieron)', 'error');
  const btn = $('#publish-submit');
  FX.setLoading(btn, true);
  FX.showLoading('Publicando a ' + name, ['Subiendo fotos...', 'Optimizando imágenes...', 'Avisando a adoptantes cerca...'], 'run');
  try {
    const photos = await uploadFiles(photoStore.pub);
    const c = locStore.pub || state.coords;
    const sizeChip = $('[data-single="pub-size"] .chip.on');
    const dog = await api('/dogs', { method: 'POST', body: {
      name, breed: $('#pub-breed').value.trim() || null, color: $('#pub-color').value.trim() || null,
      age_years: parseInt($('#pub-age-years').value) || 0, age_months: parseInt($('#pub-age-months').value) || 0,
      size: sizeChip ? sizeChip.dataset.v : null, description: $('#pub-description').value.trim() || null,
      city: $('#pub-city').value.trim() || state.city, country: $('#pub-country').value.trim() || 'México',
      latitude: c ? c.lat : null, longitude: c ? c.lon : null, photos, ...foundFields(),
    } });
    FX.hideLoading();
    track('dog_published');
    // Reglas de adopción: en revisión por cobros o rifas, o en resguardo por ser un perro encontrado
    if (dog.review) await FX.success('Publicación en revisión', dog.review.message || 'Un moderador la revisará pronto');
    else if (dog.found_hold && dog.found_hold.active) await FX.success('Guardado en resguardo', dog.found_hold.message || 'Podrás publicarlo en adopción cuando se cumpla el plazo');
    else await FX.success('¡Publicado!', `${name} ya está buscando familia`);
    stack = ['home'];
    openDog(dog.id, { push: false });
  } catch (err) { FX.hideLoading(); toast(err.message, 'error'); }
  finally { FX.setLoading(btn, false); }
}

/* ============================================================
   Reportes perdido / encontrado
   ============================================================ */
function openReportForm(type = 'lost', file = null) {
  $('#report-form').reset();
  $('#rf-country').value = 'México';
  clearPhotos('rf'); resetLoc('rf');
  $('#rf-ai').classList.add('hidden');
  setReportType(type);
  if (file) { photoStore.rf.push(file); renderPhotoDrop('rf'); }
  navigate('report-form');
}
function setReportType(type) {
  state.reportType = type;
  const lost = type === 'lost';
  $$('#rf-type button').forEach(b => b.classList.toggle('on', b.dataset.v === type));
  $('#rf-title').firstChild.textContent = lost ? 'Reportar perro perdido' : 'Reportar perro encontrado';
  $('#rf-sub').textContent = lost ? 'Cada minuto cuenta' : 'Gracias por ayudar 💚';
  $('#rf-name-lbl').textContent = lost ? 'Nombre del perro' : 'Nombre (si trae placa)';
  $('#rf-name').placeholder = lost ? 'Rocky' : 'Desconocido';
  $('#rf-loc-lbl').textContent = lost ? '¿Dónde se perdió?' : '¿Dónde lo encontraste?';
}
async function submitReport(e) {
  e.preventDefault();
  const lost = state.reportType === 'lost';
  const name = $('#rf-name').value.trim();
  if (lost && !name) return toast('Escribe el nombre de tu perrito', 'error');
  if (!photoStore.rf.length) return toast('Una foto ayuda muchísimo a encontrarlo 📸', 'error');
  const c = locStore.rf || state.coords;
  if (!c && !$('#rf-city').value.trim()) return toast('Indica la ubicación o la colonia', 'error');
  const btn = $('#rf-submit');
  FX.setLoading(btn, true);
  FX.showLoading(lost ? 'Activando la alerta' : 'Publicando reporte', ['Subiendo fotos...', 'La IA analiza su carita...', 'Buscando coincidencias cerca...'], 'sniff');
  try {
    const photos = await uploadFiles(photoStore.rf);
    const r = await api('/lost-reports', { method: 'POST', body: {
      dog_name: name || 'Desconocido', report_type: state.reportType, description: $('#rf-description').value.trim() || null,
      city: $('#rf-city').value.trim() || state.city, country: $('#rf-country').value.trim() || 'México',
      state: window.Compartir ? Compartir.reportState('rf') : null,  // geocoder → selector → texto de la colonia
      latitude: c ? c.lat : null, longitude: c ? c.lon : null, photos,
    } });
    FX.hideLoading();
    track('report_created', { type: state.reportType });
    await FX.success(lost ? '¡Alerta activada!' : '¡Reporte publicado!', lost ? 'Avisamos a la comunidad de tu zona' : 'Ojalá vuelva pronto a casa');
    stack = ['home'];
    openReport(r.id, { push: false });
  } catch (err) { FX.hideLoading(); toast(err.message, 'error'); }
  finally { FX.setLoading(btn, false); }
}

async function openReport(id, nav = {}) {
  const body = $('#report-body');
  body.innerHTML = `<div class="skel" style="height:260px"><i class="skel-paw">${FX.PAW}</i></div>${FX.skeletonList(2)}`;
  navigate('report', nav);
  try {
    const r = await api(`/lost-reports/${id}`);
    state.report = r;
    const lost = r.report_type === 'lost';
    const mine = state.me && r.reporter_id === state.me.id;
    const expired = r.status === 'expired';
    $('#report-flag').classList.toggle('hidden', !!mine || !state.me);
    $('#report-title').textContent = lost ? 'Perro perdido' : 'Perro encontrado';
    const photos = r.photos && r.photos.length ? r.photos : [''];
    const srcLbl = { whatsapp: 'vía WhatsApp', facebook: 'vía Facebook', volunteer: 'vía voluntario' }[r.source] || '';
    // Contenido importado de una publicación pública de Facebook (grupos o voluntarios): su autor no es usuario
    const imported = r.source === 'facebook' || r.source === 'volunteer';
    body.innerHTML = `
      <div class="gallery pop-in" style="height:250px"><div class="track">${photos.map(p => `<div>${imgTag(p, { thumb: false, alt: r.dog_name }) || FX.dogFace(140)}</div>`).join('')}</div></div>
      <div class="between mt16"><div class="grow"><div class="row" style="gap:6px"><span class="badge ${lost ? 'b-red' : 'b-green'}">${lost ? 'PERDIDO' : 'ENCONTRADO'}</span>${r.status === 'resolved' ? '<span class="badge b-teal">¡REUNIDO!</span>' : ''}${expired ? '<span class="badge b-gray">EXPIRADO</span>' : ''}${srcLbl ? `<span class="badge">${srcLbl}</span>` : ''}</div>
      <div class="h1 mt8">${esc(r.dog_name)}</div><div class="small muted">${esc([r.city, dist(r.distance_km), timeAgo(r.created_at)].filter(Boolean).join(' · '))}</div></div></div>
      ${mine && r.is_hidden ? HIDDEN_NOTE : ''}
      ${r.description ? `<div class="card p mt12"><div class="small muted" style="font-weight:800">SEÑAS PARTICULARES</div><p class="body mt8" style="white-space:pre-line">${esc(r.description)}</p></div>` : ''}
      ${imported ? (window.Compartir ? Compartir.importedHtml(r) : `<div class="card p small mt12" style="background:var(--blue)">ℹ️ Importado de una publicación pública de Facebook; su autor no es usuario de GuauWoow.</div>`) : ''}
      ${r.reporter ? `<div class="card p row mt12">${avatarHtml(r.reporter)}<div class="grow"><b>${esc(r.reporter.full_name)}</b><div class="small muted">${r.source === 'volunteer' ? 'Compartió esta publicación de Facebook' : lost ? 'Busca a su perrito' : 'Lo tiene resguardado'}</div></div></div>` : ''}
      <div class="col mt16">
        ${mine && expired && imported ? `<div class="card p small" style="background:var(--yellow)">⏳ Las publicaciones importadas de Facebook caducan a los 30 días y ya no son públicas. Si el perrito sigue perdido, crea un reporte nuevo con tus propias fotos.</div>` : ''}
        ${mine && expired && !imported ? `<div class="card p small" style="background:var(--yellow)">⏳ Este reporte expiró porque no tuvo cambios en 90 días. Si sigues buscando, renuévalo para que vuelva a aparecer en las listas y el mapa.</div>
        <button class="btn block btn-orange shine" id="rp-renew">🔄 Renovar reporte</button>` : ''}
        ${mine && (r.status === 'active' || expired) ? `<button class="btn block btn-green shine" id="rp-resolve">🎉 ¡Ya está en casa!</button>` : ''}
        ${mine && !lost && !imported && r.status === 'active' ? `<div class="card p small" style="background:var(--blue)">🏠 Si nadie lo reclama, podrás ofrecerlo en adopción cuando pasen <span data-found-days>30</span> días con este reporte publicado, con su microchip revisado y aviso a la autoridad local. Puedes preparar su ficha desde ahora: quedará en resguardo.<button type="button" class="btn btn-sm btn-ghost block mt8" id="rp-adopt">Preparar su ficha de adopción</button></div>` : ''}
        ${!mine && r.reporter_id && r.status === 'active' ? `<button class="btn block btn-orange shine" id="rp-contact"><svg width="18" height="18"><use href="#chat"/></svg> ${lost ? 'Lo vi / lo tengo' : 'Es mi perro'}</button>` : ''}
        <button class="btn block btn-ghost" id="rp-share"><svg width="18" height="18"><use href="#send"/></svg> Compartir alerta</button>
      </div>
      <div class="between mt24"><span class="h2">Posibles coincidencias</span><svg width="22" height="22" style="color:var(--purple)"><use href="#sparkle"/></svg></div>
      <div class="col mt12" id="rp-matches">${FX.inlineLoader('La IA compara fotos cercanas...')}</div>`;
    FX.decorate(body);
    if (imported && window.Compartir) Compartir.bindImported(r);  // «Soy el autor: retirar» (sin cuenta)
    const ad = $('#rp-adopt');
    if (ad) {
      ad.onclick = () => openPublish({ foundReportId: r.id });
      donationRules().then(rules => { const days = rules && rules.adoption && rules.adoption.found_dog_hold_days; if (days) $$('[data-found-days]', body).forEach(el => el.textContent = days); });
    }
    const rn = $('#rp-renew');
    if (rn) rn.onclick = () => withBtn(rn, async () => { await api(`/lost-reports/${r.id}/renew`, { method: 'POST' }); toast('¡Reporte renovado! Vuelve a estar visible 🔔', 'ok'); openReport(r.id, { push: false }); });
    const rs = $('#rp-resolve');
    if (rs) rs.onclick = () => withBtn(rs, async () => { await api(`/lost-reports/${r.id}/resolve`, { method: 'PATCH' }); await FX.success('¡Qué alegría!', `${r.dog_name} está de vuelta 💚`); openReport(r.id, { push: false }); });
    const ct = $('#rp-contact');
    if (ct) ct.onclick = () => withBtn(ct, async () => { if (!state.me) throw new Error('Inicia sesión para contactar'); const c = await api(`/lost-reports/${r.id}/contact`, { method: 'POST' }); openChat(c.id); });
    $('#rp-share').onclick = () => share(`${lost ? '🚨 Se busca' : '🐶 Encontrado'}: ${r.dog_name} en ${r.city || 'mi zona'}`, `/app/?report=${r.id}`);
    try {
      const ms = await api(`/lost-reports/${r.id}/matches`);
      $('#rp-matches').innerHTML = ms.length ? ms.map(matchRow).join('') : `<div class="card p small center muted">Aún no hay coincidencias. Te avisaremos en cuanto aparezca una 🔔</div>`;
    } catch { $('#rp-matches').innerHTML = `<div class="card p small center muted">No pudimos calcular coincidencias ahora.</div>`; }
  } catch (e) { toast(e.message, 'error'); back(); }
}

function matchRow(m) {
  const lbl = { lost: ['PERDIDO', 'b-red'], found: ['ENCONTRADO', 'b-green'], adoption: ['ADOPCIÓN', 'b-yellow'] }[m.type] || ['', ''];
  const attr = m.type === 'adoption' ? `data-dog="${m.id}"` : `data-report="${m.id}"`;
  return `<div class="card p row tap pop-in" ${attr}>
    <div class="thumb">${imgOrDog(photo(m), 34)}</div>
    <div class="grow"><span class="badge ${lbl[1]}">${lbl[0]}</span><div style="font-weight:800" class="ellipsis mt8">${esc(m.name)}</div><div class="small muted ellipsis">${esc([m.city, dist(m.distance_km)].filter(Boolean).join(' · '))}</div></div>
    <div class="score-ring" style="--p:${Math.round(m.score)}"><b>${Math.round(m.score)}%</b></div></div>`;
}

async function share(text, path) {
  const url = location.origin + path;
  try {
    if (navigator.share) await navigator.share({ title: 'GuauWoow', text, url });
    else { await navigator.clipboard.writeText(`${text} ${url}`); toast('Enlace copiado 📋', 'ok'); }
  } catch { }
}

/* ============================================================
   Búsqueda por foto con IA
   ============================================================ */
function openPhotoSearch() {
  state.psFile = null;
  $('#ps-pick').classList.remove('hidden');
  $('#ps-scan').classList.add('hidden');
  $('#ps-results').classList.add('hidden');
  $('#ps-go').classList.add('hidden');
  $('#ps-preview-inner').innerHTML = FX.dogFace(140);
  navigate('photo-search');
}
function setPsFile(f) {
  if (!f) return;
  state.psFile = f;
  $('#ps-preview-inner').innerHTML = `<img src="${URL.createObjectURL(f)}" alt="" style="width:100%;height:100%;object-fit:cover">`;
  $('#ps-go').classList.remove('hidden');
  FX.decorate($('#ps-pick'));
}
async function runPhotoSearch() {
  if (!state.psFile) return toast('Primero toma o elige una foto', 'error');
  $('#ps-pick').classList.add('hidden');
  $('#ps-scan').classList.remove('hidden');
  const box = $('#ps-scan-box');
  $$('.pt, img', box).forEach(n => n.remove());
  box.insertAdjacentHTML('afterbegin', `<img src="${URL.createObjectURL(state.psFile)}" alt="">`);
  const msgs = ['Detectando rasgos del rostro', 'Midiendo hocico, ojos y orejas', 'Comparando colores del pelaje', 'Buscando en reportes cercanos', 'Ordenando coincidencias'];
  let p = 0, mi = 0;
  const bar = $('#ps-bar');
  bar.style.width = '0';
  const iv = setInterval(() => {
    p = Math.min(90, p + FX.rand(4, 11)); bar.style.width = p + '%';
    if (Math.random() < .5) box.insertAdjacentHTML('beforeend', `<span class="pt" style="left:${FX.rand(25, 75)}%;top:${FX.rand(20, 80)}%"></span>`);
    if (p > (mi + 1) * 18 && mi < msgs.length - 1) $('#ps-scan-msg').textContent = msgs[++mi];
  }, 300);
  const fd = new FormData();
  fd.append('file', await shrinkImage(state.psFile));
  if (state.coords) { fd.append('lat', state.coords.lat); fd.append('lon', state.coords.lon); }
  if (state.city) fd.append('city', state.city);
  if (state.psType) fd.append('report_type', state.psType);
  try {
    const [res] = await Promise.all([api('/search/by-photo', { method: 'POST', body: fd }), sleep(2800)]);
    clearInterval(iv); bar.style.width = 'calc(100% - 4px)';
    await sleep(350);
    renderPhotoResults(res);
  } catch (e) {
    clearInterval(iv);
    toast(e.message, 'error');
    $('#ps-scan').classList.add('hidden'); $('#ps-pick').classList.remove('hidden');
  }
}
function renderPhotoResults(res) {
  $('#ps-scan').classList.add('hidden');
  const box = $('#ps-results');
  box.classList.remove('hidden');
  const a = res.analysis;
  const ms = res.matches || [];
  box.innerHTML = `
    ${a ? `<div class="card p row pop-in" style="background:var(--lila)"><div class="thumb" style="width:64px;height:64px"><img src="${URL.createObjectURL(state.psFile)}" alt=""></div>
      <div class="grow"><div class="small" style="font-weight:800">✨ La IA ve:</div><b>${esc([a.breed_guess, a.size].filter(Boolean).join(' · ') || 'Un perrito')}</b>
      <div class="small muted">${esc((a.colors || []).join(', '))}${(a.distinctive_marks || []).length ? ' · ' + esc(a.distinctive_marks.join(', ')) : ''}</div></div></div>` : ''}
    <div class="between mt16"><span class="h2">${ms.length ? `${ms.length} posibles coincidencias` : 'Sin coincidencias'}</span></div>
    <div class="col mt12 stagger">${ms.length ? ms.map((m, i) => matchRow(m).replace('class="card p row tap pop-in"', `class="card p row tap" style="--i:${i}"`)).join('') : FX.empty('No encontramos parecidos todavía', 'Crea una alerta y te avisaremos si aparece')}</div>
    <div class="col mt20"><button class="btn block btn-orange" id="ps-alert-lost">Crear alerta de perdido</button><button class="btn block btn-green" id="ps-alert-found">Reportar como encontrado</button><button class="btn block btn-ghost" id="ps-again">Buscar otra foto</button></div>`;
  FX.decorate(box);
  $('#ps-alert-lost').onclick = () => openReportForm('lost', state.psFile);
  $('#ps-alert-found').onclick = () => openReportForm('found', state.psFile);
  $('#ps-again').onclick = openPhotoSearch;
}

/* ============================================================
   Chat
   ============================================================ */
async function loadChatList() {
  const list = $('#chat-list');
  list.innerHTML = FX.skeletonList(4);
  try {
    const cs = await api('/conversations');
    list.innerHTML = cs.length ? cs.map((c, i) => `
      <div class="card p row tap pop-in" data-conv="${c.id}" style="animation-delay:${i * 50}ms">
        <div class="thumb">${imgOrDog(c.photo, 32)}</div>
        <div class="grow"><div class="between"><b class="ellipsis">${esc(c.title)}</b><span class="small muted">${c.last_message ? timeAgo(c.last_message.created_at) : ''}</span></div>
        <div class="small muted ellipsis">${esc(c.other_user ? c.other_user.full_name : '')}${c.last_message ? ': ' + esc(c.last_message.content) : ' · Nuevo chat'}</div></div>
        ${c.unread_count ? `<span class="badge b-orange">${c.unread_count}</span>` : ''}
      </div>`).join('') : FX.empty('Sin conversaciones aún', 'Cuando apruebes o te aprueben una adopción, o contactes un reporte, el chat aparece aquí', { action: 'go-discover', label: 'Descubrir perritos' });
    FX.decorate(list);
  } catch (e) { toast(e.message, 'error'); list.innerHTML = ''; }
}

async function openChat(id) {
  const area = $('#chat-messages');
  area.innerHTML = FX.inlineLoader('Abriendo chat...');
  navigate('chat');
  try {
    const [c, msgs] = await Promise.all([api(`/conversations/${id}`), api(`/conversations/${id}/messages?limit=100`)]);
    state.conv = c;
    $('#chat-title').textContent = c.title;
    $('#chat-subtitle').textContent = c.other_user ? `con ${c.other_user.full_name}` : '';
    $('#chat-avatar').innerHTML = imgTag(c.photo) || esc(initials(c.title));
    const ref = $('#chat-open-ref');
    ref.classList.toggle('hidden', !c.lost_report_id);
    $('#chat-flag').classList.toggle('hidden', !c.other_user);
    area.innerHTML = '';
    if (!msgs.length) area.innerHTML = `<div class="center small muted" id="chat-empty" style="margin-top:30px">${FX.dogFace(80)}<p class="mt8">¡Salúdense! Coordinen con calma y siempre en lugares públicos.</p></div>`;
    msgs.slice().reverse().forEach(m => renderMsg(m, false));
    area.scrollTop = area.scrollHeight;
    api(`/conversations/${id}/read`, { method: 'PATCH' }).catch(() => {});
    state.wsAttempt = 0;
    connectWS(id);
  } catch (e) { toast(e.message, 'error'); back(); }
}
/* Tras reconectar se traen los mensajes que llegaron mientras no había conexión */
async function syncMessages(id) {
  try {
    const msgs = await api(`/conversations/${id}/messages?limit=50`);
    if (!state.conv || state.conv.id != id || current !== 'chat') return;
    msgs.slice().reverse().forEach(m => renderMsg(m, false));
  } catch { }
}

function renderMsg(m, animate = true) {
  const area = $('#chat-messages');
  const empty = $('#chat-empty'); if (empty) empty.remove();
  if (m.id && area.querySelector(`[data-mid="${m.id}"]`)) return;
  hideTyping();
  const mine = state.me && m.sender_id === state.me.id;
  const el = document.createElement('div');
  el.className = `bubble ${mine ? 'me' : 'them'}`;
  if (m.id) el.dataset.mid = m.id;
  if (!animate) el.style.animation = 'none';
  // «Reportar» en cada mensaje recibido (moderacion.html §3: solo se revisa lo que un participante reporta)
  const flag = !mine && m.id ? ` · <button type="button" data-flag-msg="${+m.id}" aria-label="Reportar este mensaje" style="all:unset;cursor:pointer;text-decoration:underline">Reportar</button>` : '';
  el.innerHTML = `${esc(m.content)}<time>${fmtTime(m.created_at)}${flag}</time>`;
  area.appendChild(el);
  area.scrollTop = area.scrollHeight;
}
function showTyping() {
  const area = $('#chat-messages');
  if (!$('#typing', area)) {
    area.insertAdjacentHTML('beforeend', `<div class="typing" id="typing"><i>${FX.PAW}</i><i>${FX.PAW}</i><i>${FX.PAW}</i></div>`);
    area.scrollTop = area.scrollHeight;
  }
  clearTimeout(state.typingTimer);
  state.typingTimer = setTimeout(hideTyping, 3500);
}
function hideTyping() { const t = $('#typing'); if (t) t.remove(); }

const WS_PING_MS = 25000, WS_MAX_DELAY = 30000;
function connectWS(id) {
  closeWS();
  if (!state.token) return;
  const local = ['localhost', '127.0.0.1'].includes(location.hostname) && location.port !== '8001' && location.port !== '';
  const host = local ? `${location.hostname}:8001` : location.host;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let ws;
  try { ws = new WebSocket(`${proto}//${host}/ws/chat/${id}?token=${encodeURIComponent(state.token)}`); } catch { return scheduleReconnect(id); }
  state.ws = ws;
  ws.onopen = () => {
    if (state.ws !== ws) return;
    const reconnected = state.wsAttempt > 0;
    state.wsAttempt = 0;
    // ping cada 25 s para que proxies y celulares no corten la conexión inactiva
    ws._ping = setInterval(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping' })); }, WS_PING_MS);
    if (reconnected) syncMessages(id);
  };
  ws.onmessage = ev => {
    let d; try { d = JSON.parse(ev.data); } catch { return; }
    if (d.type === 'pong') return;
    if (d.type === 'typing') { if (!state.me || d.sender_id !== state.me.id) showTyping(); return; }
    if (d.type === 'error') {
      // Cuenta limitada (teléfono sin verificar, verificación de edad...): mismo trato que un error de api()
      const err = new Error(d.detail || 'No pudimos enviar tu mensaje.');
      err.code = d.code;
      if (err.code === 'phone_verification_required' && current !== 'verify-phone') { setTimeout(() => startPhoneVerify(), 50); err.message = 'Primero verifica tu teléfono 📲'; }
      if (err.code && window.Cumplimiento) Cumplimiento.onApiError(err);
      toast(err.message, 'error');
      return;
    }
    if (d.content) {
      renderMsg(d);
      if (state.me && d.sender_id !== state.me.id) api(`/conversations/${id}/read`, { method: 'PATCH' }).catch(() => {});
    }
  };
  ws.onclose = ev => {
    clearInterval(ws._ping);
    if (state.ws !== ws) return;  // cierre intencional (closeWS)
    state.ws = null;
    // 4401/4403/1008: sin permiso o token inválido; no tiene caso reintentar
    if ([1008, 4401, 4403].includes(ev.code)) return;
    scheduleReconnect(id);
  };
}
/* Reintento con espera exponencial: 1 s, 2 s, 4 s... hasta 30 s, solo mientras el chat siga abierto */
function scheduleReconnect(id) {
  clearTimeout(state.wsRetry);
  if (current !== 'chat' || !state.conv || state.conv.id != id || !state.token || document.hidden) return;
  const delay = Math.min(WS_MAX_DELAY, 1000 * 2 ** state.wsAttempt);
  state.wsAttempt++;
  state.wsRetry = setTimeout(() => {
    if (current === 'chat' && state.conv && state.conv.id == id && !state.ws) connectWS(id);
  }, delay);
}
function closeWS() {
  clearTimeout(state.wsRetry);
  if (state.ws) { const w = state.ws; state.ws = null; clearInterval(w._ping); try { w.close(); } catch { } }
}

async function sendChat(e) {
  e.preventDefault();
  const input = $('#chat-input');
  const content = input.value.trim();
  if (!content || !state.conv) return;
  input.value = '';
  if (state.ws && state.ws.readyState === 1) {
    state.ws.send(JSON.stringify({ type: 'message', content }));
  } else {
    try { const m = await api(`/conversations/${state.conv.id}/messages`, { method: 'POST', body: { content } }); renderMsg(m); }
    catch (err) { toast(err.message, 'error'); input.value = content; }
  }
}

/* ============================================================
   Listas genéricas
   ============================================================ */
async function openList(title, sub, fetcher, renderer, opts = {}) {
  $('#list-title').firstChild.textContent = title;
  $('#list-sub').textContent = sub || '';
  const act = $('#list-action');
  act.classList.toggle('hidden', !opts.action);
  act.onclick = opts.action || null;
  const chips = $('#list-chips');
  chips.classList.toggle('hidden', !opts.chips);
  if (opts.chips) {
    chips.innerHTML = opts.chips.map((c, i) => `<span class="chip ${i ? '' : 'on'}" data-v="${c[0]}">${c[1]}</span>`).join('');
    $$('.chip', chips).forEach(c => c.onclick = () => { $$('.chip', chips).forEach(x => x.classList.remove('on')); c.classList.add('on'); load(c.dataset.v); });
  }
  const box = $('#list-container');
  navigate('list');
  async function load(filter) {
    box.innerHTML = FX.skeletonList(4);
    try {
      const items = await fetcher(filter);
      box.innerHTML = items.length ? `<div class="col stagger">${items.map((it, i) => renderer(it).replace(/^(\s*<div)/, `$1 style="--i:${i}"`)).join('')}</div>` : FX.empty(opts.emptyTitle || 'Nada por aquí todavía', opts.emptyText || '', opts.emptyBtn);
      FX.decorate(box);
      if (opts.after) opts.after(box, items);
    } catch (e) { toast(e.message, 'error'); box.innerHTML = ''; }
  }
  load(opts.chips ? opts.chips[0][0] : undefined);
}

function dogRow(d) {
  return `<div class="card p row tap" data-dog="${d.id}"><div class="thumb">${imgOrDog(photo(d), 34)}</div>
    <div class="grow"><b class="ellipsis">${esc(d.name)}</b><div class="small muted ellipsis">${esc([d.breed || 'Mestizo', age(d.age_years, d.age_months), d.distance_km != null ? dist(d.distance_km) : d.city].filter(Boolean).join(' · '))}</div></div>
    ${d.is_hidden ? '<span class="badge b-gray">OCULTO</span>' : `<span class="badge ${d.status === 'available' ? 'b-green' : 'b-yellow'}">${esc(STATUS_LABEL[d.status] || d.status)}</span>`}</div>`;
}
const HIDDEN_NOTE = '<div class="card p small mt12" style="background:var(--sand)">🙈 Ocultamos esta publicación porque no cumple las reglas de la comunidad. Solo tú la ves. Si crees que es un error, escríbenos desde Ayuda.</div>';
function refugeRow(r) {
  return `<div class="card p row tap" data-refuge="${r.id}"><div class="avatar" style="background:var(--pink);border-radius:16px">${esc(initials(r.name))}</div>
    <div class="grow"><b class="ellipsis">${esc(r.name)}</b> <svg width="14" height="14"><use href="#shield"/></svg><div class="small muted">${esc(r.city || '')} · ${r.adopted_count} adopciones · ${r.points} pts</div></div><b>→</b></div>`;
}

function openReportsList(type) {
  const lost = type === 'lost';
  openList(lost ? 'Perdidos cerca' : 'Encontrados cerca', state.city, () => api(`/lost-reports?${locParams({ report_type: type, radius_km: 50 })}`), reportRow,
    { emptyTitle: lost ? 'No hay perdidos reportados cerca' : 'No hay encontrados cerca', emptyText: '¡Buenas noticias! 💚', action: () => openReportForm(type) });
}
function openRefugesList() {
  openList('Refugios', 'Verificados por GuauWoow', () => api(`/refuges${state.coords ? '' : '?city=' + encodeURIComponent(state.city)}`), refugeRow,
    { emptyTitle: 'Aún no hay refugios aquí', emptyText: '¿Tienes uno? Regístralo gratis', emptyBtn: { action: 'refuge-register', label: 'Registrar refugio' } });
}
function openAdoptList() {
  openList('En adopción', 'Refugios, casas de paso y particulares · ' + state.city, size => api(`/dogs/featured?${locParams({ limit: 20 })}`).then(ds => size ? ds.filter(d => d.size === size) : ds), dogRow,
    { action: openPublish, chips: [['', 'Todos'], ['Pequeño', 'Pequeños'], ['Mediano', 'Medianos'], ['Grande', 'Grandes']], emptyTitle: 'Sin perritos con ese filtro', emptyBtn: { action: 'publish', label: 'Publicar en adopción' } });
}
function openMyDogs() {
  openList('Mis publicaciones', 'Perritos que diste en adopción', () => api('/dogs/me'), dogRow,
    { action: openPublish, emptyTitle: 'Aún no publicas perritos', emptyBtn: { action: 'publish', label: 'Publicar uno' } });
}
function openMyReports() {
  openList('Mis reportes', 'Perdidos y encontrados', () => api('/lost-reports/me'), reportRow, { action: () => openReportForm('found'), emptyTitle: 'No tienes reportes', emptyText: 'Sube aquí perritos perdidos o encontrados en la calle 🐾' });
}
/* Mis pedidos, carrito, checkout y "Mi tienda" del refugio viven en tienda.js (window.Tienda) */

function openMyMatches() {
  openList('Solicitudes', 'Adopciones que enviaste y recibiste', async role => {
    const ms = await api('/matches');
    return ms.filter(m => role === 'owner' ? m.dog.owner_id === state.me.id : m.user_id === state.me.id);
  }, m => {
    const owner = m.dog.owner_id === state.me.id;
    const col = { approved: 'b-green', completed: 'b-teal', rejected: 'b-red' }[m.status] || 'b-yellow';
    return `<div class="card p"><div class="row"><div class="thumb">${imgOrDog(photo(m.dog), 32)}</div>
      <div class="grow"><b class="ellipsis">${esc(m.dog.name)}</b><div class="small muted ellipsis">${owner ? `Solicitó ${esc(m.user.full_name)}` : 'Tu solicitud'} · ${timeAgo(m.created_at)}</div></div>
      <span class="badge ${col}">${esc(STATUS_LABEL[m.status] || m.status)}</span></div>
      ${owner ? contactHtml(m) : (m.status === 'pending_application' ? '<div class="small muted mt8">🔒 Tus datos de contacto se comparten solo si aceptan tu solicitud.</div>' : '')}
      <div class="row mt12" style="flex-wrap:wrap;gap:8px">
        ${owner && m.has_application ? `<button class="btn btn-sm btn-lila" data-app="${m.id}">Ver solicitud${m.compatibility != null ? ` · ${m.compatibility}%` : ''}</button>` : ''}
        ${!owner && !m.has_application && m.status === 'pending_application' ? `<button class="btn btn-sm btn-orange" data-fill="${m.id}">Llenar cuestionario</button>` : ''}
        ${m.conversation_id ? `<button class="btn btn-sm" data-conv-open="${m.conversation_id}">Chat</button>` : ''}
      </div></div>`;
  }, {
    chips: [['adopter', 'Mis solicitudes'], ['owner', 'Recibidas']], emptyTitle: 'Sin solicitudes aquí',
    after: (box, items) => {
      $$('[data-app]', box).forEach(b => b.onclick = () => openApplication(+b.dataset.app, items.find(m => m.id == b.dataset.app)));
      $$('[data-fill]', box).forEach(b => b.onclick = () => { const m = items.find(x => x.id == b.dataset.fill); state.matchId = m.id; state.matchDog = m.dog; openQuestionnaire(); });
      $$('[data-conv-open]', box).forEach(b => b.onclick = () => openChat(b.dataset.convOpen));
    },
  });
}

/* Datos de contacto del solicitante: el backend los manda solo si la solicitud se aceptó */
function contactHtml(m) {
  const u = m.user || {};
  const visible = m.contact_visible ?? !!(u.email || u.phone);
  if (!visible || (!u.email && !u.phone)) return `<div class="small muted mt8">🔒 Los datos de contacto se mostrarán cuando se acepte la solicitud${m.conversation_id ? '. Mientras, usa el chat.' : '.'}</div>`;
  const tel = (u.phone || '').replace(/[^\d+]/g, '');
  return `<div class="small mt8 row" style="flex-wrap:wrap;gap:6px 14px">${u.email ? `<a class="link" href="mailto:${esc(u.email)}">✉️ ${esc(u.email)}</a>` : ''}${tel ? `<a class="link" href="tel:${esc(tel)}">📞 ${esc(u.phone)}</a>` : ''}</div>`;
}

const Q_LABELS = {
  housing: ['Vivienda', { casa_con_jardin: 'Casa con patio', casa_sin_jardin: 'Casa sin patio', departamento_grande: 'Depa grande', departamento_chico: 'Depa chico' }],
  experience: ['Experiencia', { mucha: 'Toda la vida', alguna: 'Alguna', poca: 'Poca', ninguna: 'Primer perro' }],
  children: ['Niños', { si_chicos: 'Menores de 10', si_grandes: 'Mayores de 10', no: 'No' }],
  other_pets: ['Otras mascotas', { perros: 'Perros', gatos: 'Gatos', otros: 'Otros', no: 'No' }],
  budget: ['Presupuesto', {}], hours_alone: ['Horas solo', {}], outdoor: ['Exterior', {}],
};
async function openApplication(matchId, m) {
  const body = $('#application-body');
  body.innerHTML = FX.inlineLoader('Cargando solicitud...');
  $('#app-title').textContent = `Solicitud por ${m.dog.name}`;
  navigate('application');
  try {
    const a = await api(`/matches/${matchId}/application`);
    const ans = a.answers || {};
    const score = a.compatibility ?? m.compatibility;
    body.innerHTML = `
      <div class="card p row pop-in">${avatarHtml(m.user, 56)}<div class="grow"><b>${esc(m.user.full_name)}</b><div class="small muted">Envió ${timeAgo(a.created_at)}</div></div>
      ${score != null ? `<div class="score-ring" style="--p:${score}"><b>${score}%</b></div>` : ''}</div>
      <div class="card p mt12"><div class="small muted" style="font-weight:800">CONTACTO</div>${contactHtml(m)}</div>
      <div class="card p mt12 col" style="gap:8px">${Object.entries(Q_LABELS).filter(([k]) => ans[k]).map(([k, [l, map]]) => `<div class="between"><span class="small muted">${l}</span><b>${esc(map[ans[k]] || ans[k])}</b></div>`).join('')}</div>
      ${ans.why ? `<div class="card p mt12"><div class="small muted" style="font-weight:800">¿POR QUÉ QUIERE ADOPTAR?</div><p class="body mt8">${esc(ans.why)}</p></div>` : ''}
      <div class="col mt20">
        ${m.status === 'pending_application' ? `<button class="btn block btn-green shine" id="ap-approve">Aprobar y abrir chat</button><button class="btn block btn-ghost" id="ap-reject">No esta vez</button>` : ''}
        ${m.status === 'approved' ? `<button class="btn block btn-orange shine" id="ap-complete">🎉 Confirmar adopción</button>` : ''}
        ${m.conversation_id ? `<button class="btn block" id="ap-chat">Ir al chat</button>` : ''}
      </div>`;
    FX.decorate(body);
    const ap = $('#ap-approve'), rj = $('#ap-reject'), cp = $('#ap-complete'), ch = $('#ap-chat');
    if (ap) ap.onclick = () => withBtn(ap, async () => { const c = await api(`/matches/${matchId}/approve`, { method: 'POST' }); await FX.success('¡Aprobada!', 'Ya pueden chatear para conocerse'); openChat(c.id); });
    if (rj) rj.onclick = () => withBtn(rj, async () => { if (!confirm('¿Rechazar esta solicitud?')) return; await api(`/matches/${matchId}/reject`, { method: 'POST' }); toast('Solicitud rechazada'); back(); });
    if (cp) cp.onclick = () => withBtn(cp, async () => { await api(`/matches/${matchId}/complete`, { method: 'POST' }); await FX.success('¡Adopción completada!', `${m.dog.name} tiene nueva familia 💚`, 2200); back(); });
    if (ch) ch.onclick = () => openChat(m.conversation_id);
  } catch (e) { toast(e.message, 'error'); back(); }
}

/* ============================================================
   Refugios
   ============================================================ */
async function openRefuge(id) {
  const body = $('#refuge-body');
  body.innerHTML = FX.inlineLoader('Visitando el refugio...');
  navigate('refuge');
  try {
    const [r, dogs] = await Promise.all([api(`/refuges/${id}`), api(`/refuges/${id}/dogs`).catch(() => [])]);
    state.refuge = r;
    // Sin Mercado Pago conectado el refugio no puede recibir donativos (salvo el respaldo con la cuenta de la plataforma).
    // donations_ready no exige RFC (a diferencia de la tienda); si el backend no lo manda se usa la regla anterior.
    const donOff = r.donations_ready != null ? r.donations_ready === false : (r.seller_payments_ready === false && !state.config.donations_fallback);
    const ownRefuge = !!(state.me && r.user_id === state.me.id);  // nadie se dona a sí mismo (donativos §8)
    $('#refuge-flag').classList.toggle('hidden', !state.me || r.user_id === state.me.id);
    body.innerHTML = `
      <div class="center pad pop-in"><div class="avatar" style="width:92px;height:92px;margin:0 auto;background:var(--pink);font-size:30px;border-radius:30px;border-width:3px">${esc(initials(r.name))}</div>
      <div class="h2 mt12 row" style="justify-content:center;gap:6px">${esc(r.name)} <svg width="20" height="20"><use href="#shield"/></svg></div><div class="small muted">${esc([r.city, r.country].filter(Boolean).join(', '))} · Desde ${fmtDate(r.created_at)}</div></div>
      <div class="pad row mt16"><div class="card stat"><b>${r.adopted_count}</b><span>Adopciones</span></div><div class="card stat"><b>${r.rescued_count}</b><span>Rescates</span></div><div class="card stat"><b>${r.points}</b><span>Puntos</span></div></div>
      ${r.description ? `<p class="pad body mt16">${esc(r.description)}</p>` : ''}
      <div class="pad mt20"><span class="h2">Buscan hogar</span></div>
      <div class="hscroll mt8">${dogs.filter(d => d.status === 'available').map(d => `<div class="card dog-card tap" data-dog="${d.id}"><div class="ph">${imgOrDog(photo(d), 60)}</div><div class="nm">${esc(d.name)}</div><div class="mt">${esc(d.breed || 'Mestizo')}</div></div>`).join('') || '<p class="small muted">Por ahora no hay perritos publicados.</p>'}</div>
      <div class="pad mt16"><div class="card p" style="background:var(--yellow)"><div class="h2 row" style="gap:8px"><svg width="22" height="22"><use href="#gift"/></svg> Donar</div>
        <p class="small muted">Tu donativo va directo a la cuenta de Mercado Pago de este refugio. Donar es voluntario: no es requisito para adoptar y no suma puntos ni da productos o descuentos.</p>
        <p class="small mt8" id="don-tax">${r.is_donataria ? '🧾 Este refugio declara ser donataria autorizada: tu donativo es deducible solo si le pides tu CFDI de donativo (aplican los límites del SAT).' : '🧾 Este refugio no es donataria autorizada: tu donativo no es deducible de impuestos.'}</p>
        <p class="small muted mt8" id="don-limits"></p>
        <div class="chips mt12" id="don-amounts">${[50, 100, 250, 500].map((a, i) => `<span class="chip ${i === 1 ? 'on' : ''}" data-v="${a}">${money(a)}</span>`).join('')}<span class="chip" data-v="other">Otro</span></div>
        <input id="don-other" class="inp mt12 hidden" type="number" min="10" placeholder="Monto en MXN">
        <label class="row small mt12" style="align-items:flex-start"><input type="checkbox" id="don-share" style="width:20px;height:20px;flex-shrink:0;margin-top:2px"> <span>Compartir mi nombre con el refugio (si no, tu donativo es anónimo).</span></label>
        <label class="row small mt12" style="align-items:flex-start"><input type="checkbox" id="don-policy" style="width:20px;height:20px;flex-shrink:0;margin-top:2px"> <span>Leí la <a href="/app/legal/donativos.html" target="_blank" rel="noopener">Política de donativos</a>.</span></label>
        ${donOff ? '<div class="small shop-note mt12">Este refugio aún no activa cobros. En cuanto conecte Mercado Pago podrás donarle desde aquí 💚</div>' : ''}
        ${ownRefuge ? '<div class="small shop-note mt12">No puedes donar a tu propio refugio.</div>' : ''}
        <button class="btn block btn-orange shine mt12" id="don-btn" ${donOff || ownRefuge ? 'disabled' : ''}>Donar con Mercado Pago</button></div></div>`;
    FX.decorate(body);
    $$('#don-amounts .chip').forEach(c => c.onclick = () => { $$('#don-amounts .chip').forEach(x => x.classList.remove('on')); c.classList.add('on'); $('#don-other').classList.toggle('hidden', c.dataset.v !== 'other'); });
    $('#don-btn').onclick = () => donate(r);
    donationRules().then(rules => {
      const box = $('#don-limits'), d = rules && rules.donations;
      if (!box || !d) return;
      box.textContent = `Tope por donativo: ${money(d.max_mxn)} · tope diario por cuenta: ${money(d.daily_max_mxn)}. ${Number(d.fee_percent) > 0 ? `GuauWoow cobra ${d.fee_percent} % de comisión` : 'GuauWoow no cobra comisión'}; Mercado Pago le cobra su comisión al refugio.`;
    });
  } catch (e) { toast(e.message, 'error'); back(); }
}
/* Topes y comisión de donativos (GET /cumplimiento/reglas; services/reglas.py) */
let rulesPromise = null;
function donationRules() {
  if (!rulesPromise) rulesPromise = api('/cumplimiento/reglas').catch(() => { rulesPromise = null; return null; });
  return rulesPromise;
}

async function donate(r) {
  const on = $('#don-amounts .chip.on');
  const amount = on.dataset.v === 'other' ? parseFloat($('#don-other').value) : parseFloat(on.dataset.v);
  if (!amount || amount < 10) return toast('El monto mínimo es $10', 'error');
  const rules = await donationRules();
  const max = rules && rules.donations ? Number(rules.donations.max_mxn) : null;
  if (max && amount > max) return toast(`El tope por donativo es de ${money(max)}. Para donar más, contacta directo al refugio`, 'error');
  if (!$('#don-policy').checked) return toast('Marca que leíste la Política de donativos para continuar', 'error');
  const btn = $('#don-btn');
  await withBtn(btn, async () => {
    const d = await api('/payments/donations', { method: 'POST', body: { refuge_id: r.id, amount, share_name: $('#don-share').checked, accepted_policy: true } });
    if (d.checkout_url) { FX.showLoading('Te llevamos a Mercado Pago', ['Pagas en Mercado Pago; GuauWoow no ve ni guarda tu tarjeta'], 'run'); location.href = d.checkout_url; return KEEP_LOADING; }
    FX.boneBurst(btn, 8);
    await FX.success('¡Gracias por donar!', `${money(amount)} para ${r.name}`);
    openRefuge(r.id); stack.pop();
  });
}

async function submitRefuge(e) {
  e.preventDefault();
  const name = $('#rg-name').value.trim();
  if (!name) return toast('Escribe el nombre del refugio', 'error');
  if (!$('#rg-annex').checked) return toast('Acepta los Términos para Refugios y el Acuerdo de datos', 'error');
  const btn = $('#refuge-form button[type=submit]');
  await withBtn(btn, async () => {
    const documents = await uploadDocuments(docStore);
    await api('/refuges/register', { method: 'POST', body: { name, description: $('#rg-desc').value.trim() || null, city: $('#rg-city').value.trim() || state.city, country: $('#rg-country').value.trim() || 'México', documents, accepted_annex: true } });
    state.me = await api('/users/me');
    docStore.length = 0; renderDocDrop();
    await FX.success('¡Solicitud enviada!', 'Te avisaremos en cuanto revisemos tus documentos');
    navigate('my-refuge', { push: false });
  });
}
/* Selector de documentos del refugio: fotos o PDF, máximo 5 y 10 MB cada uno */
const docStore = [];
const DOC_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
function renderDocDrop() {
  const box = $('#rg-docs');
  box.innerHTML = docStore.map((f, i) => {
    const pdf = f.type === 'application/pdf';
    return `<div class="doc-item"><div class="doc-ic">${pdf ? 'PDF' : `<img src="${URL.createObjectURL(f)}" alt="">`}</div><span class="grow ellipsis">${esc(f.name || 'Documento')}</span><button type="button" data-doc-rm="${i}" aria-label="Quitar ${esc(f.name || 'documento')}">×</button></div>`;
  }).join('') + (docStore.length < 5 ? `<button type="button" class="btn btn-sm btn-ghost doc-add" id="rg-docs-add"><svg width="16" height="16"><use href="#plus"/></svg> Agregar documento</button>` : '');
  FX.decorate(box);
  const add = $('#rg-docs-add');
  if (add) add.onclick = () => $('#rg-docs-file').click();
  $$('[data-doc-rm]', box).forEach(b => b.onclick = () => { docStore.splice(+b.dataset.docRm, 1); renderDocDrop(); });
}
function addDocs(files) {
  const ok = [...files].filter(f => DOC_TYPES.includes(f.type) || /\.pdf$/i.test(f.name || ''));
  if (ok.length < files.length) toast('Solo se aceptan fotos (JPG, PNG, WebP) o PDF', 'error');
  if (ok.some(f => f.type === 'application/pdf' && f.size > 10 * 1024 * 1024)) return toast('Cada PDF debe pesar menos de 10 MB', 'error');
  const room = 5 - docStore.length;
  if (ok.length > room) toast('Máximo 5 documentos', 'error');
  docStore.push(...ok.slice(0, room));
  renderDocDrop();
}

async function submitFoster(e) {
  e.preventDefault();
  if (!$('#fh-annex').checked) return toast('Acepta los Términos para casas de paso y el Acuerdo de datos', 'error');
  const btn = $('#foster-form button[type=submit]');
  await withBtn(btn, async () => {
    await api('/foster-homes/register', { method: 'POST', body: { description: $('#fh-desc').value.trim() || null, city: $('#fh-city').value.trim() || state.city, country: $('#fh-country').value.trim() || 'México', capacity: parseInt($('#fh-cap').value) || 1, accepted_annex: true } });
    await FX.success('¡Gracias, héroe!', 'Te avisaremos cuando aprobemos tu casa de paso');
    back();
  });
}

async function loadMyRefuge() {
  const body = $('#my-refuge-body');
  body.innerHTML = FX.inlineLoader('Cargando tu refugio...');
  let r;
  try { r = await api('/refuges/me'); }
  catch (e) {
    if (e.status === 404) {
      $('#mr-status').textContent = '';
      body.innerHTML = FX.empty('Aún no registras un refugio', `Regístralo para publicar perritos y recibir donativos${shopOn() ? ', y vender en la tienda solidaria' : ''}`, { action: 'refuge-register', label: 'Registrar refugio' });
      FX.decorate(body);
    } else toast(e.message, 'error');
    return;
  }
  $('#mr-status').textContent = r.name;
  if (r.status !== 'approved') {
    body.innerHTML = `<div class="empty">${FX.sniffDog()}<h3>${r.status === 'pending' ? 'Estamos revisando tus documentos' : r.status === 'suspended' ? 'Tu refugio está suspendido' : 'Tu solicitud no fue aprobada'}</h3><p>${r.status === 'pending' ? 'Te avisaremos por notificación en cuanto terminemos de revisarlos.' : 'Revisa tus notificaciones para conocer el motivo.'}</p></div>`;
    return;
  }
  const stats = await api('/refuges/me/stats').catch(() => null);
  const byStatus = (stats && stats.dogs_by_status) || {};
  // Los rescates, adopciones y casas de paso fuera de la app los registra un admin (un refugio no se suma puntos solo)
  const { mail: supportMail } = supportLinks();
  const manualPointsNote = `Los rescates, adopciones y casas de paso fuera de la app los registra un administrador después de verificarlos${supportMail ? `: escríbenos a <a href="mailto:${esc(supportMail)}?subject=${encodeURIComponent('Puntos de mi refugio')}">${esc(supportMail)}</a>` : ''}.`;
  body.innerHTML = `
    <div class="row pop-in"><div class="card stat"><b>${r.points}</b><span>Puntos</span></div><div class="card stat"><b>${r.adopted_count}</b><span>Adopciones</span></div><div class="card stat"><b>${stats ? money(stats.donations_total || 0) : '—'}</b><span>Donado</span></div></div>
    <div class="card p mt12 row" style="background:var(--lila)"><div class="grow"><b>${stats ? stats.pending_applications || 0 : 0} solicitudes por revisar</b><div class="small muted">${byStatus.available || 0} disponibles · ${byStatus.in_process || 0} en proceso</div></div><button class="btn btn-sm" id="mr-apps">Ver</button></div>
    <div class="col mt16"><span class="lbl">Acciones rápidas</span>
      <div class="row"><button class="btn btn-sm btn-orange grow" id="mr-publish">+ Publicar perrito</button></div>
      <p class="small muted mt8">${manualPointsNote}</p></div>
    <div id="mr-transparency"></div>
    <div data-shop><div class="card p mt16 row tap" data-act="my-shop" role="button" tabindex="0" style="background:var(--yellow)"><svg width="30" height="30" aria-hidden="true"><use href="#store"/></svg><div class="grow"><b>Mi tienda</b><div class="small muted">Productos, pedidos, facturas, cobros y estado de cuenta</div></div><b>→</b></div></div>
    <div class="mt20"><div class="between"><span class="h2">Puntos por semana</span><svg width="22" height="22" style="color:var(--orange)"><use href="#chart"/></svg></div><div class="card p mt12"><div id="mr-chart-points" style="height:200px"></div></div></div>
    <div class="row mt12" style="align-items:stretch;gap:12px"><div class="card p grow"><b class="small">Perritos por estado</b><div id="mr-chart-status" style="height:170px"></div></div></div>
    <div class="card p mt12"><b class="small">¿De dónde vienen tus puntos?</b><div id="mr-chart-actions" style="height:170px"></div></div>
    <div class="mt20"><span class="h2">Historial de puntos</span><div class="col mt12" id="mr-points">${FX.skeletonList(2)}</div></div>`;
  chart('#mr-chart-status', { type: 'donut', labels: ['Disponibles', 'En proceso', 'Adoptados', 'Casa de paso'], series: [{ name: 'Perritos', data: [byStatus.available || 0, byStatus.in_process || 0, byStatus.adopted || 0, byStatus.in_foster || 0] }], height: 170, centerLabel: 'perritos' });
  FX.decorate(body);
  $('#mr-apps').onclick = openMyMatches;
  $('#mr-publish').onclick = openPublish;
  loadRefugeTransparency();
  try {
    const pts = await api(`/refuges/${r.id}/points`);
    renderPointCharts(pts);
    $('#mr-points').innerHTML = pts.length ? pts.slice(0, 15).map(p => `<div class="card p between"><div><b>${esc(p.description || p.action)}</b><div class="small muted">${timeAgo(p.created_at)}</div></div><span class="badge b-green">+${p.points}</span></div>`).join('') : '<p class="small muted">Aún sin movimientos.</p>';
  } catch { $('#mr-points').innerHTML = ''; }
}

/* Informe de transparencia: una persona física decide si sus cifras aparecen con su nombre (terminos-refugios 13.2;
   acuerdo-datos-refugios 15.2). Casilla desmarcada de inicio; cada cambio queda en la bitácora de consentimientos. */
async function loadRefugeTransparency() {
  const box = $('#mr-transparency');
  if (!box) return;
  let t;
  try { t = await api('/cumplimiento/transparencia/mi-refugio'); } catch { box.innerHTML = ''; return; }
  const link = '<a class="link" href="/app/legal/transparencia-fondos.html" target="_blank" rel="noopener">A dónde va tu dinero</a>';
  if (!t.requiere_consentimiento) {
    box.innerHTML = `<div class="card p mt12 small"><b>Transparencia</b><div class="muted mt4">Como persona moral, las cifras agregadas de tu refugio (donativos y ventas por mes) aparecen con su nombre en el informe de transparencia y en ${link}.</div></div>`;
    return;
  }
  box.innerHTML = `<div class="card p mt12">
    <label class="row small cp-check" for="mr-transp"><input type="checkbox" id="mr-transp" ${t.publicar ? 'checked' : ''}>
      <span><b>Publicar mis cifras con mi nombre</b><br><span class="muted">Como persona física, tus montos de donativos y ventas son datos patrimoniales: solo aparecen con tu nombre en el informe de transparencia y en ${link} si marcas esta casilla. Si no, se suman en «Otros Refugios». Puedes desmarcarla cuando quieras.</span></span></label>
    <div class="small muted mt4" id="mr-transp-since">${t.publicar && t.desde ? 'Autorizado desde el ' + esc(fmtDate(t.desde)) : ''}</div></div>`;
  const input = $('#mr-transp', box);
  input.addEventListener('change', async () => {
    input.disabled = true;
    try {
      const r = await api('/cumplimiento/transparencia/mi-refugio', { method: 'POST', body: { publicar: input.checked } });
      input.checked = !!r.publicar;
      $('#mr-transp-since', box).textContent = r.publicar && r.desde ? 'Autorizado desde el ' + fmtDate(r.desde) : '';
      toast(r.publicar ? 'Listo: tus cifras aparecerán con tu nombre' : 'Listo: tus cifras se suman en «Otros Refugios»', 'ok');
    } catch (e) { input.checked = !input.checked; toast(e.message, 'error'); }
    input.disabled = false;
  });
}

async function loadRanking() {
  const list = $('#ranking-list');
  list.innerHTML = FX.inlineLoader('Contando huellitas...');
  try {
    const city = $('#ranking-city').value.trim();
    const rs = await api(`/refuges/ranking${city ? '?city=' + encodeURIComponent(city) : ''}`);
    if (!rs.length) { list.innerHTML = FX.empty('Aún no hay refugios en el ranking'); return; }
    const top = [rs[1], rs[0], rs[2]];
    const H = [110, 150, 86], C = ['var(--blue)', 'var(--yellow)', 'var(--pink)'], N = [2, 1, 3];
    list.innerHTML = `<div class="podium">${top.map((r, i) => r ? `<div class="pd" data-refuge="${r.id}">${N[i] === 1 ? '<div class="crown">👑</div>' : ''}<div class="avatar" style="margin:0 auto;width:${N[i] === 1 ? 62 : 50}px;height:${N[i] === 1 ? 62 : 50}px;background:${C[i]}">${esc(initials(r.name))}</div>
      <div class="small mt8 ellipsis" style="font-weight:800">${esc(r.name)}</div><div class="small muted">${r.points} pts</div>
      <div class="blk mt8" style="height:${H[i]}px;background:${C[i]};animation-delay:${i * .15}s">${N[i]}</div></div>` : '<div class="pd"></div>').join('')}</div>
      <div class="col mt16 stagger">${rs.slice(3).map((r, i) => `<div class="card p row tap" data-refuge="${r.id}" style="--i:${i}"><b style="width:28px">${i + 4}</b>${avatarHtml({ full_name: r.name }, 40)}<div class="grow"><b class="ellipsis">${esc(r.name)}</b><div class="small muted">${r.adopted_count} adopciones · ${esc(r.city || '')}</div></div><span class="badge b-yellow">${r.points} pts</span></div>`).join('')}</div>
      <div class="card p mt16"><b class="small">Puntos del top 8</b><div id="rank-chart" style="height:${Math.min(8, rs.length) * 30 + 40}px"></div></div>
      <div class="card p mt16 small" style="background:var(--lila)">🏆 Los refugios suman puntos por rescates, adopciones y casas de paso. Los donativos no suman puntos.</div>`;
    const top8 = rs.slice(0, 8);
    chart('#rank-chart', { type: 'hbar', labels: top8.map(r => r.name), series: [{ name: 'Puntos', data: top8.map(r => r.points) }], valueLabels: true, height: Math.min(8, rs.length) * 30 + 40 });
  } catch (e) { toast(e.message, 'error'); list.innerHTML = ''; }
}

/* ============================================================
   Mapa (Leaflet + OpenStreetMap)
   ============================================================ */
function pinIcon(color, label, img = '') {
  return L.divIcon({ className: '', iconSize: [38, 46], iconAnchor: [19, 44], popupAnchor: [0, -40],
    html: `<div class="map-pin-wrap"><div class="map-pin" style="background:${color}">${imgTag(img) || `<span>${esc(label)}</span>`}</div></div>` });
}
function mapPopup(img, html) { return `<div class="map-pop">${imgTag(img)}<div>${html}</div></div>`; }
async function loadMap() {
  if (!window.L) return toast('No se pudo cargar el mapa', 'error');
  const center = state.coords ? [state.coords.lat, state.coords.lon] : (CITIES.find(c => c[0] === state.city) || CITIES[0]).slice(1);
  if (!state.map) {
    state.map = L.map('leaflet-map', { zoomControl: false, attributionControl: true }).setView(center, 13);
    setMapTiles();
    ['lost', 'found', 'dog'].forEach(k => { state.mapLayers[k] = L.layerGroup().addTo(state.map); });
    state.mapLayers.me = L.layerGroup().addTo(state.map);
  } else state.map.setView(center, state.map.getZoom());
  setTimeout(() => state.map.invalidateSize(), 350);
  state.mapLayers.me.clearLayers();
  if (state.coords) {
    L.marker(center, { icon: L.divIcon({ className: '', iconSize: [18, 18], html: '<div class="me-dot"></div>' }) }).addTo(state.mapLayers.me);
    L.circle(center, { radius: 3500, color: '#33C7BE', weight: 2, fillOpacity: .06, dashArray: '6 6' }).addTo(state.mapLayers.me);
  }
  try {
    const q = `lat=${center[0]}&lon=${center[1]}&radius_km=30`;
    const [reports, dogs] = await Promise.all([api(`/lost-reports?${q}`), api(`/dogs/nearby?${q}`)]);
    ['lost', 'found', 'dog'].forEach(k => state.mapLayers[k].clearLayers());
    let n = 0;
    reports.filter(r => r.latitude != null).forEach(r => {
      const lost = r.report_type === 'lost';
      L.marker([r.latitude, r.longitude], { icon: pinIcon(lost ? '#FF6B5C' : '#21A39B', (r.dog_name || '?')[0], photo(r)) })
        .bindPopup(mapPopup(photo(r), `<b>${esc(r.dog_name)}</b><br>${lost ? 'Perdido' : 'Encontrado'} · ${timeAgo(r.created_at)}<br><a href="#" data-report="${r.id}">Ver reporte →</a>`))
        .addTo(state.mapLayers[lost ? 'lost' : 'found']); n++;
    });
    dogs.filter(d => d.latitude != null).forEach(d => {
      L.marker([d.latitude, d.longitude], { icon: pinIcon('#8E66D9', d.name[0], photo(d)) })
        .bindPopup(mapPopup(photo(d), `<b>${esc(d.name)}</b><br>En adopción · ${esc(d.breed || 'Mestizo')}<br><a href="#" data-dog="${d.id}">Ver perfil →</a>`))
        .addTo(state.mapLayers.dog); n++;
    });
    $('#map-sub').textContent = `${n} perritos en un radio de 30 km`;
  } catch (e) { toast(e.message, 'error'); }
  if (window.VET) VET.loadMapMarkers(center[0], center[1]);  // pines de veterinarias (veterinarias.js)
}

/* ============================================================
   Notificaciones y badges
   ============================================================ */
const NOTIF_ICON = { new_message: ['💬', 'var(--blue)'], new_like: ['❤️', 'var(--pink)'], new_application: ['📋', 'var(--lila)'], match_approved: ['🎉', 'var(--green)'], match_rejected: ['🐾', 'var(--sand)'],
  possible_match: ['✨', 'var(--yellow)'], refuge_approved: ['🏠', 'var(--green)'], refuge_rejected: ['🏠', 'var(--sand)'], new_order: ['🛒', 'var(--lila)'], donation: ['🎁', 'var(--yellow)'], reminder: ['⏰', 'var(--blue)'], adoption_completed: ['💚', 'var(--green)'],
  nearby_alert: ['📍', 'var(--pink)'], report_expired: ['⏳', 'var(--sand)'], report_contact: ['💬', 'var(--blue)'],
  order_paid: ['🛍️', 'var(--green)'], order_shipped: ['📦', 'var(--blue)'], order_delivered: ['📦', 'var(--green)'], order_expired: ['⌛', 'var(--sand)'],
  order_refund_pending: ['💸', 'var(--sand)'], order_refunded: ['💸', 'var(--sand)'],
  donation_received: ['🎁', 'var(--yellow)'], donation_receipt: ['💛', 'var(--yellow)'], report_resolved: ['🛡️', 'var(--green)'], content_hidden: ['🙈', 'var(--sand)'], moderation_alert: ['🚩', 'var(--pink)'],
  foster_home_approved: ['🏡', 'var(--green)'], foster_home_rejected: ['🏡', 'var(--sand)'],
  moderation_notice: ['⚖️', 'var(--sand)'], moderation_urgent: ['🚩', 'var(--pink)'], content_restored: ['👀', 'var(--green)'],
  copyright_notice_copy: ['©️', 'var(--sand)'] };
async function loadNotifications() {
  const list = $('#notifications-list');
  list.innerHTML = FX.skeletonList(4);
  try {
    const ns = await api('/notifications');
    list.innerHTML = ns.length ? `<div class="col stagger">${ns.map((n, i) => { const [ic, bg] = NOTIF_ICON[n.type] || ['🔔', 'var(--white)']; return `
      <div class="card p row tap" data-notif="${n.type}" data-ndata="${esc(JSON.stringify(n.data || {}))}" style="--i:${Math.min(i, 10)};${n.is_read ? '' : 'border-width:2.5px;box-shadow:var(--sh-btn)'}">
        <div class="avatar" style="background:${bg};font-size:20px">${ic}</div>
        <div class="grow"><b>${esc(n.title)}</b><div class="small muted" style="white-space:pre-line">${esc(n.body)}</div><div class="small muted mt8">${timeAgo(n.created_at)}</div></div>
        ${n.is_read ? '' : '<span style="width:10px;height:10px;border-radius:50%;background:var(--orange);flex-shrink:0"></span>'}</div>`; }).join('')}</div>`
      : FX.empty('Todo tranquilo por aquí', 'Te avisaremos de coincidencias, mensajes y solicitudes');
    if (ns.some(n => !n.is_read)) setTimeout(() => api('/notifications/read-all', { method: 'PATCH' }).then(refreshBadges).catch(() => {}), 2500);
  } catch (e) { toast(e.message, 'error'); list.innerHTML = ''; }
}
function notifAction(type, data = {}) {
  if (type === 'moderation_alert' || type === 'moderation_urgent') { location.href = '/admin/'; return; }
  // Medidas de moderación: apelar (moderacion.html §7) o contra-aviso por derechos de autor
  if (data.copyright_notice && /^DA-[A-Z0-9]+$/.test(data.copyright_notice)) { location.href = `/app/legal/derechos-de-autor.html?contraaviso=${encodeURIComponent(data.copyright_notice)}#formularios`; return; }
  if (data.moderation_action && /^MOD-[A-Z0-9]+$/.test(data.moderation_action)) { location.href = `/app/legal/moderacion.html?apelacion=${encodeURIComponent(data.moderation_action)}#apelacion`; return; }
  if (type.startsWith('veterinary') && window.VET) return VET.onNotif(type, data);
  if (window.Tienda && Tienda.onNotification(type, data)) return;  // pedidos, facturas y cobros (tienda.js)
  if (type === 'new_order' || type === 'donation_received') return navigate('my-refuge');
  if (data.conversation_id) return openChat(data.conversation_id);
  if (data.match_report_id) return openReport(data.match_report_id);
  if (data.report_id) return openReport(data.report_id);
  if (data.order_id) return openMyOrders();
  if (type === 'new_message') navigate('chat-list');
  else if (['new_like', 'new_application', 'match_approved', 'match_rejected', 'adoption_completed'].includes(type)) openMyMatches();
  else if (type === 'possible_match') openMyReports();
  else if (type.startsWith('refuge') || type === 'new_order' || type === 'donation') navigate('my-refuge');
  else if (type === 'reminder') navigate('profile');
}

let lastUnread = 0;
async function refreshBadges() {
  if (!state.token) return;
  try {
    const d = await api('/users/me/notifications/unread-count');
    const n = d.unread_count || 0;
    [$('#notif-badge'), $('#nav-notif-badge')].forEach(b => { b.textContent = n > 9 ? '9+' : n; b.classList.toggle('hidden', !n); });
    if (n > lastUnread && lastUnread !== -1 && current !== 'notifications') { const bell = $('#home-notif svg'); bell.style.animation = 'shakeNo .5s ease 2'; setTimeout(() => bell.style.animation = '', 1000); }
    lastUnread = n;
  } catch { }
}
let pollTimer = null, pollingOn = false;
const POLL_MS = 30000;
function startPolling() {
  stopPolling();
  pollingOn = true; lastUnread = -1;
  refreshBadges();
  if (!document.hidden) pollTimer = setInterval(refreshBadges, POLL_MS);
}
function stopPolling() { pollingOn = false; clearInterval(pollTimer); pollTimer = null; }
/* Con la pestaña oculta no se consulta nada; al volver se refresca una vez y se reanuda */
function onVisibilityChange() {
  clearInterval(pollTimer); pollTimer = null;
  if (document.hidden) return;
  if (pollingOn && state.token) { refreshBadges(); pollTimer = setInterval(refreshBadges, POLL_MS); }
  if (current === 'chat' && state.conv && !state.ws && state.token) { state.wsAttempt = 0; connectWS(state.conv.id); syncMessages(state.conv.id); }
}

/* ============================================================
   Perfil
   ============================================================ */
async function loadProfile() {
  const body = $('#profile-body');
  try { state.me = await api('/users/me'); } catch (e) { return toast(e.message, 'error'); }
  updateEmailBanner();
  const u = state.me;
  const isAdmin = ['admin', 'superadmin'].includes(u.role);
  const item = (act, icon, label, sub = '', bg = 'var(--white)') => `<div class="card p row tap" data-act="${act}" style="padding:11px 14px;background:${bg}"><div class="iconbtn sm" style="box-shadow:none">${icon}</div><div class="grow"><b>${label}</b>${sub ? `<div class="small muted">${sub}</div>` : ''}</div><b>→</b></div>`;
  const svg = id => `<svg width="18" height="18"><use href="#${id}"/></svg>`;
  body.innerHTML = `
    <div class="center pop-in"><div class="avatar" style="width:92px;height:92px;margin:0 auto;font-size:30px;border-width:3px;background:var(--teal);color:#fff">${imgTag(u.avatar_url) || esc(initials(u.full_name))}</div>
      <div class="h2 mt8">${esc(u.full_name)}</div><div class="small muted">${esc(u.email)}</div>
      <div class="chips mt8" style="justify-content:center">${u.phone ? (u.phone_verified ? '<span class="badge b-green">✓ Teléfono verificado</span>' : '<button type="button" class="badge b-yellow tap" id="pf-verify" style="cursor:pointer">Verificar teléfono</button>') : ''}${u.email_verified === true ? '<span class="badge b-green">✓ Correo verificado</span>' : u.email_verified === false ? '<button type="button" class="badge b-yellow tap" id="pf-email" style="cursor:pointer">Verificar correo</button>' : ''}${u.role === 'refuge' ? '<span class="badge b-lila">Refugio</span>' : ''}${u.role === 'foster' ? '<span class="badge b-blue">Casa de paso</span>' : ''}${isAdmin ? '<span class="badge b-orange">Admin</span>' : ''}</div></div>
    <div class="mt20"><span class="h2">Avisos</span>
      <div class="card p row tap mt12" data-act="preferences" role="button" tabindex="0" style="padding:11px 14px"><div class="iconbtn sm" style="box-shadow:none">${svg('bell')}</div><div class="grow"><b>Preferencias</b><div class="small muted">Alertas de perritos cerca ${u.notify_nearby ? '(activadas)' : '(apagadas)'}, WhatsApp, correos y cookies</div></div><b>→</b></div></div>
    <div class="mt20"><div class="between"><span class="h2">Recordatorios</span></div><div class="col mt12" id="pf-reminders">${FX.skeletonList(1)}</div></div>
    <div class="mt20"><div class="between"><span class="h2">Mi actividad</span><div class="chips" id="act-types"></div></div><div class="card p mt12"><div id="act-chart" style="height:190px"></div></div></div>
    <div class="col mt20 stagger">
      ${item('appearance', svg('palette'), 'Apariencia', 'Colores, botones, animaciones y gráficas', 'linear-gradient(135deg,var(--lila),var(--green))')}
      ${item('publish-dog', svg('dogface'), 'Dar en adopción (particular)', 'Publica gratis sin ser refugio ni casa de paso', 'var(--yellow)')}
      ${item('report-found', svg('search'), 'Reportar perrito encontrado', 'Sube foto y ubicación de un perrito en la calle', 'var(--green)')}
      ${item('matches', svg('heart'), 'Solicitudes de adopción', 'Enviadas y recibidas')}
      ${item('my-dogs', svg('paw'), 'Mis publicaciones')}
      ${item('my-reports', svg('search'), 'Mis reportes', 'Perdidos y encontrados')}
      ${shopOn() ? item('orders', svg('cart'), 'Mis pedidos') : ''}
      ${item('my-refuge', svg('home'), u.role === 'refuge' ? 'Mi refugio' : 'Registrar refugio', u.role === 'refuge' ? 'Puntos, donativos y solicitudes' : (shopOn() ? 'Publica, recibe donativos y vende' : 'Publica y recibe donativos'), 'var(--lila)')}
      ${u.role === 'refuge' && shopOn() ? item('my-shop', svg('store'), 'Mi tienda', 'Productos, pedidos, facturas y cobros', 'var(--yellow)') : ''}
      ${u.role !== 'foster' ? item('foster', svg('heart'), 'Ser casa de paso', 'Recibe perritos temporalmente', 'var(--green)') : ''}
      ${item('ranking', svg('trophy'), 'Ranking de héroes')}
      ${shopOn() ? item('shop', svg('store'), 'Tienda solidaria') : ''}
      ${item('map', svg('map'), 'Mapa de mi zona')}
      ${item('vets', svg('vet'), 'Veterinarias', 'Clínicas cerca con cédula verificada')}
      ${item('my-vet', svg('vet'), 'Mi veterinaria', '¿Tienes una clínica? Regístrala gratis', 'var(--green)')}
      ${item('help', svg('help'), 'Ayuda', 'Preguntas frecuentes, seguridad y contacto')}
      ${isAdmin ? item('admin', svg('shield'), 'Panel de administración', '', 'var(--yellow)') : ''}
      <div class="lbl mt12">Seguridad y privacidad</div>
      ${item('password', svg('shield'), 'Cambiar contraseña')}
      ${item('export', svg('send'), 'Descargar mis datos', 'Copia de tu información (derecho de acceso)')}
      ${item('my-requests', svg('edit'), 'Mis solicitudes', 'Derechos ARCO, quejas y su folio')}
      ${item('consent', svg('sparkle'), 'Preferencias de cookies', window.PatitasCookies && PatitasCookies.analyticsAllowed() ? 'Analítica activada' : 'Solo necesarias')}
      ${item('legal', svg('shield'), 'Centro legal y privacidad', 'Reglas, tus derechos, quejas y transparencia')}
      ${item('terms', svg('edit'), 'Términos y condiciones')}
      ${item('privacy', svg('shield'), 'Aviso de privacidad')}
      <button class="btn block btn-ghost mt8" id="logout-btn">${svg('logout')} Cerrar sesión</button>
      <button class="btn block btn-ghost btn-sm" id="logout-all-btn">${svg('shield')} Cerrar sesión en todos los dispositivos</button>
      <button class="link small mt8" id="delete-account-btn" style="color:var(--red)">Eliminar mi cuenta</button>
    </div>`;
  FX.decorate(body);
  const v = $('#pf-verify'); if (v) v.onclick = startPhoneVerify;
  const ev = $('#pf-email'); if (ev) ev.onclick = resendVerification;
  $('#logout-btn').onclick = () => logout();
  $('#logout-all-btn').onclick = e => logoutAll(e.currentTarget);
  $('#delete-account-btn').onclick = openDeleteAccount;
  loadReminders();
  loadActivityChart();
}
async function loadReminders() {
  const box = $('#pf-reminders');
  try {
    const rs = await api('/reminders');
    const open = rs.filter(r => !r.is_completed).slice(0, 5);
    box.innerHTML = open.length ? open.map(r => `<div class="card rem" data-rem="${r.id}"><div class="chk" role="button" aria-label="Completar"></div><div class="grow"><b class="rt">${esc(r.title)}</b><div class="small muted">${fmtDate(r.due_date)}</div></div>${parseDate(r.due_date) < new Date() ? '<span class="badge b-orange">Hoy</span>' : ''}</div>`).join('')
      : `<div class="card p small muted center">Sin pendientes. Cuando adoptes, aquí verás vacunas y seguimientos 💉</div>`;
    $$('[data-rem] .chk', box).forEach(c => c.onclick = async () => {
      const row = c.closest('[data-rem]');
      c.classList.add('on'); c.innerHTML = '<svg width="14" height="14"><use href="#check"/></svg>'; row.classList.add('done');
      FX.pawBurst(c, 4);
      try { await api(`/reminders/${row.dataset.rem}/complete`, { method: 'PATCH' }); setTimeout(() => { row.style.transition = 'opacity .3s,transform .3s'; row.style.opacity = 0; row.style.transform = 'translateX(40px)'; setTimeout(() => row.remove(), 300); }, 600); }
      catch (e) { toast(e.message, 'error'); }
    });
  } catch { box.innerHTML = ''; }
}
function loadEditProfile() {
  const u = state.me; if (!u) return;
  $('#ep-name').value = u.full_name || ''; $('#ep-phone').value = u.phone || ''; $('#ep-city').value = u.city || ''; $('#ep-country').value = u.country || 'México';
  $('#ep-avatar').innerHTML = imgTag(u.avatar_url) || esc(initials(u.full_name));
  state.newAvatar = null;
}
async function submitEditProfile(e) {
  e.preventDefault();
  await withBtn($('#edit-profile-form button[type=submit]'), async () => {
    const body = { full_name: $('#ep-name').value.trim(), phone: $('#ep-phone').value.trim() || null, city: $('#ep-city').value.trim() || null, country: $('#ep-country').value.trim() || null };
    if (state.newAvatar) body.avatar_url = (await uploadFiles([state.newAvatar]))[0];
    const phoneChanged = body.phone && body.phone !== state.me.phone;
    state.me = await api('/users/me', { method: 'PATCH', body });
    toast('Perfil actualizado', 'ok');
    if (phoneChanged) return startPhoneVerify();
    back();
  });
}

/* ============================================================
   Gráficas (PFCharts) y cambios de tema
   ============================================================ */
const liveCharts = {};
function chart(sel, opts) {
  const el = typeof sel === 'string' ? $(sel) : sel;
  if (!el) return null;
  if (!window.PFCharts) { const box = el.closest('.card'); (box && box.parentElement && box.parentElement.classList.contains('mt20') ? box.parentElement : box || el).classList.add('hidden'); return null; }
  const key = el.id || sel;
  if (liveCharts[key] && liveCharts[key].destroy) liveCharts[key].destroy();
  try { liveCharts[key] = PFCharts.render(el, { ...Theme.chartDefaults(), ...opts }); } catch (e) { console.warn('chart', e); return null; }
  return liveCharts[key];
}
function weekKey(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; }
function renderPointCharts(pts) {
  const weeks = [];
  const now = weekKey(new Date());
  for (let i = 7; i >= 0; i--) { const w = new Date(now); w.setDate(w.getDate() - i * 7); weeks.push(w); }
  const sum = weeks.map(w => pts.filter(p => +weekKey(parseDate(p.created_at)) === +w).reduce((a, p) => a + p.points, 0));
  chart('#mr-chart-points', { type: ['donut', 'radar'].includes(Theme.chartType()) ? 'area' : Theme.chartType(), labels: weeks.map(w => w.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' })), series: [{ name: 'Puntos', data: sum }], height: 200 });
  // donation y donation_refund: historial anterior (los donativos ya no suman puntos; donation_points_removed los retiró)
  const ACT = { rescue: 'Rescates', adopted_to_home: 'Adopciones', foster_home: 'Casas de paso', donation: 'Donaciones (antes)', donation_refund: 'Reembolsos de donativos (antes)', donation_points_removed: 'Ajuste: los donativos no suman puntos' };
  const by = {};
  pts.forEach(p => { const k = ACT[p.action] || 'Otros'; by[k] = (by[k] || 0) + p.points; });
  const labels = Object.keys(by);
  chart('#mr-chart-actions', { type: 'bar', labels, series: [{ name: 'Puntos', data: labels.map(l => by[l]) }], height: 170, valueLabels: true });
}
let actType = null;
async function loadActivityChart() {
  const types = [['bar', '📊'], ['line', '📈'], ['donut', '🍩'], ['radar', '🕸️']];
  actType = actType || (['bar', 'line', 'donut', 'radar'].includes(Theme.chartType()) ? Theme.chartType() : 'bar');
  if (!window.PFCharts) { const sec = $('#act-chart') && $('#act-chart').closest('.mt20'); if (sec) sec.classList.add('hidden'); return; }
  $('#act-types').innerHTML = types.map(([t, i]) => `<span class="chip ${t === actType ? 'on' : ''}" data-act-type="${t}" style="padding:4px 9px">${i}</span>`).join('');
  $$('[data-act-type]').forEach(c => c.onclick = () => { actType = c.dataset.actType; loadActivityChart(); });
  try {
    const [dogs, reports, matches, orders] = await Promise.all([api('/dogs/me'), api('/lost-reports/me').catch(() => []), api('/matches'), api('/orders').catch(() => [])]);
    const mine = matches.filter(m => m.user_id === state.me.id).length, received = matches.length - mine;
    chart('#act-chart', { type: actType, labels: ['Publicados', 'Reportes', 'Solicitudes', 'Recibidas', 'Pedidos'], series: [{ name: 'Mi actividad', data: [dogs.length, reports.length, mine, received, orders.length] }], height: 190, centerLabel: 'acciones', emptyText: 'Aún no tienes actividad 🐾' });
  } catch { }
}
function setMapTiles() {
  if (!state.map) return;
  const t = Theme.mapTiles();
  if (state.tileLayer) state.map.removeLayer(state.tileLayer);
  state.tileLayer = L.tileLayer(t.url, { maxZoom: 19, attribution: t.attr, subdomains: t.url.includes('cartocdn') ? 'abcd' : 'abc' }).addTo(state.map);
}
function onThemeChange() {
  setMapTiles();
  if (current === 'home') { $('#home-dog').innerHTML = FX.dogFace(92); }
}

/* ============================================================
   Cuenta: contraseña, exportar, eliminar
   ============================================================ */
function openPassword() {
  $('#password-form').reset();
  $('#pw-current-wrap').classList.toggle('hidden', state.me && state.me.has_password === false);
  $('#password-modal').classList.add('open');
  FX.decorate($('#password-modal'));
}
async function submitPassword(e) {
  e.preventDefault();
  const current_password = $('#pw-current').value, new_password = $('#pw-new').value;
  if (new_password.length < 8) return toast('La nueva contraseña debe tener al menos 8 caracteres', 'error');
  if (new_password !== $('#pw-new2').value) return toast('Las contraseñas no coinciden', 'error');
  await withBtn($('#password-form button[type=submit]'), async () => {
    const r = await api('/users/me/password', { method: 'POST', body: { current_password: current_password || null, new_password }, noLogout: true });
    if (r && r.access_token) { state.token = r.access_token; localStorage.setItem('patitas_token', r.access_token); }
    $('#password-modal').classList.remove('open');
    toast('Contraseña actualizada 🔒 Cerramos tus otras sesiones', 'ok');
  });
}
async function exportMyData() {
  FX.showLoading('Preparando tus datos...', ['Juntando publicaciones, mensajes y pedidos'], 'sniff');
  try {
    const res = await fetch('/users/me/export', { headers: { Authorization: `Bearer ${state.token}` } });
    if (res.status === 401) { sessionExpired(); return; }
    if (res.status === 429) throw new Error('Ya descargaste tus datos hace poco. Inténtalo más tarde');
    if (!res.ok) throw new Error('No pudimos generar tu archivo');
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `guauwoow-mis-datos-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    toast('Descarga lista 📦', 'ok');
  } catch (e) { toast(e.message, 'error'); }
  finally { FX.hideLoading(); }
}
function openDeleteAccount() {
  $('#delete-form').reset();
  $('#delete-art').innerHTML = FX.sleepDog();
  $('#del-pass-wrap').classList.toggle('hidden', state.me && state.me.has_password === false);
  $('#delete-modal').classList.add('open');
  FX.decorate($('#delete-modal'));
}
async function submitDelete(e) {
  e.preventDefault();
  if ($('#del-confirm').value.trim().toUpperCase() !== 'ELIMINAR') return toast('Escribe ELIMINAR para confirmar', 'error');
  await withBtn($('#delete-form button[type=submit]'), async () => {
    await api('/users/me', { method: 'DELETE', body: { password: $('#del-pass').value || null, confirm: 'ELIMINAR' }, noLogout: true });
    track('account_deleted');
    $('#delete-modal').classList.remove('open');
    localStorage.removeItem('patitas_cart');
    toast('Tu cuenta fue eliminada. Gracias por ayudar a los perritos 💚', 'ok');
    logout(true);
  });
}

/* ============================================================
   Ayuda (FAQ y contacto) y reportes de contenido (moderación)
   ============================================================ */
function supportLinks() {
  const c = state.config;
  const wa = String(c.support_whatsapp || '').replace(/\D/g, '');
  const mail = /^[^\s@<>"']+@[^\s@<>"']+\.[^\s@<>"']+$/.test(c.support_email || '') ? c.support_email : '';
  return { mail, wa };
}
function loadHelp() {
  if (!$('#help-art').innerHTML) $('#help-art').innerHTML = FX.dogFace(96);
  const { mail, wa } = supportLinks();
  $('#help-contact').classList.toggle('hidden', !mail && !wa);
  const em = $('#help-email'), w = $('#help-whatsapp');
  em.classList.toggle('hidden', !mail);
  if (mail) em.href = `mailto:${mail}?subject=${encodeURIComponent('Ayuda con GuauWoow')}`;
  w.classList.toggle('hidden', !wa);
  if (wa) w.href = `https://wa.me/${wa}?text=${encodeURIComponent('Hola, necesito ayuda con GuauWoow')}`;
  $('#help-contact-text').textContent = mail ? `Nuestro correo: ${mail}` : '';
}
function reportProblem() {
  const { mail, wa } = supportLinks();
  if (mail) location.href = `mailto:${mail}?subject=${encodeURIComponent('Problema en GuauWoow')}&body=${encodeURIComponent('Cuéntanos qué pasó, en qué pantalla y desde qué celular:\n\n')}`;
  else if (wa) window.open(`https://wa.me/${wa}?text=${encodeURIComponent('Hola, encontré un problema en GuauWoow: ')}`, '_blank', 'noopener');
  else toast('Para reportar una publicación o a un usuario usa el botón 🚩 en su perfil o en el chat', 'info');
}

const FLAG_TARGET = { dog: 'esta publicación', lost_report: 'este reporte', refuge: 'este refugio', product: 'este producto', user: 'esta persona', message: 'este mensaje' };
let flagTarget = null;
function openFlag(type, id, name = '') {
  if (!state.me) return toast('Inicia sesión para reportar', 'error');
  flagTarget = { type, id: +id };
  $('#flag-title').textContent = type === 'user' ? 'Reportar usuario' : 'Reportar';
  $('#flag-sub').textContent = `¿Qué pasa con ${FLAG_TARGET[type] || 'esto'}${name ? ` («${name}»)` : ''}? Tu reporte es confidencial.`;
  $('#flag-form').reset();
  $$('#flag-reasons .chip').forEach(c => { c.classList.remove('on'); c.setAttribute('aria-checked', 'false'); });
  // Motivos propios de un tipo (p. ej. clínicas y reseñas): data-for="veterinary veterinary_review"
  $$('#flag-reasons .chip[data-for]').forEach(c => c.classList.toggle('hidden', !c.dataset.for.split(' ').includes(type)));
  $('#flag-modal').classList.add('open');
  FX.decorate($('#flag-modal'));
}
async function submitFlag(e) {
  e.preventDefault();
  const on = $('#flag-reasons .chip.on');
  if (!on) return toast('Elige un motivo', 'error');
  if (!flagTarget) return;
  const details = $('#flag-details').value.trim();
  await withBtn($('#flag-submit'), async () => {
    try {
      await api('/reports', { method: 'POST', body: { target_type: flagTarget.type, target_id: flagTarget.id, reason: on.dataset.v, details: details || null } });
    } catch (err) {
      // Servidor sin moderación todavía: se ofrece el correo de soporte en lugar de fallar en silencio
      if (err.status !== 404 || err.message !== 'Not Found') throw err;
      $('#flag-modal').classList.remove('open');
      const { mail } = supportLinks();
      return toast(mail ? `Escríbenos a ${mail} para reportarlo` : 'No pudimos enviar el reporte. Inténtalo más tarde', 'error');
    }
    $('#flag-modal').classList.remove('open');
    track('content_reported', { type: flagTarget.type, reason: on.dataset.v });
    // Lo que involucra a menores se oculta al recibirlo (moderacion.html §4)
    const minor = ['involucra_menor', 'abuso_sexual_infantil'].includes(on.dataset.v);
    toast(minor ? 'Gracias. Lo ocultamos y lo revisamos con prioridad 🛡️' : '¡Gracias! Nuestro equipo lo revisará 🛡️', 'ok');
  });
}

/* ============================================================
   Analítica (PostHog con consentimiento) y monitoreo (Sentry)
   ============================================================ */
function loadScript(src) {
  return new Promise((ok, fail) => { const s = document.createElement('script'); s.src = src; s.async = true; s.crossOrigin = 'anonymous'; s.onload = ok; s.onerror = fail; document.head.appendChild(s); });
}
async function initAnalytics() {
  const c = state.config;
  if (c.sentry_dsn_frontend && !window.Sentry) {
    try {
      await loadScript('/app/vendor/sentry/bundle.min.js');  // @sentry/browser 8.55.0 autohospedado
      Sentry.init({ dsn: c.sentry_dsn_frontend, environment: c.environment, tracesSampleRate: 0.1, sendDefaultPii: false,
        beforeSend(ev) { if (ev.request && ev.request.url) ev.request.url = scrubUrl(ev.request.url); return ev; } });
    } catch { }
  }
  // PostHog solo se carga si se aceptó la analítica en el aviso de cookies; si se retira, se detiene
  if (window.PatitasCookies) {
    if (c.posthog_key && PatitasCookies.analyticsAllowed()) startPosthog();
    PatitasCookies.onChange(s => {
      if (s.analytics) startPosthog();
      toast(s.analytics ? '¡Gracias! Nos ayudas a mejorar 💜' : 'Listo, solo usaremos lo necesario', 'ok');
      if (current === 'profile') loadProfile();
    });
  }
}
function showCookieBanner() {
  if (window.PatitasCookies) PatitasCookies.open();
}
async function startPosthog() {
  const c = state.config;
  if (!c.posthog_key || window.posthog) { try { window.posthog && posthog.opt_in_capturing(); } catch { } return; }
  try {
    const assets = c.posthog_host.replace('.i.posthog.com', '-assets.i.posthog.com');
    await loadScript(`${assets}/static/array.js`);
    posthog.init(c.posthog_key, {
      api_host: c.posthog_host, person_profiles: 'identified_only', autocapture: true, capture_pageview: false, persistence: 'localStorage',
      // Nunca se manda a PostHog lo que escribe la gente ni el texto en pantalla (nombres, mensajes, direcciones)
      mask_all_text: true, mask_all_element_attributes: true, disable_session_recording: true,
      session_recording: { maskAllInputs: true, maskTextSelector: '*' },
      sanitize_properties: props => { ['$current_url', '$referrer'].forEach(k => { if (props[k]) props[k] = scrubUrl(props[k]); }); return props; },
    });
    identify();
  } catch { }
}
/* Quita de las URLs los tokens de sesión, verificación y recuperación antes de enviarlas a terceros */
function scrubUrl(u) { return String(u).replace(/([?#&](token|verify_email|reset)=)[^&#]+/g, '$1[filtrado]'); }
function identify() {
  try { if (window.posthog && posthog.__loaded && state.me) posthog.identify(String(state.me.id), { role: state.me.role, city: state.me.city }); } catch { }
  try { if (window.Sentry && state.me) Sentry.setUser({ id: String(state.me.id) }); } catch { }
}
function track(event, props = {}) {
  try { if (window.posthog && posthog.__loaded) posthog.capture(event, props); } catch { }
}

/* ============================================================
   Deep links y pagos
   ============================================================ */
async function handleDeepLinks() {
  const p = new URLSearchParams(location.search);
  const clean = () => history.replaceState({}, '', location.pathname);
  if (state.openHelp) { state.openHelp = false; navigate('help'); }
  else if (p.get('dog')) { clean(); openDog(p.get('dog')); }
  else if (p.get('report')) { clean(); openReport(p.get('report')); }
  else if (/^\d+$/.test(p.get('vet') || '') && window.VET) { clean(); VET.open(p.get('vet')); }
  // Publicación compartida por un voluntario: ?share=1&url=&text= (botón) o ?title=&text=&url= (share_target de Android)
  else if (p.has('share') || p.has('url') || p.has('text') || p.has('title')) { clean(); if (window.Compartir) Compartir.openFromParams(p); }
  else if (p.get('payment')) {
    const status = p.get('payment'), order = p.get('order'), donation = p.get('donation');
    clean();
    if (status === 'failure') return toast('El pago no se completó. Puedes intentarlo de nuevo', 'error');
    FX.showLoading('Confirmando tu pago...', ['Esto tarda unos segundos'], 'chase');
    let st = 'pending';
    for (let i = 0; i < 8 && st !== 'paid' && st !== 'approved'; i++) {
      try { st = (await api(`/payments/status?${order ? 'order=' + order : 'donation=' + donation}`)).status; } catch { }
      if (st !== 'paid' && st !== 'approved') await sleep(1500);
    }
    FX.hideLoading();
    if (st === 'paid' || st === 'approved') await FX.success('¡Pago recibido!', order ? 'El refugio ya prepara tu pedido 📦' : 'Gracias por tu donación 💚', 2200);
    else toast('Tu pago está en proceso. Te avisaremos cuando se confirme', 'info');
    if (order && window.Tienda) Tienda.openOrder(+order);
  }
  // Enlace de un aviso o correo de la tienda: /app/?order=N (comprador o refugio que vende)
  else if (/^\d+$/.test(p.get('order') || '') && window.Tienda) { const receipt = p.get('receipt') === '1'; clean(); Tienda.openOrder(+p.get('order'), { fallbackShop: true, receipt }); }
  // Avisos y correos para el refugio que vende: /app/?shop=pedidos (abre "Mi tienda" en esa pestaña)
  else if (/^(productos|pedidos|facturas|fiscal|cobros|cuenta)$/.test(p.get('shop') || '') && window.Tienda && state.me) { clean(); Tienda.openMyShop(p.get('shop')); }
  // Regreso de conectar Mercado Pago (refugio vendedor): /app/#mp=connected|error
  else if (state.mpReturn) { const mp = state.mpReturn; state.mpReturn = null; if (window.Tienda) Tienda.onMpReturn(mp); }
}

/* ============================================================
   Eventos
   ============================================================ */
function bindEvents() {
  $$('.nav-back').forEach(b => b.addEventListener('click', back));
  $$('#nav .nav-item').forEach(i => i.addEventListener('click', () => navigate(i.dataset.go, { reset: i.dataset.go === 'home' })));
  $('#nav-fab').addEventListener('click', () => { $('#publish-menu').classList.add('open'); });
  $$('.modal').forEach(m => m.addEventListener('click', e => { if (e.target === m) m.classList.remove('open'); }));
  $$('[data-pub]').forEach(c => c.addEventListener('click', () => {
    $('#publish-menu').classList.remove('open');
    const k = c.dataset.pub;
    if (k === 'adopt') openPublish(); else if (k === 'photo') openPhotoSearch(); else openReportForm(k);
  }));

  // Delegación: abrir perros, reportes, refugios y acciones de estados vacíos
  device.addEventListener('click', e => {
    const t = e.target.closest('[data-dog],[data-report],[data-refuge],[data-conv],[data-empty-action],[data-notif],[data-act],[data-city],[data-product]');
    if (!t || t.closest('#publish-menu')) return;
    if (t.matches('a')) e.preventDefault();
    const inModal = t.closest('#product-detail');
    if (inModal && !t.dataset.product) inModal.classList.remove('open');
    if (t.dataset.product) openProduct(t.dataset.product);
    else if (t.dataset.dog) openDog(t.dataset.dog);
    else if (t.dataset.report) openReport(t.dataset.report);
    else if (t.dataset.refuge) openRefuge(t.dataset.refuge);
    else if (t.dataset.conv) openChat(t.dataset.conv);
    else if (t.dataset.notif) { let d = {}; try { d = JSON.parse(t.dataset.ndata || '{}'); } catch { } notifAction(t.dataset.notif, d); }
    else if (t.dataset.city) { const c = CITIES[+t.dataset.city]; saveLocation({ lat: c[1], lon: c[2] }, c[0]); }
    else if (t.dataset.act) ({
      'publish-dog': () => openPublish(), 'report-found': () => openReportForm('found'),
      matches: openMyMatches, 'my-dogs': openMyDogs, 'my-reports': openMyReports, orders: openMyOrders, 'my-refuge': () => navigate('my-refuge'),
      foster: () => { $('#foster-art').innerHTML = FX.dogFace(100, { fur: '#86E0D4' }); $('#fh-city').value = state.me.city || ''; navigate('foster-register'); },
      ranking: () => navigate('ranking'), shop: () => navigate('shop'), map: () => navigate('map'), admin: () => { location.href = '/admin/'; },
      appearance: () => navigate('appearance'), password: openPassword, export: exportMyData, consent: () => showCookieBanner(true), preferences: () => navigate('preferences'),
      terms: () => window.open('/app/legal/terminos.html', '_blank'), privacy: () => window.open('/app/legal/privacidad.html', '_blank'),
      'my-requests': () => window.open('/app/legal/derechos-arco.html#mis-solicitudes', '_blank'),
      legal: () => window.open('/app/legal/centro-legal.html', '_blank'),
      help: () => navigate('help'),
    }[t.dataset.act] || (() => {}))();
    else if (t.dataset.emptyAction) ({
      'reload-discover': loadDiscover, 'go-discover': () => navigate('discover'), publish: openPublish, shop: () => navigate('shop'),
      'refuge-register': () => { $('#rg-city').value = state.me.city || ''; renderDocDrop(); navigate('refuge-register'); },
    }[t.dataset.emptyAction] || (() => {}))();
  });

  // Teclado: Escape cierra el modal abierto; Enter/Espacio activan tarjetas con rol de botón
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const m = $$('.modal.open').filter(x => x.id !== 'terms-modal').pop();
      if (m) { if (m.id === 'match-modal') closeMatchModal(); else m.classList.remove('open'); }
      return;
    }
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[role=button]:not(button)')) { e.preventDefault(); e.target.click(); }
  });
  document.addEventListener('visibilitychange', onVisibilityChange);

  // Ayuda, correo y reportes de contenido
  $('#auth-help').addEventListener('click', () => navigate('help'));
  $('#help-problem').addEventListener('click', reportProblem);
  $('#email-resend').addEventListener('click', resendVerification);
  $('#email-banner-close').addEventListener('click', snoozeEmailBanner);
  $('#flag-form').addEventListener('submit', submitFlag);
  $('#flag-close').addEventListener('click', () => $('#flag-modal').classList.remove('open'));
  $$('#flag-reasons .chip').forEach(c => c.addEventListener('click', () => {
    $$('#flag-reasons .chip').forEach(x => { x.classList.toggle('on', x === c); x.setAttribute('aria-checked', String(x === c)); });
  }));
  $('#dog-flag').addEventListener('click', () => state.dog && openFlag('dog', state.dog.id, state.dog.name));
  $('#report-flag').addEventListener('click', () => state.report && openFlag('lost_report', state.report.id, state.report.dog_name));
  $('#refuge-flag').addEventListener('click', () => state.refuge && openFlag('refuge', state.refuge.id, state.refuge.name));
  $('#chat-flag').addEventListener('click', () => state.conv && state.conv.other_user && openFlag('user', state.conv.other_user.id, state.conv.other_user.full_name));
  $('#chat-messages').addEventListener('click', e => { const b = e.target.closest('[data-flag-msg]'); if (b) openFlag('message', b.dataset.flagMsg); });
  $('#pd-flag').addEventListener('click', () => { if (!state.product) return; $('#product-detail').classList.remove('open'); openFlag('product', state.product.id, state.product.name); });
  $('#pd-close').addEventListener('click', () => $('#product-detail').classList.remove('open'));
  $('#rg-docs-file').addEventListener('change', e => { addDocs(e.target.files); e.target.value = ''; });
  renderDocDrop();

  // Splash / onboarding / auth
  $('#ob-next').addEventListener('click', () => obGo(obIdx + 1));
  $('#ob-skip').addEventListener('click', () => obGo(3));
  $('#auth-form').addEventListener('submit', submitAuth);
  $('#auth-toggle').addEventListener('click', () => setAuthMode(state.authMode === 'register' ? 'login' : 'register'));
  $('#auth-forgot-link').addEventListener('click', () => setAuthMode('forgot'));
  $('#auth-back').addEventListener('click', () => setAuthMode('login'));
  $('#demo-login').addEventListener('click', demoLogin);
  $('#google-login').addEventListener('click', () => { FX.showLoading('Conectando con Google...', [], 'chase'); location.href = '/auth/google/login'; });
  $('#verify-submit').addEventListener('click', verifyCode);
  $('#verify-resend').addEventListener('click', sendCode);
  $('#verify-skip').addEventListener('click', enterApp);
  $('#verify-change').addEventListener('click', () => showPhoneEdit(true));
  $('#verify-phone-save').addEventListener('click', savePhoneAndSend);
  $('#verify-phone-input').addEventListener('keydown', e => { if (e.key === 'Enter') savePhoneAndSend(); });
  $('#verify-logout').addEventListener('click', () => logout());
  $('#password-form').addEventListener('submit', submitPassword);
  $('#delete-form').addEventListener('submit', submitDelete);
  $('#delete-cancel').addEventListener('click', () => $('#delete-modal').classList.remove('open'));
  $('#tm-accept').addEventListener('click', e => {
    if (!$('#tm-terms').checked) return toast('Marca la casilla para continuar', 'error');
    withBtn(e.currentTarget, async () => {
      const age = window.Cumplimiento ? Cumplimiento.termsPayload(state.me) : {};
      state.me = await api('/users/me/terms', { method: 'POST', body: { accepted_terms: true, marketing_opt_in: $('#tm-marketing').checked, ...age }, noVerifyRedirect: true });
      $('#terms-modal').classList.remove('open');
      afterLogin();
    });
  });
  $('#tm-logout').addEventListener('click', () => { $('#terms-modal').classList.remove('open'); logout(); });
  $$('.code-box').forEach((b, i, all) => {
    b.addEventListener('input', () => { b.value = b.value.replace(/\D/g, '').slice(0, 1); if (b.value && all[i + 1]) all[i + 1].focus(); if (b.value && i === all.length - 1) verifyCode(); });
    b.addEventListener('keydown', e => { if (e.key === 'Backspace' && !b.value && all[i - 1]) all[i - 1].focus(); });
    b.addEventListener('paste', e => { const t = (e.clipboardData.getData('text') || '').replace(/\D/g, ''); if (t) { e.preventDefault(); [...t].slice(0, all.length).forEach((c, j) => { all[j].value = c; }); } });
  });

  // Home
  $('#home-loc').addEventListener('click', openLocation);
  $('#loc-gps').addEventListener('click', e => withBtn(e.currentTarget, async () => {
    const c = await getPosition();
    const g = await reverseGeocode(c);
    await saveLocation(c, g ? (g.city || g.area || 'Mi ubicación') : 'Mi ubicación');
  }));
  $('#home-notif').addEventListener('click', () => navigate('notifications'));
  $('#home-theme').addEventListener('click', () => navigate('appearance'));
  $('#home-photo').addEventListener('click', openPhotoSearch);
  $('#home-photo-btn').addEventListener('click', openPhotoSearch);
  $('#home-lost-btn').addEventListener('click', () => openReportForm('lost'));
  const hFound = $('#home-found-btn'); if (hFound) hFound.addEventListener('click', () => openReportForm('found'));
  const hAdopt = $('#home-adopt-btn'); if (hAdopt) hAdopt.addEventListener('click', () => openPublish());
  const hResFound = $('#home-rescue-found'); if (hResFound) hResFound.addEventListener('click', () => openReportForm('found'));
  const hResAdopt = $('#home-rescue-adopt'); if (hResAdopt) hResAdopt.addEventListener('click', () => openPublish());
  $('#home-see-all').addEventListener('click', openAdoptList);
  $('#home-map').addEventListener('click', () => navigate('map'));
  $('#home-shop').addEventListener('click', () => navigate('shop'));
  $$('.cat').forEach(c => c.addEventListener('click', () => {
    const k = c.dataset.cat;
    if (k === 'adopt') navigate('discover'); else if (k === 'refuges') openRefugesList(); else openReportsList(k);
  }));

  // Discover
  $$('#discover-sizes .chip').forEach(c => c.addEventListener('click', () => {
    $$('#discover-sizes .chip').forEach(x => x.classList.remove('on')); c.classList.add('on');
    state.deckSize = c.dataset.size; loadDiscover();
  }));
  $('#discover-filter').addEventListener('click', openLocation);
  $('#match-questionnaire').addEventListener('click', () => { closeMatchModal(); openQuestionnaire(); });
  $('#match-close').addEventListener('click', closeMatchModal);

  // Perro / cuestionario
  $('#dog-adopt').addEventListener('click', adoptCurrentDog);
  $('#dog-share').addEventListener('click', () => state.dog && share(`🐶 ${state.dog.name} busca hogar en GuauWoow`, `/app/?dog=${state.dog.id}`));
  $$('#questionnaire-form [data-q] .chip, [data-single] .chip').forEach(c => c.addEventListener('click', () => {
    $$('.chip', c.parentElement).forEach(x => x.classList.remove('on')); c.classList.add('on');
  }));
  $('#questionnaire-form').addEventListener('submit', submitQuestionnaire);

  // Foto IA
  $('#ps-shoot').addEventListener('click', () => $('#ps-file').click());
  $('#ps-gallery-btn').addEventListener('click', () => $('#ps-gallery').click());
  $('#ps-reset').addEventListener('click', openPhotoSearch);
  $('#ps-file').addEventListener('change', e => { setPsFile(e.target.files[0]); e.target.value = ''; });
  $('#ps-gallery').addEventListener('change', e => { setPsFile(e.target.files[0]); e.target.value = ''; });
  $('#ps-go').addEventListener('click', runPhotoSearch);
  $$('#ps-type button').forEach(b => b.addEventListener('click', () => { $$('#ps-type button').forEach(x => x.classList.remove('on')); b.classList.add('on'); state.psType = b.dataset.v; }));

  // Formularios
  photoHooks.pub = f => aiAutofill(f, 'pub');
  photoHooks.rf = f => aiAutofill(f, 'rf');
  $('#publish-form').addEventListener('submit', submitPublish);
  $('#pub-found').addEventListener('change', e => $('#pub-found-wrap').classList.toggle('hidden', !e.target.checked));
  $('#report-form').addEventListener('submit', submitReport);
  $$('#rf-type button').forEach(b => b.addEventListener('click', () => setReportType(b.dataset.v)));
  $('#refuge-form').addEventListener('submit', submitRefuge);
  $('#foster-form').addEventListener('submit', submitFoster);
  $('#edit-profile-form').addEventListener('submit', submitEditProfile);
  $('#profile-edit').addEventListener('click', () => navigate('edit-profile'));
  const pickAvatar = () => $('#ep-avatar-file').click();
  $('#ep-avatar').addEventListener('click', pickAvatar);
  $('#ep-avatar-btn').addEventListener('click', pickAvatar);
  $('#ep-avatar-file').addEventListener('change', e => { const f = e.target.files[0]; if (!f) return; state.newAvatar = f; $('#ep-avatar').innerHTML = `<img src="${URL.createObjectURL(f)}" alt="">`; });

  // Chat
  $('#chat-form').addEventListener('submit', sendChat);
  $('#chat-input').addEventListener('input', () => {
    if (state.ws && state.ws.readyState === 1 && Date.now() - state.lastTypingSent > 2000) { state.lastTypingSent = Date.now(); state.ws.send(JSON.stringify({ type: 'typing' })); }
  });
  $('#chat-open-ref').addEventListener('click', () => state.conv && state.conv.lost_report_id && openReport(state.conv.lost_report_id));

  // Notificaciones, ranking, tienda, mapa
  $('#notif-read-all').addEventListener('click', async () => { try { await api('/notifications/read-all', { method: 'PATCH' }); refreshBadges(); loadNotifications(); } catch (e) { toast(e.message, 'error'); } });
  $('#ranking-filter-btn').addEventListener('click', loadRanking);
  // Carrito, checkout y "Mi tienda": los eventos los conecta tienda.js
  $('#map-locate').addEventListener('click', e => withBtn(e.currentTarget, async () => { const c = await getPosition(); setCoords(c); loadMap(); }));
  $$('#map-filters .chip').forEach(c => c.addEventListener('click', () => {
    c.classList.toggle('on');
    const layer = state.mapLayers[c.dataset.k];
    if (layer && state.map) c.classList.contains('on') ? layer.addTo(state.map) : state.map.removeLayer(layer);
  }));

  // Volver con botón físico de Android / navegador
  window.addEventListener('popstate', () => { if (current !== 'home' && current !== 'auth') { history.pushState({}, ''); back(); } });
}

/* ============================================================
   Arranque
   ============================================================ */
async function init() {
  // Miniaturas: si una no existe se usa la imagen completa (capturing: "error" no burbujea)
  document.addEventListener('error', e => {
    const img = e.target;
    if (img instanceof HTMLImageElement && img.dataset.full && img.getAttribute('src') !== img.dataset.full) img.src = img.dataset.full;
  }, true);
  FX.init(device);
  Theme.initInteractions(device);
  document.addEventListener('themechange', onThemeChange);
  initPhotoDrops();
  initLocPickers();
  bindEvents();
  FX.decorate(device);

  // Token de Google en el fragmento (#token=...; ?token= se acepta por compatibilidad), enlace de
  // verificación de correo (#verify_email=...) y #ayuda. Se quitan de la URL antes de cualquier otra cosa.
  const params = new URLSearchParams(location.search);
  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  const tk = hash.get('token') || params.get('token');
  if (tk) { state.token = tk; localStorage.setItem('patitas_token', tk); }
  const verifyEmail = hash.get('verify_email');
  state.mpReturn = /^(connected|error)$/.test(hash.get('mp') || '') ? hash.get('mp') : null;  // OAuth de Mercado Pago (tienda.js)
  state.openHelp = /^#(ayuda|help)$/.test(location.hash);
  const authError = params.get('auth_error');  // se lee antes de borrarlo de params (el toast sale después del splash)
  if (authError) setTimeout(() => toast('No pudimos entrar con Google: ' + authError, 'error'), 2200);
  if (params.get('reset')) state.resetToken = params.get('reset');
  ['token', 'auth_error', 'reset'].forEach(k => params.delete(k));
  history.replaceState({}, '', location.pathname + (params.toString() ? '?' + params : ''));
  history.pushState({}, '', location.href);
  const finishSplash = runSplash();
  const minSplash = sleep(1700);

  try { state.config = { ...state.config, ...(await api('/auth/config', { noLogout: true })) }; } catch { }
  applyConfig();
  let logged = false;
  if (state.token) {
    try { await setToken(state.token); logged = true; } catch { state.token = ''; localStorage.removeItem('patitas_token'); }
  }
  await minSplash;
  finishSplash();
  await sleep(300);

  if (state.resetToken) return showAuth('reset');
  initAnalytics();
  if (verifyEmail) verifyEmailToken(verifyEmail);
  if (logged) return afterLogin();
  if (!localStorage.getItem('patitas_onboarded') && !state.openHelp) return showOnboarding();
  showAuth('login');
  if (state.openHelp) { state.openHelp = false; navigate('help'); }
}

init();
