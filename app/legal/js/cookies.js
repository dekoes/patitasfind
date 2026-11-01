/* ============================================================
   GuauWoow — Aviso y preferencias de cookies (L-pref, cookies.html §3 y §8)
   Se carga en la página de inicio, en la app (/app/) y en las páginas legales.

   - «Necesarias»: siempre activas (sesión, carrito, tu elección y seguridad).
   - «Analítica» (PostHog): apagada hasta que la aceptes. Mientras no la aceptes, el código de PostHog no se carga.
   - La elección se guarda en el navegador (clave patitas_consent) con la versión de la política y la fecha, y se
     vuelve a preguntar a los 12 meses o si la política cambia. Si hay sesión iniciada, también se manda la
     constancia a POST /cumplimiento/preferencias/cookies {analytics}.
   - Al retirar el permiso se detiene PostHog y se borran sus claves ph_… del navegador.
   - Cualquier enlace con [data-cookie-prefs] abre el panel. API: window.PatitasCookies
     { get(), analyticsAllowed(), open(), set(analytics), onChange(fn) } y el evento «patitas:consent».
   Sin manejadores en línea (CSP) y sin dependencias.
   ============================================================ */
(function () {
  'use strict';
  if (window.PatitasCookies) return;

  var KEY = 'patitas_consent';
  var POLICY_VERSION = '2026-10-17';   // versión de cookies.html: si cambia, se vuelve a preguntar
  var MAX_AGE_MS = 365 * 24 * 60 * 60 * 1000;  // 12 meses
  var listeners = [];
  var banner = null;

  function read() {
    var raw = null;
    try { raw = localStorage.getItem(KEY); } catch (e) { return null; }
    if (!raw) return null;
    var data = null;
    try { data = JSON.parse(raw); } catch (e) { data = null; }
    // Elecciones anteriores ("all" / "essential") no tienen fecha ni versión: se vuelve a preguntar
    if (!data || typeof data !== 'object' || data.v !== POLICY_VERSION || !data.at) return null;
    var at = Date.parse(data.at);
    if (!at || Date.now() - at > MAX_AGE_MS) return null;
    return { analytics: data.analytics === true, at: data.at, v: data.v };
  }

  function clearAnalyticsStorage() {
    try {
      var keys = [];
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && (k.indexOf('ph_') === 0 || k.indexOf('__ph_') === 0)) keys.push(k);
      }
      keys.forEach(function (k) { localStorage.removeItem(k); });
    } catch (e) { /* sin acceso al almacenamiento */ }
    try {
      document.cookie.split(';').forEach(function (c) {
        var name = c.split('=')[0].trim();
        if (name.indexOf('ph_') === 0) document.cookie = name + '=; Max-Age=0; path=/';
      });
    } catch (e) { /* nada */ }
  }

  function token() {
    try { return localStorage.getItem('patitas_token') || ''; } catch (e) { return ''; }
  }

  function sendRecord(analytics) {
    var tk = token();
    if (!tk || !window.fetch) return;
    try {
      fetch('/cumplimiento/preferencias/cookies', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tk },
        body: JSON.stringify({ analytics: !!analytics }), keepalive: true,
      }).catch(function () { /* la elección ya quedó en el navegador */ });
    } catch (e) { /* nada */ }
  }

  function set(analytics) {
    var state = { v: POLICY_VERSION, analytics: !!analytics, at: new Date().toISOString() };
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* modo privado: solo esta visita */ }
    if (!analytics) {
      try { if (window.posthog && window.posthog.opt_out_capturing) window.posthog.opt_out_capturing(); } catch (e) { /* nada */ }
      clearAnalyticsStorage();
    }
    sendRecord(analytics);
    hide();
    var detail = { analytics: !!analytics, at: state.at, v: state.v };
    listeners.slice().forEach(function (fn) { try { fn(detail); } catch (e) { /* nada */ } });
    try { document.dispatchEvent(new CustomEvent('patitas:consent', { detail: detail })); } catch (e) { /* nada */ }
    return detail;
  }

  var CSS = [
    '#cookie-banner.pfc{font-family:inherit;color:var(--ink,#1D2233);background:var(--sheet-bg,#fff);',
    'border:2px solid var(--line,#1D2233);border-radius:20px;box-shadow:0 6px 0 var(--line,#1D2233);padding:14px;z-index:9000}',
    '#cookie-banner.pfc-fixed{position:fixed;left:16px;right:16px;bottom:16px;max-width:520px;margin:0 auto}',
    '#cookie-banner .pfc-title{margin:0 0 6px;font-size:17px;font-weight:800;line-height:1.25}',
    '#cookie-banner .pfc-text{margin:0;font-size:14px;line-height:1.45;font-weight:600}',
    '#cookie-banner .pfc-text a{color:var(--purple,#5E3BA6);font-weight:800}',
    '#cookie-banner .pfc-cats{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:8px}',
    '#cookie-banner .pfc-cat{display:flex;align-items:center;gap:10px;border:1.5px solid var(--line,#1D2233);border-radius:14px;padding:8px 10px}',
    '#cookie-banner .pfc-cat b{display:block;font-size:14px}',
    '#cookie-banner .pfc-cat small{display:block;font-size:12.5px;line-height:1.3;opacity:.8}',
    '#cookie-banner .pfc-cat .pfc-grow{flex:1;min-width:0}',
    '#cookie-banner .pfc-pill{font-size:12px;font-weight:800;border:1.5px solid var(--line,#1D2233);border-radius:999px;padding:1px 8px;white-space:nowrap}',
    '#cookie-banner input[type=checkbox]{width:22px;height:22px;flex-shrink:0;accent-color:var(--purple,#5E3BA6)}',
    '#cookie-banner .pfc-actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}',
    '#cookie-banner .pfc-btn{flex:1 1 140px;min-height:44px;border:2px solid var(--line,#1D2233);border-radius:999px;',
    'background:var(--white,#fff);color:inherit;font:inherit;font-weight:800;font-size:14px;cursor:pointer;padding:8px 12px}',
    '#cookie-banner .pfc-btn:focus-visible,#cookie-banner .pfc-close:focus-visible{outline:3px solid var(--purple,#5E3BA6);outline-offset:2px}',
    '#cookie-banner .pfc-head{display:flex;align-items:flex-start;gap:8px}',
    '#cookie-banner .pfc-head .pfc-grow{flex:1}',
    '#cookie-banner .pfc-close{border:0;background:none;font-size:22px;line-height:1;cursor:pointer;color:inherit;padding:2px 6px}',
    '#cookie-banner .pfc-current{margin:8px 0 0;font-size:12.5px;font-weight:700;opacity:.8}',
    '@media print{#cookie-banner{display:none!important}}',
  ].join('');

  function injectStyle() {
    if (document.getElementById('pfc-style')) return;
    var st = document.createElement('style');
    st.id = 'pfc-style';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function hide() {
    if (banner) { banner.remove(); banner = null; }
  }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }

  function fmt(iso) {
    try { return new Date(iso).toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' }); }
    catch (e) { return ''; }
  }

  /* manage=true: se abrió desde «Preferencias de cookies» (muestra la elección actual y se puede cerrar) */
  function show(manage) {
    injectStyle();
    hide();
    var current = read();
    var device = document.getElementById('device');
    banner = el('div', { id: 'cookie-banner', class: 'pfc' + (device ? '' : ' pfc-fixed'), role: 'dialog',
      'aria-labelledby': 'pfc-title', 'aria-describedby': 'pfc-text' });
    var head = el('div', { class: 'pfc-head' });
    var headText = el('div', { class: 'pfc-grow' });
    headText.appendChild(el('p', { class: 'pfc-title', id: 'pfc-title' }, '🍪 Cookies y tu privacidad'));
    var p = el('p', { class: 'pfc-text', id: 'pfc-text' },
      'Usamos lo necesario para que GuauWoow funcione. Con tu permiso, también medimos qué pantallas se usan para mejorar la app. Puedes cambiarlo cuando quieras en «Preferencias de cookies». ');
    var a = el('a', { href: '/app/legal/cookies.html' }, 'Política de cookies');
    p.appendChild(a);
    headText.appendChild(p);
    head.appendChild(headText);
    if (manage) {
      var close = el('button', { type: 'button', class: 'pfc-close', 'aria-label': 'Cerrar sin cambios' }, '×');
      close.addEventListener('click', hide);
      head.appendChild(close);
    }
    banner.appendChild(head);

    var cats = el('ul', { class: 'pfc-cats' });
    var nec = el('li', { class: 'pfc-cat' });
    var necText = el('div', { class: 'pfc-grow' });
    necText.appendChild(el('b', {}, 'Necesarias'));
    necText.appendChild(el('small', {}, 'Tu sesión, tu carrito, esta elección y la protección contra ataques.'));
    nec.appendChild(necText);
    nec.appendChild(el('span', { class: 'pfc-pill' }, 'Siempre activas'));
    cats.appendChild(nec);
    var ana = el('li', { class: 'pfc-cat' });
    var anaLabel = el('label', { class: 'pfc-grow', for: 'pfc-analytics' });
    anaLabel.appendChild(el('b', {}, 'Analítica (PostHog)'));
    anaLabel.appendChild(el('small', {}, 'Qué pantallas y funciones se usan, sin el texto que escribes ni grabar tu sesión. Apagada hasta que la aceptes.'));
    var box = el('input', { type: 'checkbox', id: 'pfc-analytics' });
    box.checked = !!(manage && current && current.analytics);
    ana.appendChild(anaLabel);
    ana.appendChild(box);
    cats.appendChild(ana);
    banner.appendChild(cats);

    var actions = el('div', { class: 'pfc-actions' });
    var reject = el('button', { type: 'button', class: 'pfc-btn', id: 'pfc-reject' }, 'Solo necesarias');
    var accept = el('button', { type: 'button', class: 'pfc-btn', id: 'pfc-accept' }, 'Aceptar analítica');
    reject.addEventListener('click', function () { set(false); });
    accept.addEventListener('click', function () { set(true); });
    actions.appendChild(reject);
    actions.appendChild(accept);
    if (manage) {
      var save = el('button', { type: 'button', class: 'pfc-btn', id: 'pfc-save' }, 'Guardar mi elección');
      save.addEventListener('click', function () { set(box.checked); });
      actions.appendChild(save);
    }
    banner.appendChild(actions);
    if (manage && current) {
      banner.appendChild(el('p', { class: 'pfc-current' },
        'Tu elección actual: ' + (current.analytics ? 'analítica activada' : 'solo necesarias') + ' (desde el ' + fmt(current.at) + ').'));
    }
    (device || document.body).appendChild(banner);
    (manage ? box : reject).focus({ preventScroll: true });
  }

  function bindLinks(root) {
    (root || document).querySelectorAll('[data-cookie-prefs]').forEach(function (link) {
      if (link.dataset.pfcBound) return;
      link.dataset.pfcBound = '1';
      link.addEventListener('click', function (e) { e.preventDefault(); show(true); });
    });
  }

  window.PatitasCookies = {
    version: POLICY_VERSION,
    get: read,
    analyticsAllowed: function () { var c = read(); return !!(c && c.analytics); },
    open: function () { show(true); },
    set: set,
    onChange: function (fn) { if (typeof fn === 'function') listeners.push(fn); },
    bind: bindLinks,
  };

  function init() {
    bindLinks(document);
    if (!read()) show(false);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
