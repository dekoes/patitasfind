/* ============================================================
   GuauWoow — Aclaraciones y quejas sobre clínicas, sin cuenta (veterinarias-solicitud.html)
   GET /veterinaries?q (búsqueda), GET /veterinaries/{id}?google=false (sin consultar Google),
   GET /veterinaries/{id}/reviews, POST /veterinaries/{id}/requests {kind, review_id, relation,
   reason, name, email, text, accept_privacy}. Acepta ?vet=ID&review=ID en la URL.
   ============================================================ */
'use strict';

(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const EMAIL_RE = /^[^\s@<>"']+@[^\s@<>"']+\.[^\s@<>"']+$/;
  const params = new URLSearchParams(location.search);
  let vet = null;
  let reviews = [];

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || 'GET',
      headers: opts.body ? { 'Content-Type': 'application/json' } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      const d = data && data.detail;
      const msg = typeof d === 'string' ? d : Array.isArray(d) ? 'Revisa los datos del formulario.' : `Error ${res.status}`;
      throw new Error(res.status === 429 ? 'Enviaste muchas solicitudes. Inténtalo mañana.' : msg);
    }
    return data;
  }
  function fmtDate(iso) {
    try { return new Date(iso.endsWith('Z') ? iso : iso + 'Z').toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' }); } catch { return ''; }
  }
  function showError(msg) { const e = $('#err'); e.textContent = msg; e.classList.toggle('hidden', !msg); }

  /* ---------- 1. clínica ---------- */
  async function search(q) {
    const box = $('#vet-results');
    box.innerHTML = '<p class="small muted">Buscando…</p>';
    try {
      const items = await api(`/veterinaries?${new URLSearchParams({ q, limit: 10 })}`);
      box.innerHTML = items.length
        ? items.map(v => `<label class="opt"><input type="radio" name="vet" value="${+v.id}"> <span>${esc(v.name)}<br><span class="small muted">${esc([v.address, v.city].filter(Boolean).join(', '))}</span></span></label>`).join('')
        : '<p class="small muted">No encontramos clínicas con ese nombre. Prueba con la ciudad.</p>';
      $$('input[name=vet]', box).forEach(r => r.addEventListener('change', () => pick(r.value)));
    } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  }
  async function pick(id, reviewId) {
    try {
      vet = await api(`/veterinaries/${encodeURIComponent(id)}?google=false`);
    } catch (e) { $('#vet-results').innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    try { reviews = await api(`/veterinaries/${encodeURIComponent(vet.id)}/reviews?limit=50`); } catch { reviews = []; }
    $('#vet-picked').innerHTML = `<b>${esc(vet.name)}</b><div class="small muted">${esc([vet.address, vet.city].filter(Boolean).join(', '))}</div>
      <button type="button" class="ghost small" id="vet-change" style="margin-top:8px">Cambiar de clínica</button>`;
    $('#vet-picked').classList.remove('hidden');
    $('#vet-search').classList.add('hidden');
    $('#vet-results').innerHTML = '';
    $('#vet-change').addEventListener('click', () => {
      vet = null; $('#vet-picked').classList.add('hidden'); $('#vet-search').classList.remove('hidden'); $('#req-form').classList.add('hidden'); $('#vet-q').focus();
    });
    renderReviews(reviewId);
    $('#req-form').classList.remove('hidden');
    syncKind();
  }
  function renderReviews(selected) {
    const box = $('#reviews');
    box.innerHTML = reviews.length
      ? reviews.map(r => `<label class="opt"><input type="radio" name="review" value="${+r.id}" ${String(r.id) === String(selected) ? 'checked' : ''}>
          <span><b>${esc((r.user && r.user.full_name) || r.author_name || 'Usuario')}</b> · ${'★'.repeat(Math.max(0, Math.min(5, +r.rating || 0)))}<br><span class="small review">${esc(r.text || 'Sin texto')}</span></span></label>`).join('')
        + '<label class="opt" data-no-review><input type="radio" name="review" value=""> <span>Mi queja no es sobre una reseña</span></label>'
      : '<p class="small muted">Esta clínica no tiene reseñas en GuauWoow.</p>';
    $$('input[name=review]', box).forEach(r => r.addEventListener('change', paintOpts));
    paintOpts();
  }
  function paintOpts() { $$('.opt').forEach(o => o.classList.toggle('on', !!$('input:checked', o))); }

  /* ---------- 2. solicitud ---------- */
  function kind() { return ($('input[name=kind]:checked') || {}).value || 'aclaracion'; }
  function syncKind() {
    const k = kind();
    $('#reason-box').classList.toggle('hidden', k !== 'queja');
    const none = $('[data-no-review]');
    if (none) none.classList.toggle('hidden', k === 'aclaracion');
    if (k === 'aclaracion' && none && $('input', none).checked) $('input', none).checked = false;
    $('#text-lbl').textContent = k === 'aclaracion' ? 'Tu aclaración' : 'Cuéntanos qué pasó';
    $('#text-hint').textContent = k === 'aclaracion'
      ? 'Escribe la aclaración tal como quieres que se publique: sin teléfonos, correos ni datos de otras personas.'
      : 'Solo la ve nuestro equipo. Incluye lo necesario para revisarla (fechas, qué parte de la reseña o del perfil es incorrecta).';
    paintOpts();
  }
  async function submit(e) {
    e.preventDefault();
    showError('');
    if (!vet) return showError('Elige primero la clínica.');
    const k = kind();
    const reviewInput = $('input[name=review]:checked');
    const reviewId = reviewInput && reviewInput.value ? +reviewInput.value : null;
    const name = $('#name').value.trim(), email = $('#email').value.trim(), text = $('#text').value.trim();
    if (k === 'aclaracion' && !reviewId) return showError('Elige la reseña sobre la que quieres publicar una aclaración.');
    if (name.length < 3) return showError('Escribe tu nombre para poder responderte.');
    if (!EMAIL_RE.test(email)) return showError('Escribe un correo válido para poder responderte.');
    if (text.length < 10) return showError('Cuéntanos con más detalle (mínimo 10 caracteres).');
    if (!$('#privacy').checked) return showError('Marca la casilla del aviso de privacidad para continuar.');
    const btn = $('#send');
    btn.disabled = true;
    try {
      const r = await api(`/veterinaries/${vet.id}/requests`, { method: 'POST', body: {
        kind: k, review_id: reviewId, relation: $('#relation').value, reason: k === 'queja' ? $('#reason').value : null,
        name, email, text, accept_privacy: true,
      } });
      $('#req-form').classList.add('hidden');
      $('#step-vet').classList.add('hidden');
      const done = $('#done');
      done.innerHTML = `<b>¡Listo! Recibimos tu solicitud 🐾</b><p>Folio <b>${+r.id}</b>. Te responderemos a <b>${esc(email)}</b> a más tardar el <b>${esc(fmtDate(r.due_at))}</b>.</p>`;
      done.classList.remove('hidden');
      done.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      showError(err.message);
    } finally { btn.disabled = false; }
  }

  $('#vet-search').addEventListener('submit', e => { e.preventDefault(); const q = $('#vet-q').value.trim(); if (q.length >= 2) search(q.slice(0, 100)); });
  $$('input[name=kind]').forEach(r => r.addEventListener('change', syncKind));
  $('#req-form').addEventListener('submit', submit);
  const vid = params.get('vet');
  if (/^\d+$/.test(vid || '')) pick(vid, /^\d+$/.test(params.get('review') || '') ? params.get('review') : null);
})();
