/* ============================================================
   GuauWoow — Veterinarias (directorio, reseñas y «Mi veterinaria»)
   Módulo aparte de app.js: usa sus helpers globales (api, esc, toast, navigate, back,
   state, FX, imgTag, photo, dist, fmtDate, timeAgo, avatarHtml, initials, safeUrl,
   withBtn, track, openFlag, photoStore, locStore, clearPhotos, resetLoc, uploadFiles,
   uploadDocuments, getPosition, setCoords, mapPopup, share, device). Se carga después de app.js.

   Contratos (V2): GET /veterinaries?lat&lon&radius_km&city&emergency&q&skip&limit,
   GET /veterinaries/{id}, POST /veterinaries, PATCH /veterinaries/{id}, GET /veterinaries/me,
   POST /veterinaries/{id}/reviews {rating, text, visited_month?, incentivized?},
   DELETE /veterinaries/{id}/reviews/me, GET /veterinaries/{id}/reviews?skip&limit,
   POST /veterinaries/{id}/reviews/{review_id}/reply {text} (respuesta pública de la clínica),
   POST /veterinaries/{id}/google-search {query}, POST /veterinaries/{id}/google-link {place_id|null},
   POST /veterinaries/{id}/requests {kind: aclaracion|queja, review_id?, relation, reason?, text}
   (sin cuenta: veterinarias-solicitud.html). Las respuestas públicas traen is_owner / mine, no ids de cuenta.
   Mientras el backend no exista, un 404 «Not Found» se muestra como «pronto» sin romper la app.

   Google Maps (políticas de Places, verificadas el 2026-10-17 en
   https://developers.google.com/maps/documentation/places/web-service/policies): el bloque de Google va
   en su propio contenedor con el logotipo «Google Maps» (alt «Google Maps», 16-19 px de alto, con su
   espacio libre), avatar + nombre + enlace de cada autor, reseñas completas en el orden de Google (máx. 5),
   aviso de orden y de traducción, «Ver en Google Maps» y «Reportar a Google» por reseña y enlace a todas
   las reseñas. Nunca se muestra junto al mapa de OpenStreetMap (el pin del mapa solo lleva datos propios).
   ============================================================ */
'use strict';

const VET = (() => {
  const STATES = ['Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche', 'Chiapas', 'Chihuahua', 'Ciudad de México',
    'Coahuila', 'Colima', 'Durango', 'Estado de México', 'Guanajuato', 'Guerrero', 'Hidalgo', 'Jalisco', 'Michoacán', 'Morelos', 'Nayarit',
    'Nuevo León', 'Oaxaca', 'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa', 'Sonora', 'Tabasco', 'Tamaulipas',
    'Tlaxcala', 'Veracruz', 'Yucatán', 'Zacatecas'];
  // Lista cerrada de servicios (la investigación legal pide evitar texto libre con superlativos o fármacos)
  const SERVICES = ['Consulta general', 'Vacunas', 'Desparasitación', 'Esterilización', 'Cirugía', 'Hospitalización', 'Laboratorio',
    'Rayos X', 'Ultrasonido', 'Odontología', 'Estética y baño', 'Nutrición', 'Atención a domicilio', 'Animales exóticos', 'Guardería o pensión'];
  const DAYS = [['mon', 'Lunes', 'Lun'], ['tue', 'Martes', 'Mar'], ['wed', 'Miércoles', 'Mié'], ['thu', 'Jueves', 'Jue'], ['fri', 'Viernes', 'Vie'], ['sat', 'Sábado', 'Sáb'], ['sun', 'Domingo', 'Dom']];
  const STATUS = { pending: ['En revisión', 'b-yellow'], verified: ['Verificada', 'b-green'], rejected: ['Rechazada', 'b-red'] };
  // Texto fijo de la insignia: dice solo lo que se verificó (hallazgo 17 de la investigación legal)
  // Mismo texto que veterinarias.html §4 (y BADGE_TEMPLATE del backend): solo se usa si el backend no manda badge_text
  const BADGE_TIP = 'Comprobamos que la cédula profesional del médico veterinario responsable existe en el Registro Nacional de Profesionistas de la SEP y coincide con el nombre registrado; la volvemos a comprobar cada año. No verificamos la calidad de la atención, las instalaciones, los precios ni los permisos locales; no somos autoridad ni colegio de profesionistas.';
  const EMERGENCY_NOTE = 'GuauWoow no es un servicio de emergencias ni presta servicios veterinarios: es un directorio. Si tu perrito está grave, llama directamente a la clínica o acude a una de urgencias.';
  const DISCLAIMER = 'GuauWoow es un directorio: no presta servicios veterinarios, no cobra consultas ni garantiza resultados. La relación es con la clínica y su médico responsable.';
  const GOOGLE_ORDER = 'Reseñas de Google Maps ordenadas por relevancia según Google (máximo 5). Google no verifica las reseñas. GuauWoow no las guarda, modera ni responde: para reportar una usa el enlace de Google.';
  const GOOGLE_POLICY_URL = 'https://support.google.com/contributionpolicy/answer/7400114';
  const GM_LOGO = '<img src="/app/img/google-maps-logo.svg" alt="Google Maps" width="98" height="18" class="gm-logo" translate="no">';
  const CEDULA_RE = /^\d{5,10}$/;  // igual que el backend (5 a 10 dígitos)
  const MAX_PHOTOS = 5;
  const PAGE = 20;

  const filters = { near: false, emergency: false, city: '', q: '' };
  let listSkip = 0;
  let editing = null;      // veterinaria que se está editando (null = registro nuevo)
  let cedulaFile = null;   // archivo de la cédula elegido en el formulario
  let keepPhotos = [];     // fotos ya subidas que se conservan al editar
  let detail = null;       // veterinaria abierta en la pantalla de detalle
  let reviewsShown = 0;

  if (typeof FLAG_TARGET === 'object') Object.assign(FLAG_TARGET, { veterinary: 'esta veterinaria', veterinary_review: 'esta reseña' });
  // Solo los tipos que manda el backend (routers/veterinaries.py y tasks/veterinaries.py)
  if (typeof NOTIF_ICON === 'object') Object.assign(NOTIF_ICON, {
    veterinary_verified: ['🩺', 'var(--green)'], veterinary_rejected: ['🩺', 'var(--sand)'], veterinary_pending: ['🩺', 'var(--yellow)'],
    veterinary_review: ['⭐', 'var(--yellow)'], veterinary_review_held: ['🚩', 'var(--pink)'], veterinary_expired: ['⏳', 'var(--sand)'],
    veterinary_google_unlinked: ['🗺️', 'var(--sand)'], veterinary_request: ['📨', 'var(--blue)'], veterinary_request_resolved: ['📨', 'var(--green)'],
  });
  // Avisos para el equipo: se atienden en el panel de administración
  const ADMIN_TYPES = ['veterinary_pending', 'veterinary_review_held', 'veterinary_request'];
  const REQUEST_REASONS = [['honor_reputacion', 'Afecta mi honor o reputación'], ['resena_falsa', 'Reseña falsa o pagada'], ['datos_personales', 'Publica datos personales'],
    ['cedula_falsa', 'Cédula o veterinario falso'], ['condiciones_sanitarias', 'Condiciones sanitarias del establecimiento'], ['publicidad_enganosa', 'Publicidad engañosa'], ['otro', 'Otro motivo']];
  const PUBLIC_FORM = '/app/veterinarias-solicitud.html';
  // Página pública de la sección (/app/legal/veterinarias.html). Mientras no se publique se enlaza a los Términos.
  let legalP = null;
  function legalUrl() {
    if (!legalP) legalP = fetch('/app/legal/veterinarias.html', { method: 'HEAD' })
      .then(r => (r.ok && /html/.test(r.headers.get('content-type') || '') ? '/app/legal/veterinarias.html' : '/app/legal/terminos.html'))
      .catch(() => '/app/legal/terminos.html');
    return legalP;
  }

  /* ---------- utilidades ---------- */
  // El módulo del servidor todavía no existe (404 genérico) — distinto de «no tienes veterinaria» (404 con mensaje propio)
  function missing(e) { return !!e && e.status === 404 && (e.message === 'Not Found' || e.message === 'Error 404'); }
  const SOON = '<div class="card p small mt12" style="background:var(--sand)">🩺 El directorio de veterinarias se está activando. Vuelve en un ratito.</div>';
  function stars(n) { const v = Math.max(0, Math.min(5, Math.round(Number(n) || 0))); return `<span class="vet-stars" role="img" aria-label="${v} de 5 estrellas">${'★'.repeat(v)}<span class="off">${'★'.repeat(5 - v)}</span></span>`; }
  function toMin(t) { const m = /^(\d{1,2}):(\d{2})$/.exec(String(t || '')); return m ? (+m[1]) * 60 + (+m[2]) : null; }
  function nowMx() {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Mexico_City', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date());
    const g = t => (parts.find(p => p.type === t) || {}).value || '';
    return { day: g('weekday').toLowerCase().slice(0, 3), min: ((+g('hour')) % 24) * 60 + (+g('minute')) };
  }
  // Respaldo si el servidor no manda open_now (se calcula en hora de la Ciudad de México)
  function isOpenNow(hours) {
    if (!hours || typeof hours !== 'object' || !Object.keys(hours).length) return null;
    const { day, min } = nowMx();
    const ranges = hours[day];
    if (!Array.isArray(ranges)) return null;
    return ranges.some(r => { const o = toMin(r.open), c = toMin(r.close); if (o == null || c == null) return false; return c > o ? (min >= o && min < c) : (min >= o || min < c); });
  }
  function openBadge(v) {
    if (v.emergency_24h) return '<span class="badge b-green">Abierto 24 h</span>';
    const open = v.open_now != null ? v.open_now : isOpenNow(v.hours);
    return open === true ? '<span class="badge b-green">Abierto ahora</span>' : open === false ? '<span class="badge b-gray">Cerrado ahora</span>' : '';
  }
  function digits(s) { return String(s || '').replace(/\D/g, ''); }
  function waLink(n) { let d = digits(n); if (d.length < 10) return ''; if (d.length === 10) d = '52' + d; return `https://wa.me/${d}`; }
  function webUrl(u) { const s = String(u || '').trim(); if (!s) return ''; return safeUrl(/^https?:\/\//i.test(s) ? s.replace(/^http:/i, 'https:') : 'https://' + s); }
  function monthLabel(ym) {
    const m = /^(\d{4})-(\d{2})$/.exec(String(ym || ''));
    return m ? new Date(+m[1], +m[2] - 1, 1).toLocaleDateString('es-MX', { month: 'long', year: 'numeric' }) : '';
  }
  function thisMonth() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; }
  function hoursList(hours) {
    if (!hours || typeof hours !== 'object' || !Object.keys(hours).length) return '<p class="small muted">Horario no indicado.</p>';
    const today = nowMx().day;
    const range = x => x.open === x.close ? '24 horas' : `${esc(x.open)}–${esc(x.close)}`;  // misma hora = todo el día (backend)
    return `<div class="vet-hours">${DAYS.map(([k, label]) => { const r = Array.isArray(hours[k]) ? hours[k] : []; const cls = k === today ? ' class="today"' : ''; return `<span${cls}>${label}</span><span${cls}>${r.length ? r.map(range).join(', ') : 'Cerrado'}</span>`; }).join('')}</div>`;
  }
  function statusBadge(st) { const [l, c] = STATUS[st] || [st, 'b-yellow']; return `<span class="badge ${c}">${esc(l)}</span>`; }
  // El backend guarda el nombre oficial corto «México» para el Estado de México (data/estados_mx.py)
  function stateLabel(s) { return s === 'México' ? 'Estado de México' : (s || ''); }
  // Ciudad y estado sin repetir («Ciudad de México, Ciudad de México»)
  function place(v, ...extra) {
    const st = stateLabel(v.state);
    return [...extra.slice(0, 1), v.city, st && st !== v.city ? st : '', ...extra.slice(1)].filter(Boolean).join(', ');
  }
  // Catálogos y textos fijos del servidor (GET /veterinaries/meta), pedidos una sola vez
  let metaP = null;
  function meta() {
    if (!metaP) metaP = api('/veterinaries/meta').catch(() => { metaP = null; return {}; });
    return metaP;
  }
  function thumbBox(v) { return `<div class="thumb vet-thumb">${imgTag(photo(v), { alt: '' }) || '<svg width="28" height="28" aria-hidden="true"><use href="#vet"/></svg>'}</div>`; }
  function directionsUrl(v) {
    if (v.latitude == null || v.longitude == null) return '';
    return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(v.latitude + ',' + v.longitude)}`;
  }

  /* ---------- lista ---------- */
  function card(v, i = 0) {
    const sub = [v.city, v.distance_km != null ? dist(v.distance_km) : ''].filter(Boolean).join(' · ');
    return `<div class="card p row tap" role="button" tabindex="0" data-vet="${+v.id}" style="--i:${Math.min(i, 10)}">${thumbBox(v)}
      <div class="grow" style="min-width:0"><b class="ellipsis row" style="gap:5px">${esc(v.name)}${v.status === 'verified' ? ' <svg width="14" height="14" role="img" aria-label="Cédula verificada"><use href="#shield"/></svg>' : ''}</b>
      <div class="small muted ellipsis">${esc(sub)}</div>
      <div class="chips mt8">${openBadge(v)}${v.emergency_24h ? '<span class="badge b-red">Urgencias 24 h</span>' : ''}${v.rating_count ? `<span class="badge">★ ${esc(Number(v.rating_avg || 0).toFixed(1))} (${+v.rating_count})</span>` : ''}</div></div><b aria-hidden="true">→</b></div>`;
  }
  function params(extra = {}) {
    const p = new URLSearchParams();
    if (filters.near && state.coords) { p.set('lat', state.coords.lat); p.set('lon', state.coords.lon); p.set('radius_km', 15); }
    else if (filters.city) p.set('city', filters.city);
    else if (state.coords) { p.set('lat', state.coords.lat); p.set('lon', state.coords.lon); p.set('radius_km', 50); }
    else if (state.city) p.set('city', state.city);
    if (filters.emergency) p.set('emergency', 'true');
    if (filters.q) p.set('q', filters.q);
    Object.entries(extra).forEach(([k, v]) => p.set(k, v));
    return p.toString();
  }
  function paintFilters() {
    $('#vets-sub').textContent = filters.near ? 'A menos de 15 km de ti' : filters.city || (state.coords ? 'Cerca de ti' : state.city) || 'Directorio con cédula verificada';
    [['#vets-near', filters.near], ['#vets-emergency', filters.emergency]].forEach(([s, on]) => { const b = $(s); b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
  }
  async function loadList() {
    const box = $('#vets-list');
    listSkip = 0;
    paintFilters();
    box.innerHTML = FX.skeletonList(4);
    try {
      const items = await api(`/veterinaries?${params({ skip: 0, limit: PAGE })}`);
      listSkip = items.length;
      box.innerHTML = items.length
        ? `<div class="col stagger" id="vets-items">${items.map(card).join('')}</div>${items.length >= PAGE ? '<button type="button" class="btn btn-sm btn-ghost block mt12" id="vets-more">Ver más veterinarias</button>' : ''}`
        : FX.empty('No encontramos veterinarias', filters.q || filters.city || filters.emergency || filters.near ? 'Prueba con otra búsqueda, ciudad o quita los filtros' : 'Aún no hay clínicas verificadas por aquí. ¿Tienes o conoces una? Regístrala gratis', { action: 'vet-register', label: 'Registrar una veterinaria' });
      FX.decorate(box);
      const more = $('#vets-more');
      if (more) more.onclick = () => withBtn(more, async () => {
        const next = await api(`/veterinaries?${params({ skip: listSkip, limit: PAGE })}`);
        const list = $('#vets-items');
        next.forEach((v, i) => list.insertAdjacentHTML('beforeend', card(v, i)));
        listSkip += next.length;
        FX.decorate(list);
        if (next.length < PAGE) more.remove();
      });
    } catch (e) {
      box.innerHTML = missing(e) ? SOON : '';
      if (!missing(e)) toast(e.message, 'error');
    }
  }
  function openList() { navigate('vets'); }

  /* ---------- detalle: bloque de Google Maps ---------- */
  function googleAvatar(r) {
    const src = r.author_photo_url || r.profile_photo_url || '';
    const img = src ? imgTag(src, { thumb: false, alt: '' }) : '';
    return `<div class="avatar" style="width:34px;height:34px;background:var(--sand)">${img || esc(initials(r.author_name))}</div>`;
  }
  function googleReview(r) {
    const author = safeUrl(r.author_url || '');
    const name = esc(r.author_name || 'Usuario de Google Maps');
    const link = (href, inner, extra = '') => href ? `<a href="${esc(href)}" target="_blank" rel="noopener"${extra}>${inner}</a>` : inner;
    const translated = r.original_text && r.text && r.original_text !== r.text;
    const own = safeUrl(r.google_maps_url || '');
    const flag = safeUrl(r.flag_content_url || '');
    return `<article class="g-review"><div class="row">${link(author, googleAvatar(r), ' aria-label="Perfil de ' + name + ' en Google Maps"')}
        <div class="grow" style="min-width:0"><b class="small">${link(author, name, ' class="link"')}</b><div class="small muted">${stars(r.rating)} · ${esc(r.relative_time || '')}</div></div></div>
      ${r.text ? `<p class="small mt8 g-text">${esc(r.text)}</p>` : ''}
      ${translated ? `<details class="small mt8"><summary class="muted">Traducida por Google · Ver texto original</summary><p class="g-text mt8">${esc(r.original_text)}</p></details>` : ''}
      ${own || flag ? `<div class="g-links mt8">${own ? `<a class="link small" href="${esc(own)}" target="_blank" rel="noopener">Ver en Google Maps</a>` : ''}${flag ? `<a class="link small" href="${esc(flag)}" target="_blank" rel="noopener">Reportar a Google</a>` : ''}</div>` : ''}
    </article>`;
  }
  // Bloque «Reseñas de Google Maps»: separado del bloque propio, atribución con el logotipo oficial,
  // hasta 5 reseñas tal cual las entrega Google (sin recortar ni reordenar) y enlaces a Google Maps.
  function googleBlock(g, v) {
    // Términos de Google Maps Platform (veterinarias.html §9): el contenido de Google nunca va en una vista con el
    // mapa de OpenStreetMap (Leaflet). El detalle de la clínica no lleva mapa; si algún día lo lleva, no se muestra.
    if (!g || $('#vet-body .leaflet-container') || current === 'map') return '';
    const url = safeUrl(g.maps_url || g.google_maps_url || v.google_maps_url || '');
    const reviews = (Array.isArray(g.reviews) ? g.reviews : []).slice(0, 5);
    const rating = g.rating != null ? g.rating : null;
    const total = g.ratings_total != null ? g.ratings_total : null;
    const head = `<div class="gm-head">${GM_LOGO}${rating != null ? `<span class="badge b-yellow">★ ${esc(Number(rating).toFixed(1))}${total != null ? ` · ${esc(Number(total).toLocaleString('es-MX'))} calificaciones` : ''}</span>` : ''}</div>`;
    const all = url ? `<a class="btn btn-sm btn-ghost block mt12" href="${esc(url)}" target="_blank" rel="noopener">Ver todas las reseñas en Google Maps</a>` : '';
    if (g.available === false) {
      return `<section class="card mt16 gplaces" aria-labelledby="gm-title">${head}<div class="gm-body"><b class="small" id="gm-title">Reseñas de <span translate="no">Google Maps</span></b>
        <p class="small muted mt8">No pudimos consultar Google Maps en este momento. Inténtalo más tarde.</p>${all}</div></section>`;
    }
    return `<section class="card mt16 gplaces" aria-labelledby="gm-title">${head}
      <div class="gm-body"><b class="small" id="gm-title">Reseñas de <span translate="no">Google Maps</span></b>
      <p class="small muted mt8">${esc(g.order_notice || GOOGLE_ORDER)} Estas reseñas no se suman a las opiniones de GuauWoow. <a class="link" href="${GOOGLE_POLICY_URL}" target="_blank" rel="noopener">Política de contenido de Google Maps</a></p>
      <div class="col mt12">${reviews.length ? reviews.map(googleReview).join('') : '<p class="small muted">Google Maps no devolvió reseñas para esta clínica.</p>'}</div>
      ${all}</div>
    </section>`;
  }

  /* ---------- detalle: reseñas propias ---------- */
  function reviewRow(r) {
    const u = r.user || { full_name: r.user_name || 'Usuario' };
    const mine = !!r.mine;  // el servidor ya no expone ids de cuenta en las reseñas públicas
    const owner = !!(detail && detail.is_owner);
    const edited = r.updated_at && r.created_at && Math.abs(new Date(r.updated_at) - new Date(r.created_at)) > 60000;
    const visited = monthLabel(r.visited_month);
    return `<article class="card p vet-review" data-review="${+r.id}"><div class="row">${avatarHtml(u, 36)}
      <div class="grow" style="min-width:0"><b class="small ellipsis">${esc(u.full_name || 'Usuario')}${mine ? ' (tú)' : ''}</b><div class="small muted">${stars(r.rating)} · ${timeAgo(r.created_at)}${edited ? ' · editada' : ''}</div></div>
      ${!mine && !owner && state.me ? `<button type="button" class="iconbtn sm" data-flag-review="${+r.id}" data-author="${esc(u.full_name || '')}" title="Reportar reseña" aria-label="Reportar reseña"><svg width="14" height="14" aria-hidden="true"><use href="#flag"/></svg></button>` : ''}</div>
      ${visited || r.incentivized ? `<div class="chips mt8">${visited ? `<span class="badge">Visita: ${esc(visited)}</span>` : ''}${r.incentivized ? '<span class="badge b-orange" title="La persona recibió un descuento o regalo de la clínica">Reseña incentivada</span>' : ''}</div>` : ''}
      ${r.is_hidden && mine ? '<div class="small muted mt8">🙈 Esta reseña está oculta por moderación; solo tú la ves.</div>' : ''}
      ${r.text ? `<p class="small mt8 g-text">${esc(r.text)}</p>` : ''}
      ${r.owner_reply ? `<div class="vet-reply mt8"><b class="small">Respuesta de la clínica</b>${r.owner_reply_at ? ` <span class="small muted">· ${timeAgo(r.owner_reply_at)}</span>` : ''}<p class="small g-text">${esc(r.owner_reply)}</p></div>` : ''}
      ${r.clarification ? `<div class="vet-reply vet-clar mt8"><b class="small">Aclaración publicada a solicitud de una persona aludida o de la clínica</b>${r.clarification_at ? ` <span class="small muted">· ${timeAgo(r.clarification_at)}</span>` : ''}<p class="small g-text">${esc(r.clarification)}</p></div>` : ''}
      ${owner && detail.status === 'verified' ? `<div class="row mt8" style="gap:14px;flex-wrap:wrap"><button type="button" class="link small" data-reply="${+r.id}" data-reply-text="${esc(r.owner_reply || '')}">${r.owner_reply ? 'Editar respuesta' : 'Responder públicamente'}</button>${r.owner_reply ? `<button type="button" class="link small" data-reply-del="${+r.id}">Borrar respuesta</button>` : ''}${r.clarification ? '' : `<button type="button" class="link small" data-clarify="${+r.id}">Solicitar aclaración</button>`}</div>`
        : !mine && state.me && !r.clarification ? `<div class="row mt8"><button type="button" class="link small muted" data-clarify="${+r.id}">¿Te mencionan? Solicitar aclaración</button></div>` : ''}
    </article>`;
  }
  function starsInput(rating) {
    return `<div class="stars" role="radiogroup" aria-labelledby="vr-lbl" aria-required="true" id="vr-stars">${[1, 2, 3, 4, 5].map(n => `<button type="button" class="star ${n <= rating ? 'on' : ''}" role="radio" aria-checked="${n === rating ? 'true' : 'false'}" tabindex="${n === (rating || 1) ? '0' : '-1'}" data-star="${n}" aria-label="${n} estrella${n > 1 ? 's' : ''}">★</button>`).join('')}</div>`;
  }
  function reviewForm(own) {
    return `<form id="vet-review-form" class="mt12 vet-review-form" novalidate>
      <span class="lbl" id="vr-lbl">${own ? 'Tu reseña' : 'Califica tu experiencia'}</span>
      ${own && own.is_hidden ? '<p class="small vet-tip mb8" role="status">🛡️ Tu reseña está en revisión: nuestro equipo la revisa antes de publicarla. Solo tú la ves.</p>' : ''}
      ${starsInput(own ? own.rating : 0)}
      <label class="lbl mt8" for="vr-text">Cuéntanos (opcional)</label>
      <textarea id="vr-text" class="inp" rows="3" maxlength="1000" placeholder="¿Cómo atendieron a tu perrito?">${own ? esc(own.text || '') : ''}</textarea>
      <div class="row mt8" style="flex-wrap:wrap"><label class="lbl" for="vr-month" style="margin:0">¿Cuándo fuiste?</label><input id="vr-month" class="inp grow" type="month" max="${thisMonth()}" value="${own && own.visited_month ? esc(own.visited_month) : ''}" style="min-width:150px"></div>
      <label class="row small mt8" style="align-items:flex-start"><input type="checkbox" id="vr-incentive" ${own && own.incentivized ? 'checked' : ''} style="width:20px;height:20px;flex-shrink:0;margin-top:2px"> <span>Recibí un descuento o regalo de la clínica por opinar (se mostrará «Reseña incentivada»).</span></label>
      <p class="small muted mt8">Opina solo sobre tu propia experiencia de los últimos 12 meses: nada de acusaciones de delitos, insultos ni datos de otras personas. Puedes editarla o borrarla cuando quieras.</p>
      <div class="row mt8"><button type="submit" class="btn btn-sm btn-orange grow" id="vr-submit">${own ? 'Guardar cambios' : 'Publicar reseña'}</button>${own ? '<button type="button" class="btn btn-sm btn-ghost" id="vr-delete">Eliminar</button>' : ''}</div>
    </form>`;
  }

  /* ---------- detalle ---------- */
  async function open(id, nav = {}) {
    const body = $('#vet-body');
    body.innerHTML = `<div class="skel" style="height:200px"><i class="skel-paw">${FX.PAW}</i></div>${FX.skeletonList(3)}`;
    $('#vet-flag').classList.add('hidden');
    $('#vet-share').classList.add('hidden');
    navigate('vet', nav);
    let v;
    try { v = await api(`/veterinaries/${encodeURIComponent(id)}`); }
    catch (e) { body.innerHTML = missing(e) ? SOON : ''; if (!missing(e)) { toast(e.message, 'error'); back(); } return; }
    detail = v;
    const notices = v.notices || {};
    const mine = !!v.is_owner;
    $('#vet-flag').classList.toggle('hidden', !state.me || mine);
    $('#vet-share').classList.toggle('hidden', v.status !== 'verified');
    $('#vet-title').firstChild.textContent = v.name || 'Veterinaria';
    const photos = Array.isArray(v.photos) ? v.photos.filter(p => safeUrl(p)) : [];
    const tel = digits(v.phone);
    const wa = waLink(v.whatsapp || v.phone);
    const web = webUrl(v.website);
    const mail = /^[^\s@<>"']+@[^\s@<>"']+\.[^\s@<>"']+$/.test(v.email || '') ? v.email : '';
    const reviews = Array.isArray(v.reviews) ? v.reviews : (Array.isArray(v.latest_reviews) ? v.latest_reviews : []);
    const own = v.my_review || reviews.find(r => r.mine) || null;
    const count = v.rating_count != null ? +v.rating_count : reviews.length;
    reviewsShown = reviews.length;
    const addr = place(v, v.address, v.postal_code ? `C.P. ${v.postal_code}` : '');
    const dir = directionsUrl(v);
    const verifiedLine = v.verified_label || `Cédula consultada en el Registro Nacional de Profesionistas${v.verified_at ? ` el ${fmtDate(v.verified_at)}` : ''}`;
    body.innerHTML = `
      ${photos.length ? `<div class="gallery pop-in" style="height:210px"><div class="track">${photos.map(p => `<div>${imgTag(p, { thumb: false, alt: v.name })}</div>`).join('')}</div></div>${photos.length > 1 ? `<p class="small muted center mt8">← Desliza para ver ${photos.length} fotos →</p>` : ''}` : `<div class="card center pop-in" style="padding:22px;background:var(--yellow)"><svg width="64" height="64" aria-hidden="true"><use href="#vet"/></svg></div>`}
      <div class="between mt16" style="align-items:flex-start"><div class="grow" style="min-width:0"><h1 class="h1">${esc(v.name)}</h1><div class="small muted row" style="gap:4px"><svg width="13" height="13" aria-hidden="true"><use href="#pin"/></svg>${esc(place(v))}${v.distance_km != null ? ' · ' + dist(v.distance_km) : ''}</div></div>${openBadge(v)}</div>
      <div class="chips mt8">${v.status === 'verified' ? `<button type="button" class="badge b-green cedula-badge" id="vet-badge" aria-expanded="false" aria-controls="vet-badge-tip"><svg width="13" height="13" aria-hidden="true"><use href="#shield"/></svg> Cédula verificada ⓘ</button>` : statusBadge(v.status)}${v.emergency_24h ? '<span class="badge b-red">Urgencias 24 h</span>' : ''}${count ? `<span class="badge">★ ${esc(Number(v.rating_avg || 0).toFixed(1))} · ${count} opini${count === 1 ? 'ón' : 'ones'}</span>` : ''}</div>
      <p class="small vet-tip mt8 hidden" id="vet-badge-tip">${esc(v.badge_text || BADGE_TIP)}</p>
      ${mine && v.is_hidden ? HIDDEN_NOTE : ''}
      <div class="vet-contact mt16">
        ${tel ? `<a class="btn btn-sm" href="tel:${esc(tel)}">📞 Llamar</a>` : '<button type="button" class="btn btn-sm btn-ghost" disabled>📞 Sin teléfono</button>'}
        ${wa ? `<a class="btn btn-sm btn-green" href="${esc(wa)}" target="_blank" rel="noopener">💬 WhatsApp</a>` : '<button type="button" class="btn btn-sm btn-ghost" disabled>💬 Sin WhatsApp</button>'}
        ${web ? `<a class="btn btn-sm btn-lila" href="${esc(web)}" target="_blank" rel="noopener nofollow">🌐 Sitio web</a>` : '<button type="button" class="btn btn-sm btn-ghost" disabled>🌐 Sin sitio</button>'}
      </div>
      <div class="vet-notice mt12" role="note">⚠️ ${esc(notices.emergency || EMERGENCY_NOTE)}</div>
      <div class="card p mt16"><div class="small muted vet-k">DIRECCIÓN</div><p class="body mt8">${esc(addr || 'Sin dirección')}</p>
        ${dir ? `<a class="link small" href="${esc(dir)}" target="_blank" rel="noopener">Cómo llegar →</a>` : ''}
        ${mail ? `<p class="small mt8">Correo: <a class="link" href="mailto:${esc(mail)}">${esc(mail)}</a></p>` : ''}</div>
      <div class="card p mt12"><div class="small muted vet-k">HORARIO <span style="font-weight:600">(hora local)</span></div><div class="mt8">${hoursList(v.hours)}</div></div>
      ${Array.isArray(v.services) && v.services.length ? `<div class="card p mt12"><div class="small muted vet-k">SERVICIOS <span style="font-weight:600">(declarados por la clínica)</span></div><div class="chips mt8">${v.services.map(s => `<span class="badge b-blue">${esc(s)}</span>`).join('')}</div></div>` : ''}
      ${v.description ? `<div class="card p mt12"><div class="small muted vet-k">SOBRE LA CLÍNICA</div><p class="body mt8" style="white-space:pre-line">${esc(v.description)}</p></div>` : ''}
      ${v.responsible_vet_name ? `<div class="card p mt12 row" style="align-items:flex-start"><div class="avatar" style="background:var(--green)" aria-hidden="true">🩺</div><div class="grow" style="min-width:0"><b>${esc(v.responsible_vet_name)}</b><div class="small muted">Médico veterinario responsable${v.cedula_profesional ? ` · Cédula profesional ${esc(v.cedula_profesional)}` : ''}${v.cedula_institution ? ` · ${esc(v.cedula_institution)}` : ''}</div>${v.status === 'verified' ? `<div class="small muted mt8">${esc(verifiedLine)}.</div>` : ''}</div></div>` : ''}
      <section class="card p mt16" aria-labelledby="vet-own-title"><div class="between"><b id="vet-own-title">Opiniones en GuauWoow</b>${count ? `<span class="badge b-yellow">★ ${esc(Number(v.rating_avg || 0).toFixed(1))} · ${count}</span>` : ''}</div>
        <p class="small muted mt8">${esc(notices.reviews || 'Reseñas de personas con teléfono verificado, una por cuenta, de la más reciente a la más antigua. La clínica no puede editarlas ni ocultarlas, solo responderlas.')}</p>
        ${mine ? '<p class="small muted mt8">No puedes reseñar tu propia clínica.</p>' : state.me && v.status === 'verified' ? reviewForm(own) : ''}
        ${count > 1 ? `<div class="row mt12"><label class="small muted" for="vet-order" style="font-weight:800">Ordenar</label><select id="vet-order" class="inp grow vet-order"><option value="recent">Más recientes</option><option value="oldest">Más antiguas</option><option value="highest">Calificación más alta</option><option value="lowest">Calificación más baja</option></select></div>` : ''}
        <div class="col mt12" id="vet-reviews">${reviews.length ? reviews.map(reviewRow).join('') : '<p class="small muted">Aún no hay opiniones. ¿Ya la visitaste? Sé la primera persona en opinar.</p>'}</div>
        ${count > reviews.length ? '<button type="button" class="link small mt12" id="vet-more">Ver más reseñas</button>' : ''}</section>
      ${googleBlock(v.google, v)}
      <p class="small muted mt16">${esc(notices.disclaimer || DISCLAIMER)} <a class="link" href="/app/legal/terminos.html" id="vet-legal" target="_blank" rel="noopener">Más información</a></p>
      ${notices.complaints ? `<p class="small muted mt8">${esc(notices.complaints)}</p>` : ''}
      ${v.status === 'verified' && !mine && state.me ? `<div class="card p mt12"><div class="row" style="flex-wrap:wrap;gap:8px"><b class="small grow">¿Algo no está bien con esta clínica?</b><button type="button" class="btn btn-sm btn-ghost" data-vet-complaint>Presentar una queja</button></div></div>` : ''}
      <p class="small muted mt8">¿Alguien sin cuenta en GuauWoow necesita aclarar o reportar algo de esta clínica o de una reseña? Comparte el <a class="link" href="${PUBLIC_FORM}?vet=${+v.id}" target="_blank" rel="noopener">formulario público</a>.</p>`;
    FX.decorate(body);
    legalUrl().then(u => { const a = $('#vet-legal'); if (a) a.href = u; });
    bindDetail(v, own);
  }
  function bindStars(onChange, initial) {
    let rating = initial || 0;
    const starsEl = $$('#vr-stars .star');
    const paint = () => starsEl.forEach(s => {
      const n = +s.dataset.star;
      s.classList.toggle('on', n <= rating);
      s.setAttribute('aria-checked', String(n === rating));
      s.tabIndex = n === (rating || 1) ? 0 : -1;
    });
    starsEl.forEach(s => {
      s.addEventListener('click', () => { rating = +s.dataset.star; paint(); onChange(rating); });
      s.addEventListener('keydown', e => {
        const k = e.key;
        if (!['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(k)) return;
        e.preventDefault();
        rating = k === 'Home' ? 1 : k === 'End' ? 5 : Math.min(5, Math.max(1, (rating || 0) + (k === 'ArrowRight' || k === 'ArrowUp' ? 1 : -1)));
        paint(); onChange(rating); starsEl[rating - 1].focus();
      });
    });
  }
  function bindDetail(v, own) {
    const badge = $('#vet-badge');
    if (badge) badge.onclick = () => { const tip = $('#vet-badge-tip'); const show = tip.classList.contains('hidden'); tip.classList.toggle('hidden', !show); badge.setAttribute('aria-expanded', String(show)); };
    const form = $('#vet-review-form');
    if (form) {
      let rating = own ? own.rating : 0;
      bindStars(r => { rating = r; }, rating);
      form.addEventListener('submit', e => {
        e.preventDefault();
        if (!rating) { toast('Elige de 1 a 5 estrellas', 'error'); return $('#vr-stars .star').focus(); }
        const text = $('#vr-text').value.trim();
        const month = $('#vr-month').value;
        if (month && month > thisMonth()) return toast('La fecha de tu visita no puede ser futura', 'error');
        withBtn($('#vr-submit'), async () => {
          await api(`/veterinaries/${v.id}/reviews`, { method: 'POST', body: { rating, text: text || null, visited_month: month || null, incentivized: $('#vr-incentive').checked } });
          toast(own ? 'Reseña actualizada' : '¡Gracias por tu opinión! 🐾', 'ok');
          track('veterinary_reviewed', { rating });
          open(v.id, { push: false });
        });
      });
      const del = $('#vr-delete');
      if (del) del.onclick = () => withBtn(del, async () => {
        if (!confirm('¿Eliminar tu reseña? No se puede deshacer.')) return;
        await api(`/veterinaries/${v.id}/reviews/me`, { method: 'DELETE' });
        toast('Reseña eliminada');
        open(v.id, { push: false });
      });
    }
    // Orden de las reseñas: cronológico por defecto, con selector (lo resuelve el servidor)
    let order = 'recent';
    const more = $('#vet-more');
    if (more) more.onclick = () => withBtn(more, async () => {
      const rs = await api(`/veterinaries/${v.id}/reviews?order=${order}&skip=${reviewsShown}&limit=10`);
      const box = $('#vet-reviews');
      rs.forEach(r => box.insertAdjacentHTML('beforeend', reviewRow(r)));
      reviewsShown += rs.length;
      FX.decorate(box);
      if (rs.length < 10) more.classList.add('hidden');
    });
    const sel = $('#vet-order');
    if (sel) sel.onchange = async () => {
      order = sel.value;
      const box = $('#vet-reviews');
      box.innerHTML = FX.skeletonList(2);
      try {
        const rs = await api(`/veterinaries/${v.id}/reviews?order=${order}&skip=0&limit=10`);
        box.innerHTML = rs.map(reviewRow).join('');
        reviewsShown = rs.length;
        if (more) more.classList.toggle('hidden', rs.length < 10);
        FX.decorate(box);
      } catch (e) { toast(e.message, 'error'); }
    };
  }
  // Respuesta pública de la clínica verificada (una por reseña, mismas reglas de contenido)
  function openReply(btn) {
    const row = btn.closest('[data-review]');
    if (!row || $('.vet-reply-form', row)) return;
    btn.insertAdjacentHTML('afterend', `<form class="vet-reply-form col mt8" novalidate><label class="lbl" for="vrp-${row.dataset.review}">Tu respuesta pública</label>
      <textarea id="vrp-${row.dataset.review}" class="inp" rows="3" maxlength="1000" placeholder="Agradece o aclara con respeto. Sin datos personales del cliente."></textarea>
      <div class="row"><button type="submit" class="btn btn-sm grow">Publicar respuesta</button><button type="button" class="btn btn-sm btn-ghost" data-cancel>Cancelar</button></div></form>`);
    btn.classList.add('hidden');
    const f = $('.vet-reply-form', row);
    $('textarea', f).value = btn.dataset.replyText || '';
    $('textarea', f).focus();
    $('[data-cancel]', f).onclick = () => { f.remove(); btn.classList.remove('hidden'); };
    f.addEventListener('submit', e => {
      e.preventDefault();
      const text = $('textarea', f).value.trim();
      if (!text) return toast('Escribe tu respuesta', 'error');
      withBtn($('button[type=submit]', f), async () => {
        try { await api(`/veterinaries/${detail.id}/reviews/${row.dataset.review}/reply`, { method: 'POST', body: { text } }); }
        catch (err) { if (err.status === 404 && missing(err) || err.status === 405) throw new Error('Las respuestas a reseñas se activarán muy pronto'); throw err; }
        toast('Respuesta publicada', 'ok');
        open(detail.id, { push: false });
      });
    });
  }

  function deleteReply(btn) {
    withBtn(btn, async () => {
      if (!confirm('¿Borrar tu respuesta pública a esta reseña?')) return;
      await api(`/veterinaries/${detail.id}/reviews/${btn.dataset.replyDel}/reply`, { method: 'DELETE' });
      toast('Respuesta borrada');
      open(detail.id, { push: false });
    });
  }

  /* ---------- aclaraciones y quejas (POST /veterinaries/{id}/requests) ---------- */
  // Aclaración: la clínica o una persona aludida en una reseña; si procede se publica sin comentarios (5 días hábiles).
  // Queja: sobre la clínica o una reseña; el equipo la revisa en 72 horas hábiles. Sin cuenta: veterinarias-solicitud.html
  function requestForm(kind, reviewId) {
    const owner = !!(detail && detail.is_owner);
    const fid = `vrq-${kind}-${reviewId || 'vet'}`;
    const relation = owner ? '' : `<label class="lbl" for="${fid}-rel">¿Quién eres?</label><select id="${fid}-rel" class="inp" data-rel>
        ${kind === 'aclaracion' ? '<option value="aludido">Me mencionan en la reseña</option>' : '<option value="cliente">Fui cliente de la clínica</option><option value="aludido">Me mencionan en una reseña</option>'}<option value="otro">Otra relación</option></select>`;
    const reason = kind === 'queja' ? `<label class="lbl" for="${fid}-why">Motivo</label><select id="${fid}-why" class="inp" data-why>${REQUEST_REASONS.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('')}</select>` : '';
    const hint = kind === 'aclaracion'
      ? 'Escribe la aclaración tal como quieres que se publique junto a la reseña (sin teléfonos, correos ni datos de otras personas). Nuestro equipo la revisa en un máximo de 5 días hábiles y, si procede, la publica sin comentarios.'
      : 'Cuéntanos qué pasó. Solo la ve nuestro equipo y te respondemos en un máximo de 72 horas hábiles (3 días hábiles).';
    return `<form class="vet-request-form col mt8" data-kind="${kind}" data-review-id="${reviewId || ''}" novalidate>
      <b class="small">${kind === 'aclaracion' ? 'Solicitar aclaración' : 'Presentar una queja'}</b>
      ${relation}${reason}
      <label class="lbl" for="${fid}-txt">${kind === 'aclaracion' ? 'Tu aclaración' : 'Detalles'}</label>
      <textarea id="${fid}-txt" class="inp" rows="4" minlength="10" maxlength="2000" data-txt></textarea>
      <p class="small muted">${hint}</p>
      <div class="row"><button type="submit" class="btn btn-sm grow">Enviar</button><button type="button" class="btn btn-sm btn-ghost" data-cancel>Cancelar</button></div></form>`;
  }
  function openRequest(btn, kind, reviewId) {
    const host = btn.parentElement;
    if (!host || $('.vet-request-form', host.parentElement)) return;
    host.insertAdjacentHTML('afterend', requestForm(kind, reviewId));
    const f = host.nextElementSibling;
    btn.classList.add('hidden');
    $('[data-txt]', f).focus();
    $('[data-cancel]', f).onclick = () => { f.remove(); btn.classList.remove('hidden'); };
    f.addEventListener('submit', e => {
      e.preventDefault();
      const text = $('[data-txt]', f).value.trim();
      if (text.length < 10) return toast('Cuéntanos con más detalle (mínimo 10 caracteres)', 'error');
      const rel = $('[data-rel]', f), why = $('[data-why]', f);
      withBtn($('button[type=submit]', f), async () => {
        const r = await api(`/veterinaries/${detail.id}/requests`, { method: 'POST', body: {
          kind, review_id: reviewId ? +reviewId : null, relation: rel ? rel.value : 'clinica', reason: why ? why.value : null, text,
        } });
        f.remove(); btn.classList.remove('hidden');
        toast(`Recibimos tu solicitud (folio ${+r.id}). Te responderemos a más tardar el ${fmtDate(r.due_at)}`, 'ok');
        track('veterinary_request', { kind });
      });
    });
  }

  /* ---------- formulario de registro / edición ---------- */
  // Horario: cada día admite hasta 4 rangos (turnos partidos, p. ej. 09:00–14:00 y 16:00–20:00), igual que el backend
  const MAX_RANGES = 4;
  function rangeRow([, label, short], i, r, closed) {
    const n = i ? ` (horario ${i + 1})` : '';
    return `<div class="hours-row ${closed ? 'off' : ''}" data-range>${i === 0 ? `<span title="${label}">${short}</span>` : '<span aria-hidden="true"></span>'}
        <input class="inp" type="time" data-open value="${esc(r.open || '')}" aria-label="${label}: abre${n}" ${closed ? 'disabled' : ''}>
        <span aria-hidden="true">a</span>
        <input class="inp" type="time" data-close value="${esc(r.close || '')}" aria-label="${label}: cierra${n}" ${closed ? 'disabled' : ''}>
        ${i === 0 ? `<label class="small row hours-closed"><input type="checkbox" data-closed ${closed ? 'checked' : ''} aria-label="${label}: cerrado"> Cerrado</label>`
          : `<button type="button" class="iconbtn sm hours-rm" data-rm-range aria-label="Quitar el horario ${i + 1} del ${label.toLowerCase()}" ${closed ? 'disabled' : ''}>×</button>`}</div>`;
  }
  function dayHtml(def, ranges, closed) {
    const list = (ranges.length ? ranges : [{ open: '09:00', close: '19:00' }]).slice(0, MAX_RANGES);
    return `<div class="hours-day" data-day="${def[0]}">${list.map((r, i) => rangeRow(def, i, r, closed)).join('')}
      <button type="button" class="link small hours-add ${closed || list.length >= MAX_RANGES ? 'hidden' : ''}" data-add-range aria-label="Agregar otro horario el ${def[1].toLowerCase()}">+ Agregar horario</button></div>`;
  }
  function hoursEditor(hours) {
    const empty = !hours || !Object.keys(hours).length;
    return DAYS.map(def => {
      // Al editar se conservan todos los rangos guardados (antes solo se leía el primero)
      const ranges = !empty && Array.isArray(hours[def[0]]) ? hours[def[0]].filter(r => r && r.open && r.close) : [];
      return dayHtml(def, ranges, empty ? def[0] === 'sun' : !ranges.length);
    }).join('');
  }
  function readDay(day) {
    return {
      closed: $('[data-closed]', day).checked,
      ranges: $$('[data-range]', day).map(row => ({ open: $('[data-open]', row).value, close: $('[data-close]', row).value })),
    };
  }
  function setClosed(day, closed) {
    $$('[data-range]', day).forEach(row => {
      row.classList.toggle('off', closed);
      $$('input[type=time], [data-rm-range]', row).forEach(i => { i.disabled = closed; });
    });
    $('[data-add-range]', day).classList.toggle('hidden', closed || $$('[data-range]', day).length >= MAX_RANGES);
  }
  function bindHours() {
    const box = $('#vf-hours');
    box.addEventListener('change', e => { if (e.target.matches('[data-closed]')) setClosed(e.target.closest('.hours-day'), e.target.checked); });
    box.addEventListener('click', e => {
      const add = e.target.closest('[data-add-range]'), rm = e.target.closest('[data-rm-range]');
      if (add) {
        const day = add.closest('.hours-day');
        const rows = $$('[data-range]', day);
        if (rows.length >= MAX_RANGES) return;
        add.insertAdjacentHTML('beforebegin', rangeRow(DAYS.find(d => d[0] === day.dataset.day), rows.length, {}, false));
        add.classList.toggle('hidden', rows.length + 1 >= MAX_RANGES);
        $$('[data-range]', day).slice(-1)[0].querySelector('[data-open]').focus();
      } else if (rm) {
        const day = rm.closest('.hours-day');
        rm.closest('[data-range]').remove();
        $('[data-add-range]', day).classList.remove('hidden');
      }
    });
  }
  function copyMonday() {
    const mon = readDay($('#vf-hours [data-day="mon"]'));
    const ranges = mon.ranges.filter(r => r.open && r.close);
    $$('#vf-hours .hours-day').forEach(day => {
      const k = day.dataset.day;
      if (k === 'sun' || k === 'mon') return;
      day.outerHTML = dayHtml(DAYS.find(d => d[0] === k), ranges, mon.closed);
    });
    toast('Copiamos el horario del lunes de martes a sábado', 'ok');
  }
  function readHours() {
    const out = {};
    $$('#vf-hours .hours-day').forEach(day => {
      const { closed, ranges } = readDay(day);
      out[day.dataset.day] = closed ? [] : ranges.filter(r => r.open && r.close);
    });
    return out;
  }
  function renderCedulaBox() {
    const box = $('#vf-cedula-box');
    const f = cedulaFile;
    // Tras verificarla, la imagen de la cédula se borra a los 30 días (queda la constancia del cotejo)
    const purged = editing && !editing.cedula_document_id && editing.cedula_document_purged_at;
    const sent = editing && (editing.cedula_document_id || purged);
    box.innerHTML = (f ? `<div class="doc-item"><div class="doc-ic">${f.type === 'application/pdf' || /\.pdf$/i.test(f.name || '') ? 'PDF' : `<img src="${URL.createObjectURL(f)}" alt="">`}</div><span class="grow ellipsis">${esc(f.name || 'Cédula')}</span><button type="button" id="vf-cedula-rm" aria-label="Quitar cédula">×</button></div>`
      : purged ? '<div class="doc-item"><div class="doc-ic">✓</div><span class="grow">Cédula verificada. Por tu privacidad ya borramos la imagen; súbela de nuevo solo si cambian sus datos.</span></div>'
      : sent ? '<div class="doc-item"><div class="doc-ic">✓</div><span class="grow">Cédula ya enviada. Sube otra solo si cambió.</span></div>' : '')
      + `<button type="button" class="btn btn-sm btn-ghost doc-add" id="vf-cedula-add"><svg width="16" height="16" aria-hidden="true"><use href="#plus"/></svg> ${f || sent ? 'Cambiar cédula' : 'Subir cédula (foto o PDF)'}</button>`;
    $('#vf-cedula-add').onclick = () => $('#vf-cedula-file').click();
    const rm = $('#vf-cedula-rm'); if (rm) rm.onclick = () => { cedulaFile = null; renderCedulaBox(); };
  }
  function renderKeepPhotos() {
    const box = $('#vf-keep-photos');
    box.classList.toggle('hidden', !keepPhotos.length);
    box.innerHTML = keepPhotos.map((p, i) => `<div class="photo-prev">${imgTag(p, { alt: '' })}<button type="button" data-keep-rm="${i}" aria-label="Quitar foto">×</button></div>`).join('');
    $$('[data-keep-rm]', box).forEach(b => b.onclick = () => { keepPhotos.splice(+b.dataset.keepRm, 1); renderKeepPhotos(); });
  }
  function openForm(v = null) {
    if (!state.me) return toast('Inicia sesión para registrar una veterinaria', 'error');
    editing = v; cedulaFile = null; keepPhotos = v && Array.isArray(v.photos) ? v.photos.filter(p => safeUrl(p)) : [];
    $('#vf-title').firstChild.textContent = v ? 'Editar mi veterinaria' : 'Registrar veterinaria';
    $('#vf-state').innerHTML = '<option value="">Elige el estado</option>' + STATES.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
    const has = s => !!(v && Array.isArray(v.services) && v.services.includes(s));
    $('#vf-services').innerHTML = SERVICES.map(s => `<button type="button" class="chip ${has(s) ? 'on' : ''}" data-service="${esc(s)}" aria-pressed="${has(s)}">${esc(s)}</button>`).join('');
    $$('#vf-services .chip').forEach(c => c.onclick = () => { c.classList.toggle('on'); c.setAttribute('aria-pressed', String(c.classList.contains('on'))); });
    $('#vf-hours').innerHTML = hoursEditor(v ? v.hours : null);
    // Antes de llenar los campos: resetLoc('vf') también vacía #vf-state (Compartir.clearGeo usa <clave>-state)
    clearPhotos('vf');
    resetLoc('vf');
    const set = (id, val) => { $(id).value = val == null ? '' : val; };
    set('#vf-name', v && v.name); set('#vf-desc', v && v.description); set('#vf-address', v && v.address);
    set('#vf-city', v ? v.city : (state.me && state.me.city) || '');
    set('#vf-state', v ? stateLabel(v.state) : (typeof Compartir !== 'undefined' && Compartir.guessState ? Compartir.guessState(state.me && state.me.city) || '' : ''));
    set('#vf-cp', v && v.postal_code); set('#vf-phone', v && v.phone); set('#vf-wa', v && v.whatsapp); set('#vf-email', v && v.email); set('#vf-web', v && v.website);
    set('#vf-vet', v && v.responsible_vet_name); set('#vf-cedula', v && v.cedula_profesional); set('#vf-institution', v && v.cedula_institution);
    $('#vf-24h').checked = !!(v && v.emergency_24h);
    $('#vf-consent').checked = !!v;
    $('#vf-pending-note').classList.toggle('hidden', !v);
    if (v && v.latitude != null && v.longitude != null) {
      locStore.vf = { lat: v.latitude, lon: v.longitude };
      $('[data-loc="vf"]').classList.add('ok');
      $('[data-loc="vf"] [data-loc-text]').textContent = '📍 Ubicación guardada';
    }
    renderKeepPhotos();
    renderCedulaBox();
    $('#vf-submit').textContent = v ? 'Guardar cambios' : 'Enviar para verificación';
    navigate('vet-form');
    $('#vet-form').scrollTop = 0;
  }
  // Ubica la dirección escrita (Nominatim, mismo proveedor que la geocodificación inversa de la app)
  async function geocodeAddress() {
    if (!$('#vf-address').value.trim() || !$('#vf-city').value.trim()) throw new Error('Escribe la calle y la ciudad para ubicarla');
    const q = [$('#vf-address').value, $('#vf-cp').value, $('#vf-city').value, $('#vf-state').value, 'México'].map(s => String(s || '').trim()).filter(Boolean).join(', ');
    let d;
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=mx&accept-language=es&q=${encodeURIComponent(q)}`);
      d = await r.json();
    } catch { throw new Error('No pudimos consultar el mapa. Usa «Ubicar» estando dentro de la clínica'); }
    if (!Array.isArray(d) || !d.length) throw new Error('No encontramos esa dirección. Revísala o usa «Ubicar» dentro de la clínica');
    locStore.vf = { lat: +(+d[0].lat).toFixed(6), lon: +(+d[0].lon).toFixed(6) };
    $('[data-loc="vf"]').classList.add('ok');
    $('[data-loc="vf"] [data-loc-text]').textContent = '📍 Dirección ubicada en el mapa';
    toast('Dirección ubicada', 'ok');
  }
  // Devuelve [mensaje, selector del campo] o null si todo está bien
  function validateForm() {
    const val = id => $(id).value.trim();
    if (val('#vf-name').length < 3) return ['Escribe el nombre de la clínica (mínimo 3 letras)', '#vf-name'];
    if (val('#vf-address').length < 5) return ['Escribe la dirección de la clínica (calle y número)', '#vf-address'];
    if (!val('#vf-city')) return ['Escribe la ciudad o municipio', '#vf-city'];
    if (!STATES.includes(val('#vf-state'))) return ['Elige el estado', '#vf-state'];
    if (val('#vf-cp') && !/^\d{5}$/.test(val('#vf-cp'))) return ['El código postal tiene 5 dígitos', '#vf-cp'];
    if (digits(val('#vf-phone')).length < 10 && digits(val('#vf-wa')).length < 10) return ['Indica al menos un teléfono o WhatsApp de 10 dígitos', '#vf-phone'];
    if (val('#vf-email') && !/^[^\s@<>"']+@[^\s@<>"']+\.[^\s@<>"']+$/.test(val('#vf-email'))) return ['Revisa el correo de la clínica', '#vf-email'];
    if (val('#vf-web') && !webUrl(val('#vf-web'))) return ['Revisa la dirección del sitio web', '#vf-web'];
    const badDay = $$('#vf-hours .hours-day').find(d => { const r = readDay(d); return !r.closed && r.ranges.some(x => !x.open || !x.close); });
    if (badDay) return [`Escribe la hora de apertura y de cierre de cada horario del ${$('span[title]', badDay).title.toLowerCase()}, quita el que sobre o márcalo como cerrado`, `#vf-hours [data-day="${badDay.dataset.day}"] [data-open]`];
    if (keepPhotos.length + (photoStore.vf || []).length > MAX_PHOTOS) return [`Máximo ${MAX_PHOTOS} fotos en total. Quita alguna`, '#vf-photos-lbl'];
    if (val('#vf-vet').length < 5) return ['Escribe el nombre completo del médico veterinario responsable, como aparece en su cédula', '#vf-vet'];
    if (!CEDULA_RE.test(val('#vf-cedula'))) return ['El número de cédula profesional son de 5 a 10 dígitos, sin espacios ni letras', '#vf-cedula'];
    if (!cedulaFile && !(editing && (editing.cedula_document_id || editing.cedula_document_purged_at))) return ['Sube la foto o el PDF de la cédula profesional', '#vf-cedula-add'];
    if (!locStore.vf) return ['Ubica la clínica: usa «Ubicar» dentro de la clínica o «Ubicar por dirección»', '#vf-geocode'];
    if (!$('#vf-consent').checked) return ['Marca la casilla de consentimiento para continuar', '#vf-consent'];
    return null;
  }
  async function submitForm(e) {
    e.preventDefault();
    const err = validateForm();
    if (err) {
      toast(err[0], 'error');
      const el = $(err[1]);
      if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); if (el.focus) el.focus({ preventScroll: true }); }
      return;
    }
    await withBtn($('#vf-submit'), async () => {
      const val = id => $(id).value.trim();
      const body = {
        name: val('#vf-name'), description: val('#vf-desc') || null, address: val('#vf-address'), city: val('#vf-city'), state: val('#vf-state'),
        postal_code: val('#vf-cp') || null, latitude: locStore.vf.lat, longitude: locStore.vf.lon,
        phone: val('#vf-phone') || null, whatsapp: val('#vf-wa') || null, email: val('#vf-email') || null, website: webUrl(val('#vf-web')) || null,
        hours: readHours(), services: $$('#vf-services .chip.on').map(c => c.dataset.service), emergency_24h: $('#vf-24h').checked,
        responsible_vet_name: val('#vf-vet'), cedula_profesional: val('#vf-cedula'), cedula_institution: val('#vf-institution') || null,
      };
      if (!editing) body.consent = true;  // casilla obligatoria: el servidor guarda la fecha y la versión de los Términos
      if (cedulaFile) {
        const ids = await uploadDocuments([cedulaFile]);
        if (!ids.length) throw new Error('No pudimos subir la cédula. Inténtalo de nuevo');
        body.cedula_document_id = ids[0];
      }
      body.photos = [...keepPhotos, ...(await uploadFiles(photoStore.vf))].slice(0, MAX_PHOTOS);
      let r;
      try { r = await api(editing ? `/veterinaries/${editing.id}` : '/veterinaries', { method: editing ? 'PATCH' : 'POST', body }); }
      catch (err2) { if (missing(err2)) throw new Error('El registro de veterinarias se activará muy pronto. Inténtalo más tarde 🩺'); throw err2; }
      track(editing ? 'veterinary_updated' : 'veterinary_registered');
      cedulaFile = null; clearPhotos('vf');
      if (editing) toast(r && r.status === 'pending' && editing.status !== 'pending' ? 'Cambios guardados. Volveremos a revisar tu clínica' : 'Cambios guardados', 'ok');
      else await FX.success('¡Solicitud enviada!', 'Revisaremos la cédula y te avisaremos por notificación');
      editing = null;
      navigate('my-vet', { push: false });
    });
  }

  /* ---------- «Mi veterinaria» ---------- */
  function googlePanel(v) {
    const linked = !!(v.google_place_id || v.google_linked);
    const maps = safeUrl(v.google_maps_url || '');
    return `<section class="card mt16 gplaces" id="mv-google" aria-labelledby="mv-g-title"><div class="gm-head">${GM_LOGO}${linked ? '<span class="badge b-green">Vinculada</span>' : ''}</div>
      <div class="gm-body"><b id="mv-g-title">Reseñas de <span translate="no">Google Maps</span> en tu perfil</b>
      <p class="small muted mt8">${linked ? 'Tu perfil muestra tu calificación de Google Maps y hasta 5 reseñas tal como las entrega Google, consultadas en tiempo real.' : 'Vincula la ficha de tu clínica en Google Maps para mostrar tu calificación y hasta 5 reseñas de Google en tu perfil. Solo guardamos el identificador de la ficha.'}</p>
      ${linked ? `<div class="row mt8">${maps ? `<a class="btn btn-sm btn-ghost grow" href="${esc(maps)}" target="_blank" rel="noopener">Ver en Google Maps</a>` : ''}<button type="button" class="btn btn-sm btn-ghost" id="mv-unlink">Desvincular</button></div>`
        : `<form class="row mt8" id="mv-gform"><label class="sr-only" for="mv-gquery">Nombre de la clínica en Google Maps</label><input id="mv-gquery" class="inp grow" placeholder="Nombre de la clínica en Google Maps" value="${esc(v.name)}" maxlength="200"><button type="submit" class="btn btn-sm" id="mv-gsearch">Buscar</button></form><div class="col mt8" id="mv-gresults"></div>`}</div></section>`;
  }
  async function loadMine() {
    const body = $('#my-vet-body');
    body.innerHTML = FX.inlineLoader('Cargando tu veterinaria...');
    let v;
    try { v = await api('/veterinaries/me'); }
    catch (e) {
      $('#mv-status').textContent = '';
      if (missing(e)) { body.innerHTML = SOON; return; }
      if (e.status === 404) {
        body.innerHTML = FX.empty('Aún no registras una veterinaria', '¿Tienes una clínica? Regístrala gratis: verificamos la cédula del médico responsable y apareces en el directorio y en el mapa', { action: 'vet-register', label: 'Registrar mi veterinaria' });
        FX.decorate(body);
      } else { body.innerHTML = ''; toast(e.message, 'error'); }
      return;
    }
    $('#mv-status').textContent = v.name;
    const [label] = STATUS[v.status] || [v.status];
    const msg = v.status === 'pending' ? 'Estamos cotejando la cédula del médico responsable en el Registro Nacional de Profesionistas de la SEP. Te avisaremos por notificación.'
      : v.status === 'rejected' ? `No pudimos verificar tu clínica${v.rejection_note ? `: «${esc(v.rejection_note)}»` : '.'} Corrige los datos y vuelve a enviarla.`
        : `Tu clínica aparece en el directorio y en el mapa con la insignia «Cédula verificada».${v.verification_expires_at ? ` La verificación vence el ${esc(fmtDate(v.verification_expires_at))}.` : ''}`;
    body.innerHTML = `
      <div class="card p row pop-in">${thumbBox(v)}<div class="grow" style="min-width:0"><b class="ellipsis">${esc(v.name)}</b><div class="small muted ellipsis">${esc(place(v))}</div></div>${statusBadge(v.status)}</div>
      <div class="card p mt12" role="status" style="background:${v.status === 'verified' ? 'var(--green)' : v.status === 'rejected' ? 'var(--pink)' : 'var(--yellow)'}"><b>${esc(label)}</b><p class="small mt8" style="font-weight:600">${msg}</p></div>
      ${v.is_hidden ? HIDDEN_NOTE : ''}
      <div class="row mt12"><button type="button" class="btn btn-sm grow" id="mv-edit">✏️ ${v.status === 'rejected' ? 'Corregir y reenviar' : 'Editar datos'}</button>${v.status === 'verified' ? '<button type="button" class="btn btn-sm btn-ghost grow" id="mv-view">Ver perfil público</button>' : ''}</div>
      <p class="small muted mt8">Si cambias el nombre, el médico responsable o la cédula, la clínica vuelve a revisión.</p>
      ${v.status === 'verified' ? '<p class="small muted mt8">Desde tu perfil público puedes responder las reseñas (una respuesta por reseña).</p>' : ''}
      ${v.status !== 'rejected' ? googlePanel(v) : ''}
      <div class="card p mt16"><b class="small">Lo que ven las personas</b><div class="mt8">${hoursList(v.hours)}</div>${Array.isArray(v.services) && v.services.length ? `<div class="chips mt8">${v.services.map(s => `<span class="badge b-blue">${esc(s)}</span>`).join('')}</div>` : ''}
        <p class="small muted mt8">Responsable: ${esc(v.responsible_vet_name || '')} · Cédula ${esc(v.cedula_profesional || '')}</p></div>`;
    FX.decorate(body);
    $('#mv-edit').onclick = () => openForm(v);
    const view = $('#mv-view'); if (view) view.onclick = () => open(v.id);
    bindGoogle(v);
    // Sin GOOGLE_MAPS_API_KEY en el servidor no se ofrece la búsqueda (respondería 503)
    const m = await meta();
    if (m && m.google_enabled === false && !(v.google_place_id || v.google_linked)) {
      const g = $('#mv-gform');
      if (g) { $('#mv-gresults').remove(); g.outerHTML = '<p class="small muted mt8">La vinculación con Google Maps no está disponible por ahora.</p>'; }
    }
  }
  function bindGoogle(v) {
    const unlink = $('#mv-unlink');
    if (unlink) unlink.onclick = () => withBtn(unlink, async () => {
      if (!confirm('¿Quitar las reseñas de Google Maps de tu perfil?')) return;
      await api(`/veterinaries/${v.id}/google-link`, { method: 'POST', body: { place_id: null } });
      toast('Ficha de Google Maps desvinculada'); loadMine();
    });
    const form = $('#mv-gform');
    if (form) form.addEventListener('submit', e => {
      e.preventDefault();
      const search = $('#mv-gsearch');
      withBtn(search, async () => {
        const query = $('#mv-gquery').value.trim();
        if (query.length < 2) throw new Error('Escribe el nombre de tu clínica');
        const box = $('#mv-gresults');
        box.innerHTML = FX.skeletonList(2);
        let res;
        try { res = await api(`/veterinaries/${v.id}/google-search`, { method: 'POST', body: { query } }); }
        catch (err) { box.innerHTML = ''; throw err; }
        const cands = Array.isArray(res) ? res : (res && res.candidates) || [];
        box.innerHTML = cands.length ? cands.map(c => `<div class="card p row"><div class="grow" style="min-width:0"><b class="small ellipsis">${esc(c.name || 'Sin nombre')}</b><div class="small muted">${esc(c.address || '')}${c.rating != null ? ` · ★ ${esc(Number(c.rating).toFixed(1))} (${esc(c.ratings_total || 0)})` : ''}</div></div><button type="button" class="btn btn-sm" data-place="${esc(c.place_id)}">Es mi clínica</button></div>`).join('')
          + '<p class="small muted">Resultados de <span translate="no">Google Maps</span>.</p>'
          : '<p class="small muted">No encontramos tu clínica en Google Maps cerca de la dirección registrada. Prueba con otro nombre.</p>';
        FX.decorate(box);
        $$('[data-place]', box).forEach(b => b.onclick = () => withBtn(b, async () => {
          await api(`/veterinaries/${v.id}/google-link`, { method: 'POST', body: { place_id: b.dataset.place } });
          toast('Ficha de Google Maps vinculada ⭐', 'ok'); loadMine();
        }));
      });
    });
  }
  function openMine() { if (!state.me) return toast('Inicia sesión para ver tu veterinaria', 'error'); navigate('my-vet'); }

  /* ---------- mapa (gancho desde loadMap de app.js) ---------- */
  let vetIcon = null;
  async function loadMapMarkers(lat, lon) {
    if (!state.map || !window.L) return 0;
    const chip = $('#map-filters [data-k="vet"]');
    if (!state.mapLayers.vet) {
      state.mapLayers.vet = L.layerGroup();
      if (!chip || chip.classList.contains('on')) state.mapLayers.vet.addTo(state.map);
    }
    const layer = state.mapLayers.vet;
    let vets = [];
    try { vets = await api(`/veterinaries?lat=${lat}&lon=${lon}&radius_km=30&limit=100`); } catch { return 0; }
    layer.clearLayers();
    if (!vetIcon) vetIcon = L.icon({ iconUrl: '/app/img/vet-marker.svg', iconSize: [38, 46], iconAnchor: [19, 44], popupAnchor: [0, -40] });
    const shown = vets.filter(v => v.latitude != null && v.longitude != null);
    shown.forEach(v => {
      // Solo datos propios de la clínica: el contenido de Google nunca va junto al mapa de OpenStreetMap
      L.marker([v.latitude, v.longitude], { icon: vetIcon, alt: `Veterinaria ${v.name}`, title: v.name })
        .bindPopup(mapPopup(photo(v), `<b>${esc(v.name)}</b><br>🩺 Veterinaria${v.emergency_24h ? ' · Urgencias 24 h' : ''}<br>${esc(v.address || '')}<br><a href="#" data-vet="${+v.id}">Ver clínica →</a>`))
        .addTo(layer);
    });
    return shown.length;
  }

  /* ---------- notificaciones ---------- */
  function onNotif(type, data = {}) {
    // Avisos para el equipo (clínica por verificar, reseña retenida, solicitud): al panel, solo si eres admin
    const admin = !!(state.me && ['admin', 'superadmin'].includes(state.me.role));
    if (ADMIN_TYPES.includes(type) && admin) { location.href = '/admin/'; return; }
    if ((/review/.test(type) || type === 'veterinary_request_resolved') && data.veterinary_id) return open(data.veterinary_id);
    return openMine();
  }

  /* ---------- eventos ---------- */
  function bind() {
    window.screenLoaders = Object.assign(window.screenLoaders || {}, { vets: loadList, 'my-vet': loadMine });
    device.addEventListener('click', e => {
      const t = e.target.closest('[data-vet],[data-empty-action="vet-register"],[data-flag-review],[data-reply],[data-reply-del],[data-clarify],[data-vet-complaint],[data-act="vets"],[data-act="my-vet"]');
      if (!t) return;
      if (t.matches('a')) e.preventDefault();
      if (t.dataset.clarify) openRequest(t, 'aclaracion', t.dataset.clarify);
      else if (t.hasAttribute('data-vet-complaint')) openRequest(t, 'queja', null);
      else if (t.dataset.vet) open(t.dataset.vet);
      else if (t.dataset.flagReview) openFlag('veterinary_review', t.dataset.flagReview, t.dataset.author || '');
      else if (t.dataset.reply) openReply(t);
      else if (t.dataset.replyDel) deleteReply(t);
      else if (t.dataset.act === 'vets') openList();
      else if (t.dataset.act === 'my-vet') openMine();
      else if (t.dataset.emptyAction === 'vet-register') openForm(null);
    });
    // Tarjetas con role=button: Enter/Espacio ya los convierte app.js en click
    $('#home-vets').addEventListener('click', openList);
    $('#vet-flag').addEventListener('click', () => detail && openFlag('veterinary', detail.id, detail.name));
    $('#vet-share').addEventListener('click', () => detail && share(`🩺 ${detail.name} en GuauWoow`, `/app/?vet=${detail.id}`));
    $('#vets-near').addEventListener('click', e => withBtn(e.currentTarget, async () => {
      filters.near = !filters.near;
      if (filters.near) { filters.city = ''; $('#vets-city').value = ''; }
      if (filters.near && !state.coords) {
        try { setCoords(await getPosition()); } catch (err) { filters.near = false; paintFilters(); throw err; }
      }
      await loadList();
    }));
    $('#vets-emergency').addEventListener('click', () => { filters.emergency = !filters.emergency; loadList(); });
    $('#vets-search-form').addEventListener('submit', e => {
      e.preventDefault();
      filters.q = $('#vets-q').value.trim().slice(0, 100);
      filters.city = $('#vets-city').value.trim().slice(0, 100);
      if (filters.city) filters.near = false;
      loadList();
    });
    $('#vets-register').addEventListener('click', () => openForm(null));
    $('#vets-mine').addEventListener('click', openMine);
    $('#vet-form').addEventListener('submit', submitForm);
    $('#vf-geocode').addEventListener('click', e => withBtn(e.currentTarget, geocodeAddress));
    $('#vf-copy-hours').addEventListener('click', copyMonday);
    bindHours();
    $('#vf-cedula-file').addEventListener('change', e => {
      const f = e.target.files[0]; e.target.value = '';
      if (!f) return;
      const types = typeof DOC_TYPES !== 'undefined' ? DOC_TYPES : ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
      if (!(types.includes(f.type) || /\.pdf$/i.test(f.name || ''))) return toast('Solo se aceptan fotos (JPG, PNG, WebP) o PDF', 'error');
      if (f.size > 10 * 1024 * 1024) return toast('La cédula debe pesar menos de 10 MB', 'error');
      cedulaFile = f; renderCedulaBox();
    });
  }
  bind();

  return { openList, open, openForm, openMine, loadList, loadMine, loadMapMarkers, onNotif, validateForm, STATES, SERVICES };
})();
window.VET = VET;
