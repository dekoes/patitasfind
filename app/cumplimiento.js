/* ============================================================
   GuauWoow — Consentimiento en la app (contratos K-ACEPT, K-PREF y L-edad)
   Módulo aparte de app.js: usa sus helpers globales (api, esc, toast, $, $$, state, device, navigate, back,
   withBtn, fmtDate, FX, logout, exportMyData, openDeleteAccount, afterLogin, getPosition, saveLocation).
   Se carga después de app.js.

   - Registro: fecha de nacimiento y casilla SEPARADA de 18+ (signupPayload / termsPayload).
   - gate(next): después de iniciar sesión revisa GET /cumplimiento/pendientes:
       verificación reforzada de edad pendiente -> ventana para confirmarla (fecha + SMS nuevo + declaración);
       nueva versión vigente de Términos o Aviso de Privacidad -> ventana de aceptación expresa (bloquea la app);
       anexos de aliados pendientes, aviso previo de 30 días e invitación a activar las alertas cercanas ->
       avisos dentro de Inicio (no bloquean).
   - Perfil -> Preferencias (pantalla "preferences"): alertas cercanas, avisos por WhatsApp y correos
     promocionales, todos apagados al inicio (PATCH /cumplimiento/preferencias), cookies y mis aceptaciones.
   - onApiError(err): 403 age_check_required / age_declaration_required y 400 annex_required abren la ventana.
   ============================================================ */
'use strict';

const Cumplimiento = (() => {
  const NOTICE_KEY = 'patitas_legal_avisos';      // avisos previos que la persona cerró (slug@versión)
  const INVITE_KEY = 'patitas_alertas_invite';    // la invitación a las alertas cercanas se pospuso hasta...
  const ANNEX_KEY = 'patitas_anexos_pospuestos';  // anexos pospuestos en esta sesión (sessionStorage)
  const DOC_URL = /^\/app\/legal\/[a-z0-9-]+\.html(#[\w-]+)?$/;
  let pending = null;
  let pendingAt = 0;

  if (typeof NOTIF_ICON === 'object') Object.assign(NOTIF_ICON, {
    legal_change: ['📜', 'var(--lila)'], age_check: ['🎂', 'var(--yellow)'], support_handoff: ['🙋', 'var(--blue)'],
  });

  // ---------------------------------------------------------------- utilidades
  const store = {
    get(k, s = localStorage) { try { return JSON.parse(s.getItem(k) || 'null'); } catch { return null; } },
    set(k, v, s = localStorage) { try { s.setItem(k, JSON.stringify(v)); } catch { } },
  };
  function ageFrom(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return null;
    const now = new Date();
    let a = now.getFullYear() - +m[1];
    if (now.getMonth() + 1 < +m[2] || (now.getMonth() + 1 === +m[2] && now.getDate() < +m[3])) a--;
    return a;
  }
  function maxBirth() { const d = new Date(); d.setFullYear(d.getFullYear() - 18); return d.toISOString().slice(0, 10); }
  function docLink(d) { return DOC_URL.test(d.url || '') ? d.url : `/app/legal/${encodeURIComponent(d.slug)}.html`; }
  function fechaLarga(iso) {
    const d = parseDate(iso);
    return d ? d.toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'America/Mexico_City' }) : '';
  }
  function modal(id, html, { center = true, closable = true } = {}) {
    let m = document.getElementById(id);
    if (m) m.remove();
    m = document.createElement('div');
    m.className = 'modal' + (center ? ' center' : '');
    m.id = id;
    m.setAttribute('role', 'dialog');
    m.setAttribute('aria-modal', 'true');
    m.innerHTML = html;
    device.appendChild(m);
    if (closable) m.addEventListener('click', e => { if (e.target === m || e.target.closest('[data-cp-close]')) close(m); });
    requestAnimationFrame(() => { m.classList.add('open'); FX.decorate(m); });
    return m;
  }
  function close(m) { if (m) { m.classList.remove('open'); setTimeout(() => m.remove(), 250); } }

  // ---------------------------------------------------------------- registro y cuenta con Google
  function readAge(birthSel, adultSel) {
    const birth = ($(birthSel) || {}).value || '';
    const adult = !!($(adultSel) || {}).checked;
    if (!birth) throw new Error('Escribe tu fecha de nacimiento');
    const a = ageFrom(birth);
    if (a == null || a > 120) throw new Error('Revisa tu fecha de nacimiento');
    if (a < 18) throw new Error('GuauWoow es solo para personas de 18 años o más');
    if (!adult) throw new Error('Marca la casilla en la que declaras tener 18 años o más');
    return { birth_date: birth, is_adult: true };
  }
  /* Campos de edad del registro: fecha de nacimiento + casilla separada de 18+ (L-edad) */
  function signupPayload() { return readAge('#auth-birth', '#auth-adult'); }
  /* Ventana «Antes de continuar» (cuentas con Google o sin fecha de nacimiento) */
  function prepareTermsModal(user) {
    const wrap = $('#tm-age');
    if (wrap) wrap.classList.toggle('hidden', !!(user && user.age_declared));
    const b = $('#tm-birth'); if (b) b.max = maxBirth();
  }
  function termsPayload(user) {
    return user && user.age_declared ? {} : readAge('#tm-birth', '#tm-adult');
  }
  function initSignupFields() {
    const b = $('#auth-birth'); if (b) b.max = maxBirth();
  }

  // ---------------------------------------------------------------- después de iniciar sesión
  async function load() {
    pending = await api('/cumplimiento/pendientes', { noVerifyRedirect: true });
    pendingAt = Date.now();
    return pending;
  }
  async function gate(next) {
    try { await load(); }
    catch { pending = null; return next(); }
    const age = pending.verificacion_edad;
    if (age && age.required) return openAgeCheck(age, next);
    const blocking = (pending.pendientes || []).filter(p => p.blocking);
    if (blocking.length) return openAcceptance(blocking, { blocking: true, next });
    next();
  }
  async function refresh() {
    try { await load(); renderHomeNotices(); } catch { }
  }
  /* Al entrar a la app (enterApp): usa lo que trajo gate() hace un momento o lo vuelve a pedir */
  function homeNotices() {
    if (!state.token) return;
    if (pending && Date.now() - pendingAt < 15000) renderHomeNotices(); else refresh();
  }

  /* Ventana de aceptación expresa: una casilla sin marcar por documento */
  function openAcceptance(docs, { blocking = false, next = null, reason = '' } = {}) {
    const items = docs.map((d, i) => `
      <div class="card p cp-doc">
        <div class="between"><b>${esc(d.title)}</b><span class="badge b-lila">v. ${esc(d.version)}</span></div>
        <div class="small muted mt4">${d.effective_at ? 'Vigente desde el ' + esc(fechaLarga(d.effective_at)) : 'Vigente desde su publicación'}</div>
        ${d.summary ? `<p class="small mt8"><b>Qué cambia:</b> ${esc(d.summary)}</p>` : ''}
        <a class="link small" href="${esc(docLink(d))}" target="_blank" rel="noopener">Leer el documento completo</a>
        <label class="row small mt8 cp-check"><input type="checkbox" data-cp-doc="${i}"> <span>He leído y acepto «${esc(d.title)}» (versión ${esc(d.version)}).</span></label>
      </div>`).join('');
    const intro = blocking
      ? 'Actualizamos documentos que te aplican. Para seguir usando tu cuenta necesitamos que los aceptes de forma expresa: seguir usando GuauWoow no cuenta como aceptación.'
      : (reason || 'Para seguir con esta función necesitamos que aceptes estos documentos.');
    const m = modal('cp-accept-modal', `
      <div class="mm-card cp-card" style="text-align:left">
        <h2 class="h2 center">${blocking ? 'Actualizamos nuestras reglas' : 'Antes de continuar'}</h2>
        <p class="small mt8">${esc(intro)}</p>
        <div class="col mt12" style="gap:10px">${items}</div>
        <button type="button" class="btn block mt16" id="cp-accept-btn">Aceptar y continuar</button>
        ${blocking ? `<p class="small muted mt12">¿No estás de acuerdo? Puedes descargar una copia de tus datos o cerrar tu cuenta sin costo.</p>
          <div class="row mt8" style="flex-wrap:wrap;gap:8px"><button type="button" class="btn btn-sm btn-ghost grow" id="cp-export">Descargar mis datos</button><button type="button" class="btn btn-sm btn-ghost grow" id="cp-delete">Eliminar mi cuenta</button></div>
          <button type="button" class="link small" id="cp-logout" style="display:block;margin:12px auto 0">Salir</button>`
        : '<button type="button" class="link small" data-cp-close style="display:block;margin:12px auto 0">Ahora no</button>'}
      </div>`, { closable: !blocking });
    $('#cp-accept-btn', m).addEventListener('click', e => {
      const boxes = $$('[data-cp-doc]', m);
      if (boxes.some(b => !b.checked)) return toast('Marca cada casilla para aceptar', 'error');
      withBtn(e.currentTarget, async () => {
        for (const d of docs) {
          await api('/cumplimiento/aceptaciones', { method: 'POST', body: { slug: d.slug, version: d.version, sha256: d.sha256 }, noVerifyRedirect: true });
        }
        close(m);
        toast('¡Gracias! Guardamos tu aceptación 📜', 'ok');
        if (next) next(); else refresh();
      });
    });
    if (blocking) {
      $('#cp-export', m).addEventListener('click', () => exportMyData());
      $('#cp-delete', m).addEventListener('click', () => { close(m); openDeleteAccount(); });
      $('#cp-logout', m).addEventListener('click', () => { close(m); logout(); });
    } else {
      $$('[data-cp-close]', m).forEach(b => b.addEventListener('click', () => {
        const snoozed = store.get(ANNEX_KEY, sessionStorage) || [];
        store.set(ANNEX_KEY, [...new Set([...snoozed, ...docs.map(d => d.slug)])], sessionStorage);
      }));
    }
  }

  // ---------------------------------------------------------------- avisos dentro de Inicio
  function renderHomeNotices() {
    const anchor = $('#email-banner');
    let box = $('#cp-notices');
    if (!anchor) return;
    if (!box) { box = document.createElement('div'); box.id = 'cp-notices'; anchor.insertAdjacentElement('afterend', box); }
    const p = pending || {};
    const html = [];
    const closed = store.get(NOTICE_KEY) || [];
    (p.avisos || []).filter(a => !closed.includes(`${a.slug}@${a.version}`)).forEach(a => {
      html.push(`<div class="email-banner cp-banner" role="status" data-cp-aviso="${esc(a.slug)}@${esc(a.version)}">
        <span class="eb-ic" aria-hidden="true">📜</span>
        <div class="grow"><b>Cambian los ${esc(a.title)}</b><div class="small">Entran en vigor el ${esc(fechaLarga(a.effective_at))}. Te pediremos aceptarlos en la app.</div></div>
        <a class="link small" href="${esc(docLink(a))}" target="_blank" rel="noopener">Ver cambios</a>
        <button type="button" class="iconbtn sm" data-cp-dismiss aria-label="Cerrar aviso"><svg width="14" height="14"><use href="#close"/></svg></button></div>`);
    });
    const snoozed = store.get(ANNEX_KEY, sessionStorage) || [];
    const annex = (p.pendientes || []).filter(d => !d.blocking && !d.at_checkout);
    if (annex.length) {
      const fresh = annex.some(d => !snoozed.includes(d.slug));
      html.push(`<div class="email-banner cp-banner" role="status">
        <span class="eb-ic" aria-hidden="true">🤝</span>
        <div class="grow"><b>Acepta tus condiciones de aliado</b><div class="small">${esc(annex.map(d => d.title).join(', '))}. Sin la versión vigente no podemos verificar ni renovar tu verificación, y no puedes recibir donativos ni vender.</div></div>
        <button type="button" class="link small" id="cp-annex-open">${fresh ? 'Revisar' : 'Revisar ahora'}</button></div>`);
    }
    const invite = store.get(INVITE_KEY);
    if (p.invitar_alertas && !(invite && Date.now() < invite)) {
      html.push(`<div class="email-banner cp-banner cp-invite" role="status">
        <span class="eb-ic" aria-hidden="true">📍</span>
        <div class="grow"><b>¿Te avisamos de perritos perdidos cerca?</b><div class="small">Las alertas están apagadas hasta que tú las actives.</div></div>
        <button type="button" class="link small" id="cp-invite-on">Activar</button>
        <button type="button" class="iconbtn sm" id="cp-invite-later" aria-label="Ahora no"><svg width="14" height="14"><use href="#close"/></svg></button></div>`);
    }
    box.innerHTML = html.join('');
    FX.decorate(box);
    $$('[data-cp-dismiss]', box).forEach(b => b.addEventListener('click', () => {
      const row = b.closest('[data-cp-aviso]');
      store.set(NOTICE_KEY, [...new Set([...(store.get(NOTICE_KEY) || []), row.dataset.cpAviso])]);
      row.remove();
    }));
    const annexBtn = $('#cp-annex-open', box);
    if (annexBtn) annexBtn.addEventListener('click', () => openAcceptance(annex, {
      reason: 'Como aliado de GuauWoow (refugio, vendedor, clínica o casa de paso) necesitamos tu aceptación de estas condiciones. Es una casilla aparte de tus Términos de usuario.',
    }));
    const on = $('#cp-invite-on', box);
    if (on) on.addEventListener('click', () => withBtn(on, async () => {
      await setPreference('notify_nearby', true);
      store.set(INVITE_KEY, Date.now() + 3650 * 86400000);
      $('.cp-invite', box) && $('.cp-invite', box).remove();
      toast(state.me && state.me.latitude != null ? 'Listo, te avisaremos de perritos perdidos cerca 📍' : 'Listo. Guarda tu ubicación en Inicio para recibir las alertas 📍', 'ok');
    }));
    const later = $('#cp-invite-later', box);
    if (later) later.addEventListener('click', () => { store.set(INVITE_KEY, Date.now() + 30 * 86400000); later.closest('.cp-invite').remove(); });
  }

  // ---------------------------------------------------------------- verificación reforzada de edad
  async function openAgeCheck(status, next) {
    if (!status) { try { status = await api('/cumplimiento/edad', { noVerifyRedirect: true }); } catch (e) { return toast(e.message, 'error'); } }
    if (!status.required) { if (next) next(); return; }
    if (status.in_review) {
      // Tres fechas que no coincidieron: la revisa el equipo; ya no se completa desde la app
      const r = modal('cp-age-modal', `
      <div class="mm-card cp-card" style="text-align:left">
        <h2 class="h2 center">Estamos revisando tu cuenta 🎂</h2>
        <p class="small mt8">${esc(status.review_message || 'Nuestro equipo revisará tu cuenta y te escribirá.')}</p>
        <p class="small muted mt8">Si crees que es un error, escríbenos desde Ayuda.</p>
        <button type="button" class="btn block mt16" data-cp-close>Entendido</button>
      </div>`);
      $$('[data-cp-close]', r).forEach(b => b.addEventListener('click', () => { if (next) next(); }, { once: true }));
      return;
    }
    const m = modal('cp-age-modal', `
      <div class="mm-card cp-card" style="text-align:left">
        <h2 class="h2 center">Confirma tu edad 🎂</h2>
        <p class="small mt8">${esc(status.reason_label || 'Necesitamos confirmar que tienes 18 años o más.')} Mientras lo confirmas, tu cuenta queda en modo de solo lectura.</p>
        <p class="small muted mt8">No te pediremos copia de tu identificación ni usaremos reconocimiento facial o biometría. Solo guardamos la constancia: fecha, método y resultado.</p>
        <label class="lbl mt12" for="cp-age-birth">Tu fecha de nacimiento</label>
        <input id="cp-age-birth" class="inp" type="date" max="${maxBirth()}" autocomplete="bday">
        <div class="lbl mt12">Código por SMS ${status.phone ? `<span class="muted">(${esc(status.phone)})</span>` : ''}</div>
        ${status.phone ? `<div class="row" style="gap:8px"><input id="cp-age-code" class="inp grow" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6 dígitos"><button type="button" class="btn btn-sm btn-ghost" id="cp-age-send">Enviar código</button></div>`
          : '<p class="small">Agrega tu celular en Perfil → Editar perfil para recibir el código.</p>'}
        <label class="row small mt12 cp-check"><input type="checkbox" id="cp-age-decl"> <span>${esc(status.declaration_text || 'Declaro que tengo 18 años o más.')}</span></label>
        <button type="button" class="btn block mt16" id="cp-age-submit" ${status.phone ? '' : 'disabled'}>Confirmar</button>
        <button type="button" class="link small" data-cp-close style="display:block;margin:12px auto 0">Más tarde</button>
      </div>`);
    $$('[data-cp-close]', m).forEach(b => b.addEventListener('click', () => { if (next) next(); }, { once: true }));
    const send = $('#cp-age-send', m);
    if (send) send.addEventListener('click', () => withBtn(send, async () => {
      const r = await api('/cumplimiento/edad/codigo', { method: 'POST', noVerifyRedirect: true });
      if (r && r.dev_code) { $('#cp-age-code', m).value = r.dev_code; console.info('Código (dev):', r.dev_code); }
      toast('Te enviamos un código por SMS 📲', 'ok');
    }));
    $('#cp-age-submit', m).addEventListener('click', e => {
      const birth = $('#cp-age-birth', m).value;
      const code = ($('#cp-age-code', m) || {}).value || '';
      if (!birth) return toast('Escribe tu fecha de nacimiento', 'error');
      if (!/^\d{6}$/.test(code.trim())) return toast('Escribe el código de 6 dígitos', 'error');
      if (!$('#cp-age-decl', m).checked) return toast('Marca la declaración para continuar', 'error');
      withBtn(e.currentTarget, async () => {
        try {
          await api('/cumplimiento/edad/verificar', { method: 'POST', body: { birth_date: birth, code: code.trim(), declaration: true }, noVerifyRedirect: true });
        } catch (err) {
          // 409: pasó a revisión manual -> se muestra ese estado en lugar del formulario
          if (err.status === 409) { close(m); setTimeout(() => openAgeCheck(null, next), 300); }
          throw err;
        }
        try { state.me = await api('/users/me'); } catch { }
        close(m);
        await FX.success('¡Gracias!', 'Confirmamos tu edad. Tu cuenta ya no está limitada ✅');
        if (next) next();
      });
    });
  }

  /* Errores con código del backend (app.js api()) */
  function onApiError(err) {
    if (!err || !err.code) return;
    if (err.code === 'age_check_required') {
      err.message = 'Confirma tu edad para continuar 🎂';
      setTimeout(() => openAgeCheck(null, null), 50);
    } else if (err.code === 'age_declaration_required') {
      err.message = 'Indica tu fecha de nacimiento para continuar';
      setTimeout(() => { prepareTermsModal(state.me); $('#terms-modal').classList.add('open'); FX.decorate($('#terms-modal')); }, 50);
    } else if (err.code === 'annex_required' && err.data && Array.isArray(err.data.documents)) {
      setTimeout(() => openAcceptance(err.data.documents, { reason: err.message + ' Después vuelve a enviar el formulario.' }), 50);
    } else if (err.code === 'underage_account_closed') {
      // Cuenta de una persona menor de 18 cerrada al completar el registro: se sale de la sesión
      setTimeout(() => { if (typeof logout === 'function') logout(true); }, 2500);
    } else if (err.code === 'legal_version_mismatch') {
      setTimeout(refresh, 50);
    } else if (err.code === 'legal_acceptance_required') {
      // El servidor bloquea las acciones hasta aceptar la versión vigente: abre la ventana de aceptación
      err.message = 'Acepta la versión vigente de los Términos y del Aviso de Privacidad para continuar';
      setTimeout(() => gate(() => {}), 50);
    }
  }

  // ---------------------------------------------------------------- Perfil -> Preferencias
  const SWITCHES = [
    ['notify_nearby', 'Avisarme de perritos perdidos cerca de mí'],
    ['whatsapp_alerts', 'Avisos por WhatsApp'],
    ['email_marketing', 'Correos promocionales'],
  ];
  async function setPreference(purpose, value) {
    let prefs = await api('/cumplimiento/preferencias', { method: 'PATCH', body: { [purpose]: value } });
    if (state.me) { state.me[purpose === 'email_marketing' ? 'marketing_opt_in' : purpose] = prefs[purpose]; if (purpose === 'email_marketing') state.me.email_marketing = prefs[purpose]; }
    // La ubicación vive en la cuenta solo con las alertas cercanas encendidas (privacidad.html §8): al activarlas se
    // guarda la que elegiste en Inicio; al apagarlas el servidor la borra
    if (purpose === 'notify_nearby' && state.me) {
      if (prefs.notify_nearby && state.coords) {
        try {
          const me = await api('/users/me', { method: 'PATCH', body: { latitude: state.coords.lat, longitude: state.coords.lon, city: state.city } });
          state.me.latitude = me.latitude; state.me.longitude = me.longitude;
          prefs = { ...prefs, has_location: me.latitude != null };
        } catch { }
      } else if (!prefs.notify_nearby) { state.me.latitude = state.me.longitude = null; prefs = { ...prefs, has_location: false }; }
    }
    if (pending) pending.invitar_alertas = false;
    return prefs;
  }
  function switchNote(purpose, prefs) {
    if (purpose === 'notify_nearby' && !prefs.has_location) return 'Guarda tu ubicación en Inicio para recibir estas alertas.';
    if (purpose === 'whatsapp_alerts' && !prefs.phone_verified) return 'Necesitas un teléfono verificado para recibirlos.';
    if (purpose === 'whatsapp_alerts' && !prefs.whatsapp_enabled) return 'El canal de WhatsApp aún no está activo; guardaremos tu elección.';
    return '';
  }
  async function loadPreferences() {
    const body = $('#preferences-body');
    if (!body) return;
    body.innerHTML = FX.inlineLoader('Cargando tus preferencias...');
    let prefs, mine = { aceptaciones: [] };
    try {
      [prefs, mine] = await Promise.all([api('/cumplimiento/preferencias'), api('/cumplimiento/aceptaciones/mias').catch(() => ({ aceptaciones: [] }))]);
    } catch (e) { body.innerHTML = ''; return toast(e.message, 'error'); }
    const cookie = window.PatitasCookies && PatitasCookies.get();
    const updated = p => prefs.updated_at && prefs.updated_at[p] ? `Último cambio: ${esc(fmtDate(prefs.updated_at[p]))}` : 'Apagado hasta que lo actives';
    const rows = SWITCHES.map(([p, label]) => {
      const note = switchNote(p, prefs);
      // Se muestra el texto exacto que queda en la constancia (su versión va en text_version)
      const full = (prefs.texts[p] || {}).text || label;
      const cut = full.indexOf(': ');
      const title = cut > 0 ? full.slice(0, cut) : label, desc = cut > 0 ? full.slice(cut + 2) : '';
      return `<div class="card p cp-pref">
        <label class="row" for="pref-${p}" style="cursor:pointer;align-items:flex-start"><div class="grow"><b>${esc(title)}</b>
          <div class="small muted mt4">${esc(desc)}</div>
          ${note ? `<div class="small mt4" style="font-weight:700">${esc(note)}</div>` : ''}
          <div class="small muted mt4" data-pref-updated="${p}">${updated(p)}</div></div>
          <input type="checkbox" class="switch" id="pref-${p}" data-pref="${p}" ${prefs[p] ? 'checked' : ''}></label></div>`;
    }).join('');
    const methods = { registro: 'Al registrarte', reaceptacion: 'Aceptación de una versión nueva', checkout: 'En una compra', anexo: 'Condiciones de aliado', donativo: 'En un donativo' };
    const accepted = (mine.aceptaciones || []).slice().reverse().slice(0, 12).map(a => `<div class="between small cp-acc"><span><b>${esc(a.slug)}</b> · v. ${esc(a.version)}<br><span class="muted">${esc(methods[a.method] || a.method)}</span></span><span class="muted">${esc(fmtDate(a.accepted_at))}</span></div>`).join('');
    body.innerHTML = `
      <p class="small muted">Todo lo que no es esencial está apagado hasta que tú lo actives. Los cambios son inmediatos y apagar es tan fácil como encender.</p>
      <div class="col mt12" style="gap:10px">${rows}</div>
      <div class="lbl mt20">Cookies</div>
      <div class="card p row tap" id="pref-cookies" role="button" tabindex="0"><div class="grow"><b>Preferencias de cookies</b><div class="small muted">${cookie ? (cookie.analytics ? 'Analítica activada' : 'Solo necesarias') : 'Sin elegir: solo necesarias'}</div></div><b>→</b></div>
      <div class="lbl mt20">Mensajes que siempre recibes</div>
      <div class="card p small">Códigos de verificación, seguridad de tu cuenta, recibos de pedidos y donativos, y cambios a los Términos o al Aviso de Privacidad. Nunca llevan publicidad. <a class="link" href="/app/legal/comunicaciones.html" target="_blank" rel="noopener">Comunicaciones y preferencias</a></div>
      <div class="lbl mt20">Mis aceptaciones</div>
      <div class="card p col" style="gap:8px">${accepted || '<span class="small muted">Aún no hay aceptaciones registradas.</span>'}
        <a class="link small" href="/app/legal/historial.html" target="_blank" rel="noopener">Ver el historial de versiones</a></div>
      <p class="small muted mt12">En WhatsApp también puedes escribir <b>BAJA</b> para dejar de recibir avisos y <b>ALTA</b> para volver a recibirlos.</p>`;
    FX.decorate(body);
    $$('[data-pref]', body).forEach(input => input.addEventListener('change', async e => {
      const p = e.target.dataset.pref, on = e.target.checked;
      e.target.disabled = true;
      try {
        const res = await setPreference(p, on);
        const upd = $(`[data-pref-updated="${p}"]`, body);
        if (upd && res.updated_at && res.updated_at[p]) upd.textContent = 'Último cambio: ' + fmtDate(res.updated_at[p]);
        toast(on ? 'Listo, lo activamos ✅' : 'Listo, lo apagamos', 'ok');
      } catch (err) { e.target.checked = !on; toast(err.message, 'error'); }
      finally { e.target.disabled = false; }
    }));
    const ck = $('#pref-cookies', body);
    const openCookies = () => { if (window.PatitasCookies) PatitasCookies.open(); };
    ck.addEventListener('click', openCookies);
    ck.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCookies(); } });
  }
  window.screenLoaders = Object.assign(window.screenLoaders || {}, { preferences: loadPreferences });
  if (window.PatitasCookies) PatitasCookies.onChange(() => { if (current === 'preferences') loadPreferences(); });

  initSignupFields();
  return { signupPayload, termsPayload, prepareTermsModal, gate, refresh, homeNotices, onApiError, openAgeCheck, openAcceptance, loadPreferences, setPreference };
})();
window.Cumplimiento = Cumplimiento;
