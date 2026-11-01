/* ============================================================
   GuauWoow — Voluntarios: enviar publicaciones de Facebook (F3)
   - Enlace /app/?share=1&url=...&text=... (botón para voluntarios) y
     share_target del manifest (/app/?title=...&text=...&url=... desde Android)
   - Pantalla "Enviar publicación" → POST /facebook/volunteer-import
   - "Botón para voluntarios" (bookmarklet) en Ayuda
   - Estado de la República para los reportes (geocoder o selector)
   - Etiqueta de contenido importado en el detalle del reporte: enlace a la publicación original,
     fecha y «Soy el autor: retirar o reclamar» sin cuenta (POST /facebook/author-removal)
   Se carga después de app.js y usa sus utilidades globales ($, $$, esc, api, toast,
   navigate, state, current, photoStore, clearPhotos, uploadFiles, reverseGeocode, FX, track).
   Se expone como window.Compartir: app.js lo consulta con `window.Compartir` (un `const`
   de nivel superior no crea esa propiedad).
   ============================================================ */
'use strict';

window.Compartir = (() => {
  /* Estados con el nombre oficial corto que usa el backend (backend/app/data/estados_mx.py).
     "México" es el Estado de México; en pantalla se muestra como "Estado de México". */
  const MX_STATES = [
    ['Aguascalientes', ['aguascalientes']],
    ['Baja California', ['tijuana', 'mexicali', 'ensenada', 'rosarito', 'tecate']],
    ['Baja California Sur', ['la paz', 'los cabos', 'cabo san lucas', 'san jose del cabo', 'loreto']],
    ['Campeche', ['campeche', 'ciudad del carmen']],
    ['Chiapas', ['tuxtla gutierrez', 'tuxtla', 'tapachula', 'san cristobal de las casas', 'comitan']],
    ['Chihuahua', ['chihuahua', 'ciudad juarez', 'cd juarez', 'delicias', 'parral']],
    ['Ciudad de México', ['cdmx', 'ciudad de mexico', 'distrito federal', 'df', 'coyoacan', 'iztapalapa', 'gustavo a madero', 'tlalpan',
      'xochimilco', 'benito juarez', 'miguel hidalgo', 'alvaro obregon', 'azcapotzalco', 'venustiano carranza', 'tlahuac',
      'milpa alta', 'magdalena contreras', 'cuajimalpa', 'iztacalco', 'roma norte', 'roma sur', 'condesa', 'polanco', 'narvarte', 'del valle', 'santa fe']],
    ['Coahuila', ['saltillo', 'torreon', 'monclova', 'piedras negras', 'acuna']],
    ['Colima', ['colima', 'manzanillo', 'tecoman']],
    ['Durango', ['durango', 'gomez palacio', 'lerdo']],
    ['Guanajuato', ['guanajuato', 'leon', 'irapuato', 'celaya', 'salamanca', 'silao', 'san miguel de allende']],
    ['Guerrero', ['acapulco', 'chilpancingo', 'iguala', 'zihuatanejo', 'taxco']],
    ['Hidalgo', ['pachuca', 'tulancingo', 'tula', 'tizayuca', 'mineral de la reforma']],
    ['Jalisco', ['guadalajara', 'zapopan', 'tlaquepaque', 'tonala', 'tlajomulco', 'puerto vallarta', 'el salto', 'lagos de moreno', 'tepatitlan']],
    ['México', ['estado de mexico', 'edo de mexico', 'edo mex', 'edomex', 'toluca', 'ecatepec', 'nezahualcoyotl', 'neza', 'naucalpan', 'tlalnepantla',
      'chimalhuacan', 'cuautitlan', 'cuautitlan izcalli', 'atizapan', 'tultitlan', 'coacalco', 'texcoco', 'chalco', 'ixtapaluca', 'huixquilucan',
      'metepec', 'nicolas romero', 'tecamac', 'valle de chalco', 'lerma', 'zinacantepec']],
    ['Michoacán', ['morelia', 'uruapan', 'zamora', 'lazaro cardenas', 'apatzingan', 'patzcuaro']],
    ['Morelos', ['cuernavaca', 'jiutepec', 'cuautla', 'temixco']],
    ['Nayarit', ['tepic', 'bahia de banderas', 'nuevo vallarta']],
    ['Nuevo León', ['monterrey', 'san nicolas de los garza', 'apodaca', 'san pedro garza garcia', 'santa catarina', 'escobedo']],
    ['Oaxaca', ['oaxaca', 'juchitan', 'salina cruz', 'tuxtepec', 'huatulco', 'puerto escondido']],
    ['Puebla', ['puebla', 'tehuacan', 'san martin texmelucan', 'atlixco', 'cholula']],
    ['Querétaro', ['queretaro', 'san juan del rio', 'corregidora', 'el marques', 'juriquilla']],
    ['Quintana Roo', ['cancun', 'playa del carmen', 'chetumal', 'tulum', 'cozumel', 'solidaridad']],
    ['San Luis Potosí', ['san luis potosi', 'slp', 'soledad de graciano sanchez', 'ciudad valles']],
    ['Sinaloa', ['culiacan', 'mazatlan', 'los mochis', 'guasave']],
    ['Sonora', ['hermosillo', 'ciudad obregon', 'nogales', 'guaymas', 'navojoa', 'san luis rio colorado']],
    ['Tabasco', ['villahermosa', 'comalcalco']],
    ['Tamaulipas', ['reynosa', 'matamoros', 'nuevo laredo', 'tampico', 'ciudad victoria', 'ciudad madero', 'altamira']],
    ['Tlaxcala', ['tlaxcala', 'apizaco', 'huamantla']],
    ['Veracruz', ['veracruz', 'xalapa', 'jalapa', 'coatzacoalcos', 'cordoba', 'orizaba', 'poza rica', 'minatitlan', 'boca del rio']],
    ['Yucatán', ['merida', 'valladolid', 'progreso', 'kanasin']],
    ['Zacatecas', ['zacatecas', 'fresnillo']],
  ];
  const STATE_NAMES = MX_STATES.map(s => s[0]);
  const LABEL = { 'México': 'Estado de México' };
  const label = s => LABEL[s] || s;
  /* Nombres oficiales largos o variantes que devuelve el geocoder (Nominatim) */
  const STATE_ALIASES = {
    'mexico': 'México', 'estado de mexico': 'México', 'edomex': 'México', 'edo de mexico': 'México',
    'cdmx': 'Ciudad de México', 'distrito federal': 'Ciudad de México', 'df': 'Ciudad de México', 'ciudad de mexico': 'Ciudad de México',
    'michoacan de ocampo': 'Michoacán', 'veracruz de ignacio de la llave': 'Veracruz', 'coahuila de zaragoza': 'Coahuila', 'queretaro de arteaga': 'Querétaro',
  };

  const norm = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const hasPhrase = (text, phrase) => new RegExp(`(^| )${escRe(phrase)}($| )`).test(text);
  // "México" suelto casi siempre es el país ("Puebla, México"): para adivinar solo cuenta con "Estado de México" o "Edomex"
  const STATES_BY_LENGTH = STATE_NAMES.filter(s => s !== 'México').sort((a, b) => norm(b).length - norm(a).length);
  const HINTS = MX_STATES.flatMap(([name, hints]) => hints.map(h => [h, name])).sort((a, b) => b[0].length - a[0].length);

  /* "Veracruz de Ignacio de la Llave" / "Estado de México" / "cdmx" → nombre oficial corto ('' si no se reconoce) */
  function normalizeState(raw) {
    const n = norm(raw);
    if (!n) return '';
    if (STATE_ALIASES[n]) return STATE_ALIASES[n];
    const exact = STATE_NAMES.find(s => norm(s) === n);
    if (exact) return exact;
    const prefix = STATES_BY_LENGTH.find(s => n.startsWith(norm(s) + ' '));
    return prefix || '';
  }
  /* Adivina el estado a partir de un texto libre (colonia, ciudad, descripción) */
  function guessState(text) {
    const n = norm(text);
    if (!n) return '';
    if (STATE_ALIASES[n]) return STATE_ALIASES[n];
    const hit = HINTS.find(([h]) => hasPhrase(n, h) && h.length > 9);  // frases largas primero ("estado de mexico", "ciudad juarez")
    if (hit) return hit[1];
    const byName = STATES_BY_LENGTH.find(s => hasPhrase(n, norm(s)));
    if (byName) return byName;
    const any = HINTS.find(([h]) => hasPhrase(n, h));
    return any ? any[1] : '';
  }
  function fillStateSelect(sel, placeholder = 'Elige el estado') {
    if (!sel || sel.options.length > 1) return;
    sel.innerHTML = `<option value="">${esc(placeholder)}</option>` + STATE_NAMES.map(s => `<option value="${esc(s)}">${esc(label(s))}</option>`).join('');
  }

  /* ---------- estado detectado por el geocoder para los formularios (clave = prefijo del formulario: rf, pub, sh) ---------- */
  const geoState = {};
  function onGeocode(key, g) {
    const st = normalizeState(g && g.state);
    if (!st) return;
    geoState[key] = st;
    const sel = $(`#${key}-state`);
    if (sel && !sel.value) sel.value = st;
  }
  function clearGeo(key) {
    delete geoState[key];
    const sel = $(`#${key}-state`);
    if (sel) sel.value = '';
  }
  /* Estado que se envía con un reporte: lo que eligió la persona (o llenó el geocoder) → geocoder →
     texto de la colonia/ciudad → ciudad guardada. null si no se sabe (el backend lo deduce de la ciudad o las coordenadas). */
  function reportState(key) {
    const sel = $(`#${key}-state`), cityInput = $(`#${key}-city`);
    return (sel && sel.value) || geoState[key] || guessState(cityInput && cityInput.value) || guessState(state.city) || null;
  }

  /* ---------- enlace de la publicación compartida ---------- */
  const URL_RE = /https?:\/\/[^\s<>"'`]+/i;
  const FB_HOST_RE = /^(?:(?:www|m|web|mobile|touch|business)\.)?(?:facebook\.com|fb\.com)$|^fb\.watch$/i;
  /* Rutas cuyo identificador va en la query (se conservan solo esos parámetros, como en el backend) */
  const QUERY_PATHS = ['/permalink.php', '/photo.php', '/story.php', '/photo', '/watch'];
  const KEEP_PARAMS = ['story_fbid', 'fbid', 'id', 'v'];

  /* URL limpia: sin rastreadores (?__cft__, mibextid...) ni fragmento; '' si no es http(s) */
  function cleanUrl(u) {
    const s = String(u ?? '').trim().replace(/[),.;]+$/, '');
    if (!/^https?:\/\/[^\s<>"'`]+$/i.test(s) || s.length > 2000) return '';
    let p;
    try { p = new URL(s); } catch { return ''; }
    if (p.protocol !== 'https:' && p.protocol !== 'http:') return '';
    p.hash = '';
    if (FB_HOST_RE.test(p.hostname)) {
      const path = p.pathname.replace(/\/+$/, '');
      const keep = QUERY_PATHS.includes(path) ? KEEP_PARAMS.filter(k => p.searchParams.has(k)).map(k => [k, p.searchParams.get(k)]) : [];
      p.search = keep.length ? '?' + new URLSearchParams(keep) : '';
    }
    return p.href.length <= 500 ? p.href : '';
  }
  const firstUrl = t => { const m = String(t ?? '').match(URL_RE); return m ? cleanUrl(m[0]) : ''; };
  /* Mensaje de error si el enlace no sirve como publicación de Facebook ('' si está bien).
     Mismas reglas que post_url_problem() en backend/app/services/facebook_groups.py. */
  const GROUP_SUBPAGES = ['about', 'members', 'media', 'files', 'events', 'buy_sell_discussion', 'search', 'photos', 'videos', 'announcements', 'featured'];
  function urlProblem(u) {
    if (!u) return 'Pega el enlace de la publicación (empieza con https://)';
    const p = new URL(u);
    if (!FB_HOST_RE.test(p.hostname)) return 'El enlace debe ser de una publicación de Facebook';
    const path = p.pathname.replace(/\/+$/, '');
    if (QUERY_PATHS.includes(path)) return p.search ? '' : 'Al enlace le falta el número de la publicación. Cópialo de nuevo desde Facebook';
    if (/^fb\.watch$/i.test(p.hostname)) return path ? '' : 'Al enlace le falta el número del video. Cópialo de nuevo desde Facebook';
    const seg = path.split('/').filter(Boolean);
    const first = (seg[0] || '').toLowerCase();
    if (!path || (first === 'groups' && (seg.length <= 2 || GROUP_SUBPAGES.includes(seg[2].toLowerCase())))
      || ['home.php', 'marketplace', 'watch', 'search'].includes(first)) {
      return 'Ese enlace es del grupo, no de la publicación. Abre la publicación (toca su fecha) y copia ese enlace';
    }
    if (seg.length === 1) return 'Ese enlace es de un perfil o una página, no de la publicación. Abre la publicación (toca su fecha) y copia ese enlace';
    return '';
  }
  const guessType = t => /encontr|rescat|lo tengo|apareci|resguard|se qued[oó]|lo recog|deambula/i.test(t || '') ? 'found' : 'lost';

  /* ---------- pantalla "Enviar publicación" ---------- */
  let shareType = 'lost';
  function setShareType(type) {
    shareType = type === 'found' ? 'found' : 'lost';
    $$('#sh-type button').forEach(b => { const on = b.dataset.v === shareType; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
  }
  /* Sin sesión: se guarda la intención en la URL y se pide entrar; al entrar, handleDeepLinks la retoma */
  function rememberAndLogin(o) {
    const q = new URLSearchParams({ share: '1' });
    if (o.url) q.set('url', o.url);
    if (o.text) q.set('text', String(o.text).slice(0, 2000));
    try { history.replaceState({}, '', location.pathname + '?' + q); } catch { }
    toast('Inicia sesión para enviar la publicación 🐾', 'info');
    if (typeof showAuth === 'function' && current !== 'auth') showAuth('login');
  }
  function openShare(o = {}) {
    if (!state.me) return rememberAndLogin(o);
    const form = $('#share-form');
    form.reset();
    form.classList.remove('hidden');
    $('#share-done').classList.add('hidden');
    clearPhotos('sh');
    $('#sh-url').value = o.url || '';
    $('#sh-text').value = String(o.text || '').slice(0, 4000);
    setShareType(o.type || guessType(o.text));
    const city = (state.me && state.me.city) || state.city || '';
    $('#sh-city').value = city;
    const sel = $('#sh-state');
    sel.value = guessState(city) || '';
    navigate('share');
    if (state.coords && !sel.value) {
      reverseGeocode(state.coords).then(g => { const st = normalizeState(g && g.state); if (st && !sel.value && current === 'share') sel.value = st; });
    }
    setTimeout(() => { const f = $(o.url ? '#sh-text' : '#sh-url'); if (f && current === 'share') f.focus(); }, 350);
  }
  /* Parámetros de la URL: ?share=1&url=&text= (botón) o ?title=&text=&url= (share_target de Android).
     Facebook suele mandar el enlace dentro de text y no en url. */
  function openFromParams(p) {
    const rawUrl = p.get('url') || '', text0 = p.get('text') || '', title = p.get('title') || '';
    const url = cleanUrl(rawUrl) || firstUrl(text0) || firstUrl(title);
    // El enlace no se repite dentro del texto de la publicación
    let text = text0.replace(URL_RE, m => (cleanUrl(m) === url ? '' : m)).trim();
    if (title && !text.includes(title) && !cleanUrl(title) && !/^facebook$/i.test(title.trim())) text = [title.trim(), text].filter(Boolean).join('\n');
    openShare({ url, text });
  }
  async function submitShare(e) {
    e.preventDefault();
    if (!state.me) return rememberAndLogin({ url: $('#sh-url').value, text: $('#sh-text').value });
    const url = cleanUrl($('#sh-url').value);
    const problem = urlProblem(url);
    if (problem) { toast(problem, 'error'); $('#sh-url').focus(); return; }
    $('#sh-url').value = url;
    const text = $('#sh-text').value.trim();
    if (text.length < 10 && !photoStore.sh.length) return toast('Pega el texto de la publicación o agrega una foto 📸', 'error');
    const st = $('#sh-state').value || guessState($('#sh-city').value) || '';
    if (!st) { toast('Elige el estado donde está el perrito', 'error'); $('#sh-state').focus(); return; }
    if (!$('#sh-consent').checked) return toast('Confirma que la publicación es pública para continuar', 'error');
    const btn = $('#sh-submit');
    FX.setLoading(btn, true);
    FX.showLoading('Enviando la publicación', ['Subiendo fotos...', 'Quitando datos personales del texto...', 'Buscando coincidencias cerca...'], 'sniff');
    try {
      const photos = await uploadFiles(photoStore.sh);
      const r = await api('/facebook/volunteer-import', { method: 'POST', body: {
        url, text, city: $('#sh-city').value.trim() || null, state: st, report_type: shareType, photos,
        consent: true,  // #sh-consent marcado (el backend guarda la fecha y la versión de los términos)
      } });
      FX.hideLoading();
      track('volunteer_import', { type: shareType });
      await FX.success('¡Gracias por ayudar!', 'Ya estamos buscando coincidencias 🔎');
      showShareDone(r);
    } catch (err) {
      FX.hideLoading();
      if (err.status === 409) {
        // Alguien ya la envió (se deduplica por enlace): se muestra el reporte que ya existe
        toast(err.message || 'Esa publicación ya está en GuauWoow. ¡Gracias!', 'info');
        showShareDone({ report_id: err.data && err.data.report_id }, true);
      } else toast(err.message, 'error');  // 429: tope de 10 por día; 400: enlace o texto no válidos
    } finally { FX.setLoading(btn, false); }
  }
  function showShareDone(r, duplicate = false) {
    const id = r && (r.id || r.report_id || (r.report && r.report.id));
    $('#share-form').classList.add('hidden');
    const done = $('#share-done');
    done.classList.remove('hidden');
    if (!$('#sh-done-art').innerHTML) $('#sh-done-art').innerHTML = FX.dogFace(96);
    $('#sh-done-text').textContent = duplicate
      ? `Esa publicación ya estaba en GuauWoow${id ? ` (reporte #${id})` : ''}: ya estamos buscando coincidencias. ¡Gracias por ayudar!`
      : id
        ? `Creamos el reporte #${id} con la publicación. Avisamos a refugios y casas de paso de tu ciudad y comparamos las fotos con los reportes de la app.`
        : 'Recibimos la publicación. Avisamos a refugios y casas de paso de tu ciudad y comparamos las fotos con los reportes de la app.';
    const view = $('#sh-done-view');
    view.classList.toggle('hidden', !id);
    view.dataset.report = id ? String(id) : '';
    FX.decorate(done);
  }

  /* ---------- botón para voluntarios (bookmarklet) ----------
     Se arma con el origen actual (JSON.stringify lo deja como literal de texto seguro) y se codifica
     entero, como cualquier bookmarklet. Abre /app/?share=1&url=<publicación>&text=<texto seleccionado o título>
     en otra pestaña (si el navegador la bloquea, en la misma). Si la persona seleccionó el texto dentro de una
     publicación del muro del grupo, toma el enlace de esa publicación en lugar del enlace del grupo. */
  function bookmarkletHref() {
    const base = location.origin + '/app/';
    const code = '(function(){'
      + "var t='',u=location.href;"
      + 'try{var s=window.getSelection();t=String(s||"");'
      + 'var n=s&&s.anchorNode;n=n&&(n.nodeType===1?n:n.parentElement);'
      + "var a=n&&n.closest&&n.closest('[role=article]');"
      + "var l=a&&a.querySelector('a[href*=\"/posts/\"],a[href*=\"/permalink/\"],a[href*=\"story_fbid\"]');"
      + 'if(l&&l.href)u=l.href;}catch(e){}'
      + "if(!t)t=document.title||'';"
      + 'var g=' + JSON.stringify(base) + "+'?share=1&url='+encodeURIComponent(u)+'&text='+encodeURIComponent(t.slice(0,2000));"
      + "var w=window.open(g,'_blank');if(!w)location.href=g;"
      + '})();';
    return 'javascript:' + encodeURIComponent(code);
  }
  async function copyBookmarklet() {
    try { await navigator.clipboard.writeText(bookmarkletHref()); toast('Código copiado. Crea un marcador y pégalo como dirección 📋', 'ok'); }
    catch { toast('No pudimos copiar. Mantén presionado el botón y elige «Copiar enlace»', 'error'); }
  }

  /* ---------- detalle de un reporte importado (fuentes facebook | volunteer) ----------
     Etiqueta con atribución, enlace seguro al original (solo hosts de Facebook) y «Soy el autor: retirar o
     reclamar», que funciona sin cuenta: el reporte se oculta de inmediato y se borra en menos de 72 h. */
  function originalLink(raw) {
    const u = cleanUrl(raw);
    if (!u) return '';
    try { return FB_HOST_RE.test(new URL(u).hostname) && new URL(u).protocol === 'https:' ? u : ''; } catch { return ''; }
  }
  function importedHtml(r) {
    const link = originalLink(r.external_url);
    const when = r.external_posted_at ? fmtDate(r.external_posted_at) : '';
    // Etiqueta que manda el backend (LostReportOut.import_notice, contrato L-fb) o la misma frase si aún no llega
    const notice = (r.import_notice || 'Importado de una publicación pública; su autor no es usuario de GuauWoow').replace(/\.$/, '');
    // «Soy el autor: retirar o reclamar» abre el centro de solicitudes (sin cuenta) con el reporte ya indicado
    const claim = `/app/legal/contenido-importado.html?report_id=${encodeURIComponent(r.id)}#form-solicitud`;
    return `<div class="card p small mt12" id="rp-imported" style="background:var(--blue)">
      <div>ℹ️ <b>${esc(notice)}.</b>
        ${when ? `Publicado originalmente en Facebook el ${esc(when)}.` : 'Publicado originalmente en Facebook.'}
        Quitamos teléfonos, correos, enlaces, datos de pago y nombres de personas del texto, y lo borramos de verdad a los 30 días.</div>
      ${link ? `<a class="btn btn-ghost mt8" id="rp-original" href="${esc(link)}" target="_blank" rel="noopener noreferrer nofollow">Ver la publicación original en Facebook ↗</a>` : ''}
      <a class="btn btn-ghost mt8" id="rp-author-link" href="${esc(claim)}" target="_blank" rel="noopener">Soy el autor: retirar o reclamar</a>
      <button type="button" class="link small mt8" id="rp-author" aria-expanded="false" aria-controls="rp-author-form">¿Solo quieres retirarla? Pídelo aquí mismo</button>
      <form class="col mt8 hidden" id="rp-author-form" novalidate>
        <label class="lbl" for="rp-author-rel">Tu relación con la publicación</label>
        <select class="inp" id="rp-author-rel">
          <option value="autor">Soy la persona autora</option>
          <option value="aparezco">Aparezco en la publicación</option>
          <option value="otro">Otro motivo</option>
        </select>
        <label class="lbl" for="rp-author-email">Correo para responderte</label>
        <input class="inp" id="rp-author-email" type="email" maxlength="255" autocomplete="email" placeholder="tu@correo.com" required>
        <label class="lbl" for="rp-author-details">Comentario (opcional)</label>
        <textarea class="inp" id="rp-author-details" maxlength="1000" rows="3" placeholder="Qué quieres que retiremos o corrijamos"></textarea>
        <button type="submit" class="btn block btn-orange" id="rp-author-send">Pedir el retiro</button>
        <p class="small muted">No necesitas cuenta. Ocultamos la publicación de inmediato y borramos su texto y fotos en menos de 72 horas. Para otros derechos sobre tus datos consulta el <a href="/app/legal/privacidad.html" target="_blank" rel="noopener">aviso de privacidad</a>.</p>
      </form>
      <p class="small mt8 hidden" id="rp-author-done" role="status"></p>
    </div>`;
  }
  function bindImported(r) {
    const btn = $('#rp-author'), form = $('#rp-author-form');
    if (!btn || !form) return;
    btn.addEventListener('click', () => {
      const open = form.classList.toggle('hidden') === false;
      btn.setAttribute('aria-expanded', String(open));
      if (open) { if (state.me && state.me.email && !$('#rp-author-email').value) $('#rp-author-email').value = state.me.email; $('#rp-author-email').focus(); }
    });
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const email = $('#rp-author-email').value.trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) { toast('Escribe un correo válido para poder responderte', 'error'); $('#rp-author-email').focus(); return; }
      const send = $('#rp-author-send');
      FX.setLoading(send, true);
      try {
        const res = await api('/facebook/author-removal', { method: 'POST', noLogout: true, body: {
          report_id: r.id, relation: $('#rp-author-rel').value, email, details: $('#rp-author-details').value.trim() || null,
        } });
        form.classList.add('hidden');
        btn.classList.add('hidden');
        const done = $('#rp-author-done');
        done.textContent = (res && res.message) || 'Recibimos tu solicitud. La revisamos en menos de 72 horas.';
        done.classList.remove('hidden');
        toast('Solicitud enviada. Gracias por avisarnos 🐾', 'ok');
      } catch (err) { toast(err.message, 'error'); }
      finally { FX.setLoading(send, false); }
    });
  }

  function init() {
    fillStateSelect($('#sh-state'));
    fillStateSelect($('#rf-state'), 'Detectar con mi ubicación');
    $('#share-form').addEventListener('submit', submitShare);
    $$('#sh-type button').forEach(b => b.addEventListener('click', () => setShareType(b.dataset.v)));
    $('#sh-done-again').addEventListener('click', () => openShare({}));
    $('#sh-done-home').addEventListener('click', () => navigate('home', { reset: true }));
    const bm = $('#volunteer-bookmarklet');
    bm.href = bookmarkletHref();
    // Dentro de la app no se ejecuta (la CSP lo bloquearía): el botón es para arrastrarlo a la barra de marcadores
    bm.addEventListener('click', e => { e.preventDefault(); toast('Arrastra este botón a la barra de marcadores de tu navegador 🐾', 'info'); });
    $('#volunteer-copy').addEventListener('click', copyBookmarklet);
    $('#volunteer-send').addEventListener('click', () => openShare({}));
  }
  init();

  return {
    states: () => STATE_NAMES.slice(), stateLabel: label, normalizeState, guessState, fillStateSelect, onGeocode, clearGeo, reportState,
    cleanUrl, urlProblem, openShare, openFromParams, bookmarkletHref, importedHtml, bindImported,
  };
})();
