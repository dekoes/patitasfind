/* ============================================================
   GuauWoow — Tienda solidaria
   Comprador: catálogo, carrito de un solo refugio, checkout con dirección
   estructurada, "Mis pedidos" con línea de tiempo, cancelación, devoluciones,
   confirmación de entrega y facturas (CFDI del refugio vendedor).
   Refugio: panel "Mi tienda" (productos con envío, pedidos, devoluciones,
   facturas, datos fiscales, cobros con Mercado Pago y estados de cuenta).

   Se carga después de app.js y usa sus utilidades globales ($, $$, api, esc,
   toast, money, photo, imgOrDog, imgTag, state, navigate, back, withBtn, FX,
   openList, uploadFiles, uploadDocuments, photoStore, clearPhotos, fmtDate,
   fmtTime, parseDate, safeUrl, sessionExpired, STATUS_LABEL, NOTIF_ICON,
   shopOn, current, device, track, openFlag).
   Mientras el backend termina los endpoints nuevos, cada llamada degrada con
   un mensaje claro cuando responde 404 "Not Found".
   ============================================================ */
window.Tienda = (() => {
  'use strict';

  /* ============================================================
     Catálogos
     ============================================================ */
  /* Mismos nombres que backend/app/data/estados_mx.py (el backend valida el estado de envío con ellos) */
  const MX_STATES = [
    'Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche', 'Chiapas', 'Chihuahua', 'Ciudad de México',
    'Coahuila', 'Colima', 'Durango', 'Guanajuato', 'Guerrero', 'Hidalgo', 'Jalisco', 'México', 'Michoacán',
    'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca', 'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa',
    'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán', 'Zacatecas',
  ];
  const STATE_DISPLAY = { 'México': 'Estado de México' };
  const stateLabel = s => STATE_DISPLAY[s] || s;
  /* Estados de un pedido (S3) en español. STATUS_LABEL se comparte con adopciones ("completed" = ¡Adoptado!),
     por eso los pedidos usan este mapa completo y a STATUS_LABEL solo se agregan las claves nuevas. */
  const ORDER_STATUS = {
    created: 'Creado', pending_payment: 'Pago pendiente', paid: 'Pagado', preparing: 'Preparando', shipped: 'Enviado',
    delivered: 'Entregado', completed: 'Completado', cancelled: 'Cancelado', expired: 'Expirado',
    return_requested: 'Devolución solicitada', return_approved: 'Devolución aprobada', return_rejected: 'Devolución rechazada',
    refunded: 'Reembolsado', refund_pending: 'Reembolso pendiente', amount_mismatch: 'Pago en revisión',
  };
  Object.keys(ORDER_STATUS).forEach(k => { if (!(k in STATUS_LABEL)) STATUS_LABEL[k] = ORDER_STATUS[k]; });
  const ORDER_BADGE = {
    pending_payment: 'b-yellow', paid: 'b-green', preparing: 'b-yellow', shipped: 'b-blue', delivered: 'b-teal', completed: 'b-green',
    cancelled: 'b-red', expired: 'b-gray', return_requested: 'b-orange', return_approved: 'b-lila', return_rejected: 'b-red',
    refunded: 'b-lila', refund_pending: 'b-yellow', amount_mismatch: 'b-yellow',
  };
  const ORDER_HINT = {
    pending_payment: 'Termina el pago en Mercado Pago para que el refugio prepare tu pedido.',
    paid: 'El refugio ya recibió tu pago y empacará tu pedido.',
    preparing: 'El refugio está preparando tu pedido.',
    shipped: 'Tu pedido va en camino. Cuando lo recibas, confírmalo aquí.',
    delivered: 'Tu pedido fue entregado. Tienes 5 días hábiles para solicitar una devolución.',
    completed: 'Pedido completado. ¡Gracias por apoyar a los refugios! 💚',
    cancelled: 'Este pedido se canceló. Si ya habías pagado, el reembolso llega en el plazo de tu banco.',
    expired: 'El pago no se completó a tiempo y el pedido expiró. Puedes volver a comprar.',
    return_requested: 'El refugio revisará tu solicitud de devolución.',
    return_approved: 'Devolución aprobada: el reembolso está en proceso.',
    return_rejected: 'El refugio no aprobó la devolución. Revisa su nota o escríbenos desde Ayuda.',
    refunded: 'Reembolsado a tu medio de pago. Puede tardar unos días en reflejarse.',
    refund_pending: 'Estamos gestionando tu reembolso.',
    amount_mismatch: 'Estamos revisando el pago con Mercado Pago. Te avisaremos.',
  };
  const TIMELINE_LABEL = { ...ORDER_STATUS, created: 'Pedido creado', paid: 'Pago recibido', preparing: 'En preparación', partial_refund: 'Reembolso parcial', bonus_registered: 'Bonificación registrada', bonus_paid: 'Bonificación pagada', bonus_waived: 'Bonificación revisada' };
  /* Reglas de negocio (GET /cumplimiento/reglas; services/reglas.py). Si el backend no responde se usan estas categorías. */
  const FALLBACK_CATEGORIES = [
    ['promocionales', 'Artículos promocionales del Refugio (playeras, tazas, bolsas, calcomanías)'], ['ropa_textiles', 'Ropa para perro y textiles'],
    ['accesorios_juguetes', 'Accesorios seguros y juguetes (correas, platos, camas, placas)'], ['impresos', 'Impresos (calendarios, libros, postales)'],
    ['electronicos', 'Electrónicos (por ejemplo, localizadores)'], ['alimento_industrializado', 'Alimento industrializado para perros'],
    ['masticables_carnaza', 'Masticables de carnaza sin relleno'], ['higiene_belleza', 'Higiene y belleza sin efecto terapéutico'], ['otro', 'Otro (lo revisamos antes de publicarlo)'],
  ];
  const NO_WARRANTY = 'Sin garantía adicional';
  const BONUS_STATUS = { pendiente: ['Pendiente', 'b-yellow'], pagada: ['Pagada', 'b-green'], improcedente: ['No procede', 'b-gray'] };
  let rulesCache = null;
  async function loadRules() {
    if (rulesCache) return rulesCache;
    try { rulesCache = await api('/cumplimiento/reglas'); } catch { rulesCache = null; }
    return rulesCache;
  }
  function categories() { return rulesCache && rulesCache.shop && Array.isArray(rulesCache.shop.categories) ? rulesCache.shop.categories.map(c => [c.key, c.label]) : FALLBACK_CATEGORIES; }
  function categoryLabel(p) { return p.category_label || (categories().find(c => c[0] === p.category) || [])[1] || ''; }
  function warrantyLabel(p) { return p.warranty_days ? `Garantía: ${p.warranty_days} días desde la entrega` : NO_WARRANTY; }
  /* Por qué se canceló un pedido (Order.cancel_reason); el detalle del refugio o del equipo viene en cancel_note */
  const CANCEL_REASON = {
    buyer: 'lo cancelaste tú', payment_expired: 'el pago no se completó a tiempo', checkout_failed: 'no se pudo crear el pago',
    dispatch_timeout: 'el refugio no lo envió a tiempo', refuge: 'el refugio no pudo surtirlo', admin: 'lo canceló el equipo de GuauWoow',
  };
  /* Causas objetivas para que el refugio cancele (consumidor-ecommerce-14); mismas claves que OrderCancelRequest */
  const SELLER_CANCEL_REASONS = [
    ['sin_inventario', 'Se agotó el producto'], ['no_puedo_enviar', 'No es posible enviarlo'],
    ['direccion_invalida', 'La dirección no es válida o no tiene cobertura'], ['sospecha_fraude', 'Posible fraude en el pago'], ['otro', 'Otro motivo'],
  ];
  const REFUND_RETRYABLE = ['error', 'insufficient_funds'];
  const RETURN_REASONS = [
    ['defectuoso', 'Llegó dañado o defectuoso'], ['no_corresponde', 'No es lo que pedí'], ['no_llego', 'No me llegó'],
    ['arrepentimiento', 'Cambié de opinión (revocación)'], ['otro', 'Otro motivo'],
  ];
  /* LFPC art. 56: 5 días hábiles desde la entrega para revocar una compra a distancia
     (docs/legal/secciones/consumidor-ecommerce.json). El backend tiene la última palabra (RETURN_WINDOW_DAYS). */
  const RETURN_WINDOW_DAYS = 5;
  const SAT_REGIMENES = [
    ['601', 'General de Ley Personas Morales'], ['603', 'Personas Morales con Fines no Lucrativos'],
    ['605', 'Sueldos y Salarios e Ingresos Asimilados a Salarios'], ['606', 'Arrendamiento'],
    ['607', 'Régimen de Enajenación o Adquisición de Bienes'], ['608', 'Demás ingresos'],
    ['610', 'Residentes en el Extranjero sin Establecimiento Permanente en México'], ['611', 'Ingresos por Dividendos (socios y accionistas)'],
    ['612', 'Personas Físicas con Actividades Empresariales y Profesionales'], ['614', 'Ingresos por intereses'],
    ['615', 'Régimen de los ingresos por obtención de premios'], ['616', 'Sin obligaciones fiscales'],
    ['620', 'Sociedades Cooperativas de Producción'], ['621', 'Incorporación Fiscal'],
    ['622', 'Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras'], ['623', 'Opcional para Grupos de Sociedades'], ['624', 'Coordinados'],
    ['625', 'Actividades Empresariales con ingresos a través de Plataformas Tecnológicas'], ['626', 'Régimen Simplificado de Confianza'],
  ];
  /* Regímenes válidos por tipo de persona (catálogo c_RegimenFiscal; mismos que REGIMENES_* en backend/app/schemas.py) */
  const REGIMENES_FISICA = ['605', '606', '607', '608', '610', '611', '612', '614', '615', '616', '621', '625', '626'];
  const REGIMENES_MORAL = ['601', '603', '607', '610', '620', '622', '623', '624', '626'];
  const SAT_USOS_CFDI = [
    ['G01', 'Adquisición de mercancías'], ['G02', 'Devoluciones, descuentos o bonificaciones'], ['G03', 'Gastos en general'],
    ['I01', 'Construcciones'], ['I02', 'Mobiliario y equipo de oficina'], ['I03', 'Equipo de transporte'], ['I04', 'Equipo de cómputo y accesorios'],
    ['I08', 'Otra maquinaria y equipo'], ['D04', 'Donativos'], ['S01', 'Sin efectos fiscales'], ['CP01', 'Pagos'],
  ];
  const RFC_RE = /^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$/;
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const INVOICE_LABEL = { requested: 'Solicitada', issued: 'Emitida', rejected: 'Rechazada' };

  /* Íconos de las notificaciones nuevas de la tienda (services/notify.py) */
  const SHOP_NOTIF_ICON = {
    order_preparing: ['📦', 'var(--yellow)'], order_cancelled: ['✖️', 'var(--sand)'], order_completed: ['💚', 'var(--green)'],
    order_status: ['📦', 'var(--blue)'], order_return_requested: ['↩️', 'var(--pink)'], order_return_approved: ['↩️', 'var(--green)'],
    order_return_rejected: ['↩️', 'var(--sand)'], return_requested: ['↩️', 'var(--pink)'], invoice_requested: ['🧾', 'var(--lila)'],
    invoice_issued: ['🧾', 'var(--green)'], invoice_rejected: ['🧾', 'var(--sand)'], mp_connected: ['💳', 'var(--green)'],
    mp_disconnected: ['💳', 'var(--sand)'], cfdi_issued: ['🧾', 'var(--lila)'], order_refund_failed: ['💸', 'var(--pink)'],
    order_payment_review: ['🔎', 'var(--yellow)'], order_partial_refund: ['💸', 'var(--lila)'], order_dispatch_overdue: ['⏰', 'var(--pink)'],
    invoice_cancel_needed: ['🧾', 'var(--pink)'],
  };
  if (typeof NOTIF_ICON === 'object') Object.keys(SHOP_NOTIF_ICON).forEach(k => { if (!(k in NOTIF_ICON)) NOTIF_ICON[k] = SHOP_NOTIF_ICON[k]; });
  /* Notificaciones que van al panel del refugio (pestaña de "Mi tienda") */
  const SELLER_NOTIF = {
    new_order: 'pedidos', return_requested: 'pedidos', invoice_requested: 'facturas', invoice_cancel_needed: 'facturas',
    mp_connected: 'cobros', mp_disconnected: 'cobros', mp_token_error: 'cobros', cfdi_issued: 'cuenta', statement_ready: 'cuenta',
  };

  /* ============================================================
     Utilidades
     ============================================================ */
  function orderLabel(s) { return ORDER_STATUS[s] || STATUS_LABEL[s] || s; }
  function orderBadge(s) { return `<span class="badge ${ORDER_BADGE[s] || 'b-yellow'}">${esc(orderLabel(s))}</span>`; }
  /* 404 "Not Found" de FastAPI = el endpoint todavía no existe en este servidor */
  function isNotReady(e) { return !!e && e.status === 404 && e.message === 'Not Found'; }
  function notReady(e) { return isNotReady(e) ? 'Esta función estará disponible muy pronto 🐾' : (e && e.message) || 'Algo falló'; }
  function num(n) { return n == null || n === '' ? null : Number(n); }
  function sellerReady(p) { return !p || p.seller_payments_ready !== false; }
  /* Transparencia (consumidor-ecommerce-17; gap-custodia-13): cuánto se queda GuauWoow y cuánto recibe el refugio */
  function feeSplit(amount, pct) {
    const p = Number(pct) || 0;
    const fee = Math.round(Number(amount || 0) * p) / 100;
    return { pct: p, fee, net: Math.round((Number(amount || 0) - fee) * 100) / 100 };
  }
  function feeText(amount, pct, who = 'el refugio') {
    const f = feeSplit(amount, pct);
    if (!f.pct) return `GuauWoow no cobra comisión: ${who} recibe ${money(f.net)} (antes de la comisión de Mercado Pago).`;
    return `GuauWoow recibe ${f.pct} % (${money(f.fee)}); ${who} recibe ${money(f.net)} (antes de la comisión de Mercado Pago y de los impuestos que la ley obliga a retener).`;
  }
  /* Dirección guardada en este dispositivo SOLO si la persona marcó la casilla (consumidor-ecommerce-20).
     Las entradas sin "v" son de versiones anteriores, que guardaban sin preguntar: se borran. */
  const ADDRESS_KEY = 'patitas_address';
  function savedAddress() {
    try {
      const a = JSON.parse(localStorage.getItem(ADDRESS_KEY) || 'null');
      if (a && a.v === 2) return a;
      if (a) localStorage.removeItem(ADDRESS_KEY);
    } catch { }
    return null;
  }
  function rememberAddress(a) { try { localStorage.setItem(ADDRESS_KEY, JSON.stringify({ ...a, v: 2 })); } catch { } }
  function forgetAddress() { try { localStorage.removeItem(ADDRESS_KEY); } catch { } }
  function shippingLabel(p) {
    const c = num(p.shipping_cost);
    if (c == null) return 'Envío: se calcula antes de pagar';
    return c > 0 ? `Envío ${money(c)}` : 'Envío gratis';
  }
  function shipsToLabel(p) {
    if (p.ships_nationwide === false) return Array.isArray(p.ships_states) && p.ships_states.length ? `Envía a: ${p.ships_states.map(stateLabel).join(', ')}` : 'Sin estados de envío configurados';
    return 'Envía a todo México';
  }
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  /* Días hábiles (lunes a viernes) transcurridos desde una fecha hasta hoy */
  function businessDaysSince(iso, now = new Date()) {
    const d = parseDate(iso); if (!d) return 0;
    const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let n = 0;
    while (x < end) { x.setDate(x.getDate() + 1); if (x.getDay() % 6) n++; }
    return n;
  }
  function addBusinessDays(iso, days) {
    const d = parseDate(iso); if (!d) return null;
    const x = new Date(d); let k = 0;
    while (k < days) { x.setDate(x.getDate() + 1); if (x.getDay() % 6) k++; }
    return x;
  }
  /* Fin del plazo de revocación (5 días hábiles): el backend lo manda en revocation_until; si no, se calcula */
  function returnDeadline(o) {
    if (o.revocation_until) return parseDate(o.revocation_until);
    return o.delivered_at ? addBusinessDays(o.delivered_at, RETURN_WINDOW_DAYS) : null;
  }
  function canCancel(o) { return o.can_cancel ?? ['pending_payment', 'paid', 'preparing'].includes(o.status); }
  function canConfirmDelivery(o) { return o.can_confirm_delivery ?? o.status === 'shipped'; }
  const returnNote = o => o.return_decision_note || o.return_note || '';
  /* Personas físicas: RFC de 13 caracteres; morales: 12 */
  function personType(rfc) { const r = String(rfc || '').trim().toUpperCase(); return RFC_RE.test(r) ? (r.length === 13 ? 'fisica' : 'moral') : null; }
  function regimenesFor(type) {
    const ok = type === 'fisica' ? REGIMENES_FISICA : type === 'moral' ? REGIMENES_MORAL : null;
    return satOptions(ok ? SAT_REGIMENES.filter(([k]) => ok.includes(k)) : SAT_REGIMENES);
  }
  /* Rellena un <select> de régimen con las claves válidas para el tipo de persona, conservando la elegida si sigue siendo válida */
  function fillRegimen(sel, type, placeholder) {
    const el = $(sel); if (!el) return;
    const prev = el.value;
    fillSelect(el, regimenesFor(type), placeholder);
    if ([...el.options].some(o => o.value === prev)) el.value = prev;
  }
  function canReturn(o) {
    if (typeof o.can_return === 'boolean') return o.can_return;
    if (!['delivered', 'completed'].includes(o.status)) return false;
    const end = returnDeadline(o);
    return !end || new Date() <= new Date(end.getFullYear(), end.getMonth(), end.getDate(), 23, 59, 59);
  }
  function invoiceOf(o) {
    const inv = o.invoice || o.invoice_request || null;
    if (inv && typeof inv === 'object') return { ...inv, status: inv.status || o.invoice_status || 'requested' };
    if (o.invoice_status) return { status: o.invoice_status, uuid: o.invoice_uuid, note: o.invoice_note };
    return null;
  }
  function invoiceable(o) { return ['paid', 'preparing', 'shipped', 'delivered', 'completed'].includes(o.status); }
  function orderSubtotal(o) { return num(o.subtotal) ?? (o.items || []).reduce((s, i) => s + Number(i.unit_price) * i.quantity, 0); }
  function itemName(i) { return i.product_name || (i.product ? i.product.name : '') || `Producto #${i.product_id}`; }
  function orderItems(o) { return (o.items || []).map(i => `<span class="badge">${i.quantity}× ${esc(itemName(i))}</span>`).join(''); }
  function orderItemsList(o) {
    return (o.items || []).map(i => `<div class="row"><div class="thumb" style="width:44px;height:44px">${imgOrDog(photo(i.product), 24)}</div><div class="grow"><b class="ellipsis">${esc(itemName(i))}</b><div class="small muted">${i.quantity} × ${money(i.unit_price)}</div></div><b>${money(Number(i.unit_price) * i.quantity)}</b></div>`).join('');
  }
  function addressText(o) {
    if (o.shipping_street) {
      return [`${o.shipping_street} ${o.shipping_ext_number || ''}${o.shipping_int_number ? ` int. ${o.shipping_int_number}` : ''}`.trim(),
        o.shipping_neighborhood, [o.shipping_postal_code, o.shipping_city].filter(Boolean).join(' '), stateLabel(o.shipping_state || '')].filter(Boolean).join(', ')
        + (o.shipping_references ? ` · ${o.shipping_references}` : '');
    }
    return o.shipping_address || '';
  }
  function orderTracking(o) {
    if (!o.shipped_at && !o.tracking_number && !o.delivered_at && !o.carrier) return '';
    const when = o.delivered_at ? `Entregado el ${fmtDate(o.delivered_at)}` : `Enviado${o.shipped_at ? ' el ' + fmtDate(o.shipped_at) : ''}`;
    const url = safeUrl(o.tracking_url);
    return `<div class="order-track"><svg width="18" height="18" aria-hidden="true"><use href="#truck"/></svg><div class="grow">${esc(when)}${o.carrier ? ` · ${esc(o.carrier)}` : ''}${o.tracking_number ? `<div>Guía: <b>${esc(o.tracking_number)}</b>${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener">Rastrear</a>` : ''}</div>` : ''}</div></div>`;
  }
  /* Línea de tiempo: la manda el backend ([{status, at, note}]); si no viene, se arma con las fechas del pedido */
  const TIMELINE_BY = { refuge: 'el refugio', admin: 'GuauWoow' };
  function buildTimeline(o) {
    if (Array.isArray(o.timeline) && o.timeline.length) {
      return o.timeline.map(t => ({ status: t.status, at: t.at || t.created_at || null, note: t.note || '', by: TIMELINE_BY[t.by] || '', label: TIMELINE_LABEL[t.status] || t.status }));
    }
    const ev = [];
    const add = (status, at, note = '') => { if (at) ev.push({ status, at, note, label: TIMELINE_LABEL[status] || status }); };
    add('created', o.created_at);
    add('paid', o.paid_at);
    add('preparing', o.preparing_at);
    add('shipped', o.shipped_at, [o.carrier, o.tracking_number ? `guía ${o.tracking_number}` : ''].filter(Boolean).join(' · '));
    add('delivered', o.delivered_at);
    add('completed', o.completed_at);
    add('cancelled', o.cancelled_at);
    const reason = (RETURN_REASONS.find(r => r[0] === o.return_reason) || [])[1] || '';
    add('return_requested', o.return_requested_at, reason);
    add(o.status === 'return_rejected' ? 'return_rejected' : 'return_approved', o.return_decided_at, returnNote(o));
    add('refunded', o.refunded_at);
    if (!ev.some(e => e.status === o.status) && !['pending_payment', 'created'].includes(o.status)) {
      ev.push({ status: o.status, at: o.updated_at || null, note: '', label: TIMELINE_LABEL[o.status] || o.status });
    }
    return ev;
  }
  function timelineHtml(o) {
    const ev = buildTimeline(o);
    if (!ev.length) return '<p class="small muted mt8">Sin movimientos todavía.</p>';
    return `<ol class="tl mt12">${ev.map((e, i) => `<li class="tl-item ${i === ev.length - 1 ? 'on' : ''}" data-tl="${esc(e.status)}"><i aria-hidden="true"></i><div class="grow"><b>${esc(e.label)}</b>${e.at ? `<div class="small muted">${fmtDate(e.at)} · ${fmtTime(e.at)}${e.by ? ` · por ${esc(e.by)}` : ''}</div>` : ''}${e.note ? `<div class="small">${esc(e.note)}</div>` : ''}</div></li>`).join('')}</ol>`;
  }
  /* Descarga autenticada (XML/PDF de facturas, CSV de estados de cuenta): el token va en el encabezado, no en la URL */
  async function downloadPrivate(path, filename) {
    const url = /^\/[a-z0-9]/i.test(String(path || '')) ? path : '';
    if (!url) return toast('El archivo todavía no está disponible', 'error');
    try {
      const res = await fetch(url, { headers: { Authorization: `Bearer ${state.token}` } });
      if (res.status === 401) return sessionExpired();
      if (!res.ok) throw new Error(res.status === 404 ? 'El archivo todavía no está disponible' : res.status === 429 ? 'Vas muy rápido 🐾 Espera un momento' : 'No pudimos descargar el archivo');
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 60000);
      toast('Descarga lista 📦', 'ok');
    } catch (e) { toast(e.message, 'error'); }
  }
  function fillSelect(sel, options, placeholder) {
    const el = typeof sel === 'string' ? $(sel) : sel;
    if (!el) return;
    el.innerHTML = (placeholder ? `<option value="">${esc(placeholder)}</option>` : '') + options.map(([val, label]) => `<option value="${esc(val)}">${esc(label)}</option>`).join('');
  }
  const satOptions = list => list.map(([k, l]) => [k, `${k} · ${l}`]);
  function lastPeriods(n = 12) {
    const out = []; const d = new Date(); d.setDate(1);
    for (let i = 0; i < n; i++) { out.push([`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`, d.toLocaleDateString('es-MX', { month: 'long', year: 'numeric' })]); d.setMonth(d.getMonth() - 1); }
    return out;
  }
  function v(sel) { const el = $(sel); return el ? (el.value || '').trim() : ''; }

  /* ============================================================
     Catálogo
     ============================================================ */
  const PRODUCTS_PAGE = 100;  // máximo que entrega el backend por página
  const PRODUCTS_MAX_PAGES = 20;
  const refugeNames = {};
  async function loadAllProducts() {
    // GET /products viene paginado (50 por defecto, 100 máximo): juntamos todas las páginas
    const all = [];
    for (let page = 0; page < PRODUCTS_MAX_PAGES; page++) {
      const rows = await api(`/products?skip=${page * PRODUCTS_PAGE}&limit=${PRODUCTS_PAGE}`);
      all.push(...rows);
      if (rows.length < PRODUCTS_PAGE) break;
    }
    return all;
  }
  async function loadRefugeNames() {
    try { (await api('/refuges?limit=100')).forEach(r => { refugeNames[r.id] = r.name; }); } catch { }
  }
  function sellerName(id, fallback) { return fallback || refugeNames[id] || (id ? `Refugio #${id}` : 'el refugio'); }

  async function loadShop() {
    updateCartCount();
    const list = $('#shop-list');
    list.innerHTML = Array.from({ length: 4 }, () => `<div class="skel" style="height:240px"><i class="skel-paw">${FX.PAW}</i></div>`).join('');
    try {
      const [products] = await Promise.all([loadAllProducts(), loadRefugeNames()]);
      state.products = products;
      syncCart();
      if (!products.length) { list.innerHTML = `<div style="grid-column:1/-1">${FX.empty('La tienda está vacía', 'Pronto habrá productos solidarios')}</div>`; return; }
      list.innerHTML = products.map((p, i) => {
        const ready = sellerReady(p);
        const out = p.stock < 1;
        return `<div class="card p pop-in prod-card" style="animation-delay:${Math.min(i, 12) * 50}ms;padding:10px">
        <div class="thumb prod-open" data-product="${p.id}" role="button" tabindex="0" aria-label="Ver ${esc(p.name)}" style="width:100%;height:120px;border-radius:16px">${imgOrDog(photo(p), 60)}</div>
        <b class="mt8 prod-open" data-product="${p.id}" style="display:block;line-height:1.15;min-height:36px">${esc(p.name)}</b>
        <div class="small muted ellipsis">🏠 ${esc(sellerName(p.refuge_id, p.refuge_name))}</div>
        <div class="between mt8"><b style="color:var(--orange-d);font-size:17px">${money(p.price)}</b>${p.stock > 0 && p.stock < 5 ? `<span class="small muted">¡Quedan ${p.stock}!</span>` : ''}</div>
        <div class="small muted">${esc(shippingLabel(p))}</div>
        ${!ready ? '<div class="small shop-note mt8">Este refugio aún no activa cobros</div>' : ''}
        <button type="button" class="btn btn-sm btn-orange block mt8" data-add="${p.id}" ${out || !ready ? 'disabled' : ''}>${out ? 'Agotado' : !ready ? 'No disponible' : 'Agregar'}</button></div>`;
      }).join('');
      FX.decorate(list);
      $$('[data-add]', list).forEach(b => b.onclick = () => addToCart(+b.dataset.add, b));
    } catch (e) { toast(e.message, 'error'); list.innerHTML = ''; }
  }
  function openProduct(id) {
    const p = state.products.find(x => x.id == id);
    if (!p) return;
    state.product = p;
    const photos = p.photos && p.photos.length ? p.photos : [''];
    const ready = sellerReady(p);
    const days = p.handling_days ?? 3;
    $('#pd-body').innerHTML = `
      <div class="gallery" style="height:230px"><div class="track">${photos.map(u => `<div>${imgTag(u, { thumb: false, alt: p.name }) || FX.dogFace(120)}</div>`).join('')}</div></div>
      <div class="between mt12"><div class="h2" id="pd-name">${esc(p.name)}</div><b style="color:var(--orange-d);font-size:20px">${money(p.price)}</b></div>
      <div class="small muted">Precio final en MXN (incluye impuestos aplicables)</div>
      ${p.description ? `<p class="body mt8" style="white-space:pre-line">${esc(p.description)}</p>` : ''}
      <div class="card p small mt12 col" style="gap:4px;background:var(--blue)"><span>🚚 ${esc(shippingLabel(p))} · despacho en ${plural(days, 'día hábil', 'días hábiles')}</span><span>📍 ${esc(shipsToLabel(p))}</span>
        <span>🛡️ ${esc(warrantyLabel(p))}${p.warranty_days && p.warranty_text ? ` · ${esc(p.warranty_text)}` : ''}</span>${categoryLabel(p) ? `<span>🏷️ ${esc(categoryLabel(p))}</span>` : ''}
        ${p.is_perishable ? '<span>🥫 Perecedero: una vez recibido y pagado no admite revocación (sí reclamación si llega dañado).</span>' : ''}</div>
      <div class="small muted mt8">${p.stock > 0 ? `${p.stock} disponibles` : 'Agotado'} · Vende <button type="button" class="link" data-refuge="${p.refuge_id}">${esc(sellerName(p.refuge_id, p.refuge_name))}</button></div>
      <div class="small muted mt8" id="pd-fee">💚 De cada pieza (${money(p.price)}): ${esc(feeText(p.price, p.platform_fee_percent))}</div>
      ${!ready ? '<div class="card p small mt12 shop-note">💳 Este refugio aún no activa cobros. En cuanto conecte Mercado Pago podrás comprarle.</div>' : ''}
      <button type="button" class="btn block btn-orange mt16" id="pd-add" ${p.stock < 1 || !ready ? 'disabled' : ''}>${p.stock < 1 ? 'Agotado' : !ready ? 'No disponible por ahora' : 'Agregar al carrito'}</button>`;
    $('#product-detail').classList.add('open');
    FX.decorate($('#product-detail'));
    $('#pd-add').onclick = e => addToCart(p.id, e.currentTarget);
  }

  /* ============================================================
     Carrito (un solo refugio por pedido)
     ============================================================ */
  function saveCart() { try { localStorage.setItem('patitas_cart', JSON.stringify(state.cart)); } catch { } updateCartCount(); }
  function updateCartCount() {
    const n = state.cart.reduce((s, i) => s + i.quantity, 0);
    const el = $('#cart-count'); if (!el) return;
    el.textContent = n; el.classList.toggle('hidden', !n);
  }
  function cartSeller() { return state.cart.length ? state.cart[0].refuge_id : null; }
  function cartItemFrom(p) {
    return {
      product_id: p.id, refuge_id: p.refuge_id, refuge_name: sellerName(p.refuge_id, p.refuge_name), name: p.name, price: parseFloat(p.price),
      quantity: 1, photo: photo(p), stock: p.stock, shipping_cost: num(p.shipping_cost), ships_nationwide: p.ships_nationwide !== false,
      ships_states: Array.isArray(p.ships_states) ? p.ships_states : [], handling_days: p.handling_days ?? 3,
      fee_percent: num(p.platform_fee_percent) ?? 0, is_perishable: !!p.is_perishable, warranty_days: p.warranty_days || null,
    };
  }
  /* Refresca precios, inventario y envío con el catálogo recién cargado y quita lo que ya no existe */
  function syncCart() {
    if (!state.cart.length || !state.products.length) return;
    let changed = false;
    state.cart = state.cart.filter(it => {
      const p = state.products.find(x => x.id === it.product_id);
      if (!p || p.stock < 1 || !sellerReady(p)) { changed = true; return false; }
      Object.assign(it, { ...cartItemFrom(p), quantity: Math.min(it.quantity, p.stock) });
      return true;
    });
    const seller = cartSeller();
    if (seller != null && state.cart.some(i => i.refuge_id !== seller)) { state.cart = state.cart.filter(i => i.refuge_id === seller); changed = true; }
    if (changed) toast('Actualizamos tu carrito: quitamos productos que ya no están disponibles', 'info');
    saveCart();
  }
  function addToCart(id, btn) {
    const p = state.products.find(x => x.id === id); if (!p) return;
    if (!sellerReady(p)) return toast('Este refugio aún no activa cobros', 'error');
    if (p.stock < 1) return toast('Este producto está agotado', 'error');
    const seller = cartSeller();
    if (seller != null && seller !== p.refuge_id) {
      const other = state.cart[0].refuge_name || sellerName(seller);
      if (!confirm(`Tu carrito tiene productos de ${other}. Cada pedido es a un solo refugio (cada uno envía por separado). ¿Vaciamos el carrito y agregamos «${p.name}»?`)) return;
      state.cart = [];
    }
    const it = state.cart.find(i => i.product_id === id);
    if (it) { if (it.quantity >= p.stock) return toast('No hay más inventario', 'error'); it.quantity++; }
    else state.cart.push(cartItemFrom(p));
    saveCart();
    if (btn) FX.boneBurst(btn, 5);
    const cb = $('#cart-btn'); if (cb) { cb.style.animation = 'heartBeat .5s var(--spring)'; setTimeout(() => cb.style.animation = '', 500); }
    toast(`${p.name} al carrito 🛒`, 'ok');
  }
  function cartSubtotal() { return state.cart.reduce((s, i) => s + i.price * i.quantity, 0); }
  /* El envío se cobra una vez por pedido: el costo más alto entre los productos (null = por calcular) */
  function cartShipping() {
    const costs = state.cart.map(i => num(i.shipping_cost)).filter(c => c != null);
    return costs.length ? Math.max(...costs) : null;
  }
  function cartTotal() { return cartSubtotal() + (cartShipping() || 0); }
  function summaryHtml() {
    const ship = cartShipping();
    return `<div class="between"><span>Subtotal</span><b>${money(cartSubtotal())}</b></div>
      <div class="between"><span>Envío</span><b>${ship == null ? 'Se calcula antes de pagar' : ship > 0 ? money(ship) : 'Gratis'}</b></div>
      <div class="between total"><span>Total MXN</span><b>${money(cartTotal())}</b></div>`;
  }
  function renderCart() {
    const box = $('#cart-items');
    $('#cart-seller').innerHTML = state.cart.length ? `Vende <b>${esc(state.cart[0].refuge_name || sellerName(cartSeller()))}</b> · un refugio por pedido` : '';
    if (!state.cart.length) { box.innerHTML = FX.empty('Tu carrito está vacío'); $('#cart-sum').innerHTML = ''; $('#cart-checkout').disabled = true; return; }
    $('#cart-checkout').disabled = false;
    box.innerHTML = state.cart.map(i => `<div class="card p row"><div class="thumb" style="width:46px;height:46px">${imgOrDog(i.photo, 26)}</div><div class="grow"><b class="ellipsis">${esc(i.name)}</b><div class="small muted">${money(i.price)} c/u${num(i.shipping_cost) != null ? ` · ${num(i.shipping_cost) > 0 ? 'envío ' + money(i.shipping_cost) : 'envío gratis'}` : ''}</div></div>
      <div class="row" style="gap:6px"><button type="button" class="iconbtn sm" data-q="${i.product_id}" data-d="-1" aria-label="Quitar uno">−</button><b>${i.quantity}</b><button type="button" class="iconbtn sm" data-q="${i.product_id}" data-d="1" aria-label="Agregar uno">+</button></div></div>`).join('');
    $('#cart-sum').innerHTML = summaryHtml();
    $$('[data-q]', box).forEach(b => b.onclick = () => {
      const it = state.cart.find(i => i.product_id == b.dataset.q);
      if (!it) return;
      if (+b.dataset.d > 0 && it.stock != null && it.quantity >= it.stock) return toast('No hay más inventario', 'error');
      it.quantity += +b.dataset.d;
      if (it.quantity <= 0) state.cart = state.cart.filter(i => i !== it);
      saveCart(); renderCart();
    });
  }
  function openCart() { renderCart(); $('#cart-modal').classList.add('open'); FX.decorate($('#cart-modal')); }

  /* ============================================================
     Checkout: dirección estructurada y validación del estado atendido
     ============================================================ */
  function readAddress() {
    return {
      shipping_name: v('#co-name'), shipping_phone: v('#co-phone'), shipping_street: v('#co-street'), shipping_ext_number: v('#co-ext'),
      shipping_int_number: v('#co-int') || null, shipping_neighborhood: v('#co-neigh'), shipping_city: v('#co-city'), shipping_state: v('#co-state'),
      shipping_postal_code: v('#co-cp'), shipping_references: v('#co-refs') || null,
    };
  }
  /* Devuelve el primer error (texto) o null. `cart` sirve para comprobar que cada producto se envía al estado elegido. */
  function validateAddress(a, cart = []) {
    if (!a.shipping_name || a.shipping_name.length < 3) return 'Escribe el nombre de quien recibe';
    if ((a.shipping_phone || '').replace(/\D/g, '').length < 10) return 'Escribe un celular de contacto a 10 dígitos';
    if (!a.shipping_street || a.shipping_street.length < 3) return 'Escribe la calle';
    if (!a.shipping_ext_number) return 'Escribe el número exterior (o S/N)';
    if (!a.shipping_neighborhood) return 'Escribe la colonia';
    if (!a.shipping_city) return 'Escribe la ciudad o municipio';
    if (!MX_STATES.includes(a.shipping_state)) return 'Elige tu estado';
    if (!/^\d{5}$/.test(a.shipping_postal_code || '')) return 'El código postal debe tener 5 dígitos';
    if (a.shipping_references && a.shipping_references.length > 300) return 'Las referencias son muy largas (máximo 300 caracteres)';
    const blocked = cart.find(i => i.ships_nationwide === false && !(i.ships_states || []).includes(a.shipping_state));
    if (blocked) return `«${blocked.name}» no se envía a ${stateLabel(a.shipping_state)}. Cambia la dirección o quítalo del carrito`;
    return null;
  }
  function joinAddress(a) {
    return `${a.shipping_street} ${a.shipping_ext_number}${a.shipping_int_number ? ` int. ${a.shipping_int_number}` : ''}, ${a.shipping_neighborhood}, ${a.shipping_postal_code} ${a.shipping_city}, ${stateLabel(a.shipping_state)}${a.shipping_references ? ` · ${a.shipping_references}` : ''}`;
  }
  function openCheckout() {
    if (!state.cart.length) return toast('Tu carrito está vacío', 'error');
    $('#cart-modal').classList.remove('open');
    const days = Math.max(...state.cart.map(i => i.handling_days ?? 3));
    const dispatchBy = addBusinessDays(new Date().toISOString(), days);
    $('#co-summary').innerHTML = `<div class="small muted">Pedido a <b>${esc(state.cart[0].refuge_name || sellerName(cartSeller()))}</b></div>
      <div class="small mt8" id="co-seller">Cargando los datos del refugio vendedor...</div>
      <div class="col mt8" style="gap:4px">${state.cart.map(i => `<div class="between small"><span>${i.quantity} × ${esc(i.name)} <span class="muted">(${money(i.price)} c/u${i.warranty_days ? ` · garantía ${i.warranty_days} días` : ''})</span></span><b>${money(i.price * i.quantity)}</b></div>`).join('')}</div>
      <div class="sum mt12">${summaryHtml()}</div>
      <div class="small muted" id="co-iva">Precios finales en MXN con impuestos incluidos.</div>
      <div class="small mt8" id="co-fee">💚 ${esc(feeText(cartTotal(), Math.max(0, ...state.cart.map(i => i.fee_percent || 0))))}</div>
      <div class="small muted mt8">Despacho: ${plural(days, 'día hábil', 'días hábiles')} después del pago${dispatchBy ? ` (a más tardar el ${fmtDate(dispatchBy.toISOString())})` : ''}, más el tiempo de la paquetería. Si el refugio no lo envía a tiempo, cancelamos tu pedido y te reembolsamos.</div>`;
    $('#co-perishable').classList.toggle('hidden', !state.cart.some(i => i.is_perishable));
    renderSellerIdentity(cartSeller());
    const saved = savedAddress();
    $('#co-save-address').checked = false;  // casilla NO premarcada (consumidor-ecommerce-20)
    $('#co-forget-address').classList.toggle('hidden', !saved);
    const me = state.me || {};
    const put = (sel, val) => { const el = $(sel); if (el && !el.value) el.value = val || ''; };
    if (saved) Object.entries({ '#co-name': saved.shipping_name, '#co-phone': saved.shipping_phone, '#co-street': saved.shipping_street, '#co-ext': saved.shipping_ext_number, '#co-int': saved.shipping_int_number, '#co-neigh': saved.shipping_neighborhood, '#co-city': saved.shipping_city, '#co-cp': saved.shipping_postal_code, '#co-refs': saved.shipping_references }).forEach(([s, val]) => put(s, val));
    put('#co-name', me.full_name); put('#co-phone', me.phone); put('#co-city', me.city || state.city);
    const st = $('#co-state');
    if (!st.value) st.value = (saved && MX_STATES.includes(saved.shipping_state) && saved.shipping_state) || (MX_STATES.includes(state.city) ? state.city : '') || '';
    $('#co-terms').checked = false;
    $('#co-prepay').checked = false;
    $('#co-pay').textContent = `Pagar ${money(cartTotal())} con Mercado Pago`;
    navigate('checkout');
  }
  /* Identidad y datos fiscales del refugio vendedor antes de pagar (terminos-tienda 1.3) y el IVA incluido en el total */
  async function renderSellerIdentity(refugeId) {
    const box = $('#co-seller'); if (!box || !refugeId) return;
    let id = null;
    if (refugeId > 0) { try { id = await api(`/products/sellers/${refugeId}/identity`); } catch { id = null; } }
    if (!box.isConnected) return;
    if (!id) { box.textContent = 'Vende, cobra y factura el refugio vendedor.'; return; }
    const fiscal = id.legal_name && id.rfc ? ` · ${esc(id.legal_name)} · RFC ${esc(id.rfc)}` : '';
    box.innerHTML = `🏠 Vende, cobra y factura: <b>${esc(id.name)}</b>${fiscal}${id.city ? ` · ${esc(id.city)}` : ''}`;
    const iva = $('#co-iva');
    if (iva) {
      const total = cartTotal();
      iva.textContent = id.iva === 'exento' ? 'Precios finales en MXN. Venta exenta de IVA (el refugio es donataria autorizada).'
        : `Precios finales en MXN con IVA incluido (IVA incluido en el total: ${money(Math.round((total - total / 1.16) * 100) / 100)}).`;
    }
  }
  async function submitCheckout(e) {
    e.preventDefault();
    if (!state.cart.length) return toast('Tu carrito está vacío', 'error');
    const a = readAddress();
    const err = validateAddress(a, state.cart);
    if (err) return toast(err, 'error');
    if (!$('#co-terms').checked) return toast('Acepta las condiciones de compra para continuar', 'error');
    if (!$('#co-prepay').checked) return toast('Autoriza el cobro antes de la entrega para continuar', 'error');
    await withBtn($('#co-pay'), async () => {
      const body = {
        items: state.cart.map(({ product_id, quantity }) => ({ product_id, quantity })), ...a, shipping_address: joinAddress(a),
        accepted_terms: true, consent_prepayment: true, terms_version: (state.config.legal_versions || {}).terms || null,
      };
      const o = await api('/orders', { method: 'POST', body });
      state.cart = []; saveCart();
      if ($('#co-save-address').checked) rememberAddress(a);
      track('order_created', { simulated: !!o.simulated });
      if (o.checkout_url && safeUrl(o.checkout_url)) { FX.showLoading('Te llevamos a Mercado Pago', ['Pagas en Mercado Pago; GuauWoow no ve ni guarda tu tarjeta'], 'run'); location.href = o.checkout_url; return; }
      await FX.success('¡Pedido confirmado!', `Gracias por apoyar a los refugios · #${o.id}`);
      openOrder(o.id, { replace: true });
    });
  }

  /* ============================================================
     Mis pedidos y detalle con línea de tiempo
     ============================================================ */
  function openMyOrders() {
    openList('Mis pedidos', 'Tienda solidaria', () => api('/orders'), o => `<div class="card p tap" data-order-open="${o.id}" role="button" tabindex="0"><div class="between"><b>Pedido #${o.id}</b>${orderBadge(o.status)}</div>
      <div class="small muted mt8">${fmtDate(o.created_at)} · ${money(o.total)}${o.refuge_name ? ` · ${esc(o.refuge_name)}` : ''}</div><div class="chips mt8">${orderItems(o)}</div>${orderTracking(o)}
      ${(invoiceOf(o) || {}).status === 'issued' ? '<div class="small mt8">🧾 Factura disponible</div>' : ''}</div>`,
      { emptyTitle: 'Sin pedidos aún', emptyBtn: { action: 'shop', label: 'Ir a la tienda' } });
  }
  function openOrder(id, opts = {}) {
    $('#order-title').firstChild.textContent = `Pedido #${id}`;
    $('#order-body').innerHTML = FX.inlineLoader('Buscando tu pedido...');
    // Al venir del checkout no se regresa al formulario de pago: se cierra ese paso del historial
    if (opts.replace && current === 'checkout') back();
    navigate('order');
    refreshOrder(id, opts);
  }
  /* opts.fallbackShop: avisos y correos anteriores (/app/?order=N) también llegaron al refugio que vende; GET
     /orders/{id} es solo del comprador (403 para los demás), así que si no es suyo se abre "Mi tienda".
     Los avisos nuevos para el refugio ya traen /app/?shop=pedidos. */
  async function refreshOrder(id, opts = {}) {
    let o;
    try { o = await api(`/orders/${id}`); }
    catch (e) {
      if (current === 'order') back();
      if (opts.fallbackShop && (e.status === 403 || e.status === 404) && state.me && state.me.role === 'refuge') return openMyShop('pedidos');
      return toast(e.message, 'error');
    }
    // La factura vive en GET /orders/{id}/invoice: solo se consulta si el pedido ya tiene una solicitud
    const hasInvoice = 'invoice_status' in o ? !!o.invoice_status : invoiceable(o);
    if (hasInvoice) {
      const inv = await api(`/orders/${id}/invoice`).catch(() => null);
      if (inv && typeof inv === 'object' && inv.status) o.invoice = { ...(invoiceOf(o) || {}), ...inv };
    }
    state.order = o;
    if (current === 'order') renderOrder(o);
    // Enlace del correo de pago confirmado (/app/?order=N&receipt=1): abre el comprobante
    if (opts.receipt && o.paid_at) openReceipt(o.id).catch(e => toast(e.message, 'error'));
  }
  function invoiceCard(o, inv) {
    if (!inv || inv.status === 'none') return '';
    const text = { requested: 'Solicitud enviada al refugio. Te avisamos cuando emita tu CFDI.', issued: 'Tu factura está lista.', rejected: 'El refugio no pudo emitir la factura.' }[inv.status] || inv.status;
    const link = k => inv[`${k}_url`] || inv[`${k}_download_url`] || `/orders/${o.id}/invoice/${k}`;
    return `<div class="card p mt12" id="od-invoice-card"><div class="between"><b>🧾 Factura</b><span class="badge ${inv.status === 'issued' ? 'b-green' : inv.status === 'rejected' ? 'b-red' : 'b-yellow'}">${esc(INVOICE_LABEL[inv.status] || inv.status)}</span></div>
      <div class="small muted mt8">${esc(text)}</div>${inv.uuid ? `<div class="small mt8">Folio fiscal: <b style="word-break:break-all">${esc(inv.uuid)}</b></div>` : ''}${inv.note ? `<div class="small mt8">Nota: ${esc(inv.note)}</div>` : ''}
      ${inv.status === 'issued' ? `<div class="row mt12"><button type="button" class="btn btn-sm grow" data-inv-dl="xml" data-href="${esc(link('xml'))}">Descargar XML</button><button type="button" class="btn btn-sm btn-ghost grow" data-inv-dl="pdf" data-href="${esc(link('pdf'))}">Descargar PDF</button></div>` : ''}</div>`;
  }
  function renderOrder(o) {
    const body = $('#order-body');
    const inv = invoiceOf(o);
    const ship = num(o.shipping_total);
    const deadline = returnDeadline(o);
    const claim = o.claim_until ? parseDate(o.claim_until) : null;
    const reason = (RETURN_REASONS.find(r => r[0] === o.return_reason) || [])[1];
    let hint = ORDER_HINT[o.status] || '';
    if (['delivered', 'completed'].includes(o.status) && (deadline || claim)) {
      const now = new Date();
      hint = o.status === 'completed' ? `${hint} ` : 'Tu pedido fue entregado. ';
      if (deadline && deadline >= now) hint += `Puedes revocar la compra hasta el ${fmtDate(deadline.toISOString())}. `;
      if (claim && claim >= now) hint += `Si llegó dañado, incompleto o no corresponde, puedes reclamar hasta el ${fmtDate(claim.toISOString())}.`;
    }
    if (o.status === 'cancelled' && o.cancel_reason) hint += ` Motivo: ${CANCEL_REASON[o.cancel_reason] || 'se canceló'}${o.cancel_note ? ` (${o.cancel_note})` : ''}.`;
    if (['paid', 'preparing'].includes(o.status) && o.dispatch_due_at) hint += ` El refugio debe enviarlo a más tardar el ${fmtDate(o.dispatch_due_at)}; si no, lo cancelamos y te reembolsamos.`;
    const actions = [];
    if (canConfirmDelivery(o)) actions.push('<button type="button" class="btn btn-sm btn-green" id="od-confirm">Ya lo recibí</button>');
    if (canReturn(o)) actions.push('<button type="button" class="btn btn-sm btn-lila" id="od-return">Devolver o reportar un problema</button>');
    if (invoiceable(o) && (!inv || inv.status === 'none' || inv.status === 'rejected')) actions.push('<button type="button" class="btn btn-sm btn-white" id="od-invoice">¿Necesitas factura?</button>');
    if (canCancel(o)) actions.push('<button type="button" class="btn btn-sm btn-ghost" id="od-cancel">Cancelar pedido</button>');
    if (o.paid_at) actions.push('<button type="button" class="btn btn-sm btn-white" id="od-receipt">Ver comprobante</button>');
    const bonus = o.bonus_info;
    body.innerHTML = `
      <div class="card p pop-in"><div class="between"><b>Pedido #${o.id}</b>${orderBadge(o.status)}</div>
        <div class="small muted mt8">${fmtDate(o.created_at)}${o.refuge_name || o.refuge_id ? ` · Vende ${esc(sellerName(o.refuge_id, o.refuge_name))}` : ''}</div>
        <p class="small mt8" id="od-hint">${esc(hint.trim())}</p>
        ${o.review_note && o.status === 'amount_mismatch' ? `<div class="small muted mt8">${esc(o.review_note)}</div>` : ''}</div>
      ${o.status === 'pending_payment' && safeUrl(o.checkout_url) ? `<a class="btn block btn-orange mt12" href="${esc(o.checkout_url)}">Terminar el pago</a>` : ''}
      <div class="card p mt12 col" style="gap:10px">${orderItemsList(o)}
        <div class="sum"><div class="between"><span>Subtotal</span><b>${money(orderSubtotal(o))}</b></div>
        ${ship != null ? `<div class="between"><span>Envío</span><b>${ship > 0 ? money(ship) : 'Gratis'}</b></div>` : ''}
        <div class="between total"><span>Total MXN</span><b>${money(o.total)}</b></div></div>
        ${num(o.fee_percent) != null ? `<div class="small muted">${num(o.fee_percent) > 0 ? `GuauWoow recibió ${num(o.fee_percent)} % (${money(o.fee_amount)}) de comisión; el resto va a la cuenta de Mercado Pago del refugio.` : 'GuauWoow no cobró comisión: el pago va a la cuenta de Mercado Pago del refugio.'}</div>` : ''}</div>
      <div class="card p mt12"><b class="small">ENVÍO A</b><div class="small mt8">${esc(o.shipping_name || '')}${o.shipping_phone ? ` · ${esc(o.shipping_phone)}` : ''}</div><div class="small">${esc(addressText(o))}</div>${orderTracking(o)}</div>
      ${o.return_reason ? `<div class="card p mt12" style="background:var(--sand)"><b class="small">DEVOLUCIÓN</b><div class="small mt8">${esc(reason || o.return_reason)}${o.return_details ? ` · ${esc(o.return_details)}` : ''}</div>${returnNote(o) ? `<div class="small mt8">Respuesta del refugio: ${esc(returnNote(o))}</div>` : ''}</div>` : ''}
      ${bonus ? `<div class="card p mt12 small" id="od-bonus" style="background:var(--yellow)"><div class="between"><b>🎁 Bonificación (LFPC art. 92 Ter)</b><span class="badge ${(BONUS_STATUS[bonus.status] || [])[1] || 'b-yellow'}">${esc((BONUS_STATUS[bonus.status] || [bonus.status])[0])}</span></div>
        <div class="mt8">Por tu reclamación, el refugio vendedor debe pagarte una bonificación de al menos <b>${money(bonus.amount)}</b> (20 % del precio pagado)${bonus.status === 'pendiente' && bonus.due_at ? `, a más tardar el ${fmtDate(bonus.due_at)}` : ''}. Le damos seguimiento.</div>
        ${bonus.payment_reference ? `<div class="mt8">Referencia del pago: <b>${esc(bonus.payment_reference)}</b></div>` : ''}${bonus.status === 'improcedente' && bonus.note ? `<div class="mt8">${esc(bonus.note)}</div>` : ''}</div>` : ''}
      ${o.refund_amount != null ? `<div class="card p mt12 small" style="background:var(--lila)">💸 ${o.status !== 'refunded' && o.status !== 'cancelled' && Number(o.refund_amount) < Number(o.total) ? 'Reembolso parcial' : 'Reembolso'} de <b>${money(o.refund_amount)}</b> a tu medio de pago${o.refund_status && !['approved', 'refunded'].includes(o.refund_status) ? ` (${esc({ pending: 'en proceso', in_process: 'en proceso', error: 'lo está revisando nuestro equipo', rejected: 'lo está revisando nuestro equipo', cancelled: 'cancelado' }[o.refund_status] || 'en proceso')})` : ''}. Puede tardar unos días en reflejarse.</div>` : ''}
      <div class="card p mt12"><b class="small">SEGUIMIENTO</b>${timelineHtml(o)}</div>
      ${invoiceCard(o, inv)}
      ${actions.length ? `<div class="row mt16" style="flex-wrap:wrap;gap:8px">${actions.join('')}</div>` : ''}
      <p class="small muted mt16">¿Dudas con tu pedido? Escríbenos desde Perfil → Ayuda. Nunca te pediremos pagos fuera de la app.</p>`;
    FX.decorate(body);
    const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = e => fn(e.currentTarget); };
    on('#od-cancel', btn => confirm('¿Cancelar este pedido? Si ya pagaste, te reembolsamos a tu medio de pago.') && withBtn(btn, async () => {
      try { await api(`/orders/${o.id}/cancel`, { method: 'POST' }); } catch (e) { throw new Error(notReady(e)); }
      toast('Pedido cancelado', 'ok'); refreshOrder(o.id);
    }));
    on('#od-confirm', btn => withBtn(btn, async () => {
      try { await api(`/orders/${o.id}/confirm-delivery`, { method: 'POST' }); } catch (e) { throw new Error(notReady(e)); }
      await FX.success('¡Qué bien!', 'Gracias por confirmar la entrega 📦'); refreshOrder(o.id);
    }));
    on('#od-return', () => openReturnModal(o));
    on('#od-receipt', btn => withBtn(btn, () => openReceipt(o.id)));
    on('#od-invoice', () => openInvoiceModal(o));
    $$('[data-inv-dl]', body).forEach(b => b.onclick = () => downloadPrivate(b.dataset.href, `factura-pedido-${o.id}.${b.dataset.invDl}`));
  }

  /* ---------- comprobante (GET /orders/{id}/comprobante; consumidor-ecommerce-07) ---------- */
  let receiptData = null;
  function receiptHtml(r) {
    const op = r.operator || {}, s = r.seller || {}, pay = r.payment || {}, rights = r.rights || {}, terms = r.terms || {};
    const line = (k, v) => v ? `<div class="between small" style="gap:12px"><span class="muted">${esc(k)}</span><b style="text-align:right">${esc(v)}</b></div>` : '';
    const link = (url, label) => safeUrl(url) ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener">${esc(label)}</a>` : esc(label);
    return `<div class="card p col" style="gap:6px">
        ${line('Folio', r.folio)}${line('Fecha de pago', r.paid_at ? `${fmtDate(r.paid_at)} · ${fmtTime(r.paid_at)}` : '')}${line('Estado', r.status_label)}
        ${line('Vende, cobra y factura', [s.name, s.legal_name, s.rfc ? `RFC ${s.rfc}` : ''].filter(Boolean).join(' · '))}
      </div>
      <div class="card p col mt8" style="gap:6px">${(r.items || []).map(i => `<div class="between small"><span>${i.quantity} × ${esc(i.name)}<br><span class="muted">${esc(i.warranty || NO_WARRANTY)}${i.is_perishable ? ' · perecedero' : ''}</span></span><b>${money(i.total)}</b></div>`).join('')}
        <div class="sum"><div class="between"><span>Subtotal</span><b>${money(r.subtotal)}</b></div><div class="between"><span>Envío</span><b>${Number(r.shipping_total) > 0 ? money(r.shipping_total) : 'Gratis'}</b></div>
        <div class="between total"><span>Total pagado ${esc(r.currency || 'MXN')}</span><b>${money(r.total)}</b></div></div>
        <div class="small muted">${r.iva === 'exento' ? 'Venta exenta de IVA (donataria autorizada).' : `IVA incluido: ${money(r.iva_amount)}`}</div></div>
      <div class="card p col mt8" style="gap:6px">${line('Medio de pago', pay.provider)}${line('ID de pago de Mercado Pago', pay.payment_id)}${line('Cobra', pay.collector)}
        ${line('Entrega en', (r.shipping || {}).address)}${line('Envío a más tardar', r.dispatch_due_at ? fmtDate(r.dispatch_due_at) : '')}
        ${line('Paquetería y guía', [(r.tracking || {}).carrier, (r.tracking || {}).tracking_number].filter(Boolean).join(' · '))}</div>
      <div class="card p small col mt8" style="gap:6px;background:var(--blue)"><span>${esc(rights.cancel || '')}</span><span>${esc(rights.revocation || '')}</span><span>${esc(rights.claims || '')}</span><span>${esc(rights.how || '')}</span>
        ${r.bonus ? `<span>🎁 Bonificación registrada: ${money(r.bonus.amount)} (${esc((BONUS_STATUS[r.bonus.status] || [r.bonus.status])[0])}).</span>` : ''}
        <span>${esc((r.invoice || {}).how || '')}</span>
        <span>Condiciones aceptadas: versión ${esc(terms.version || '-')} · ${link(terms.url, 'condiciones de compra')} · ${link(terms.returns_url, 'envíos, devoluciones y garantías')}</span></div>
      <div class="small muted mt8">Opera la tienda: ${esc([op.legal_name, op.rfc ? `RFC ${op.rfc}` : '', op.address, op.phone, op.email].filter(Boolean).join(' · '))}. ${r.profeco ? `También puedes acudir a ${esc(r.profeco.name)}: ${esc(r.profeco.phone)}.` : ''}</div>
      <p class="small mt8"><b>${esc(r.notice || 'Este comprobante no es una factura (CFDI).')}</b></p>`;
  }
  async function openReceipt(orderId) {
    let r;
    try { r = await api(`/orders/${orderId}/comprobante`); } catch (e) { throw new Error(notReady(e)); }
    receiptData = r;
    $('#rc-title').textContent = `Comprobante ${r.folio}`;
    $('#rc-body').innerHTML = receiptHtml(r);
    $('#receipt-modal').classList.add('open');
    FX.decorate($('#receipt-modal'));
  }
  /* Descarga el comprobante como archivo HTML (sin scripts) para guardarlo o imprimirlo */
  function downloadReceipt() {
    if (!receiptData) return;
    const doc = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(receiptData.folio)} · GuauWoow</title><style>body{font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:24px auto;padding:0 16px;color:#3b2a1a}.between{display:flex;justify-content:space-between;gap:12px}.card{border:1px solid #eadfd3;border-radius:12px;padding:12px;margin-top:8px}.muted{color:#7a6a5a}.small{font-size:14px}.total{font-weight:bold}.col{display:flex;flex-direction:column;gap:6px}.hidden{display:none}</style></head><body><h1>Comprobante ${esc(receiptData.folio)}</h1>${receiptHtml(receiptData)}</body></html>`;
    const url = URL.createObjectURL(new Blob([doc], { type: 'text/html' }));
    const a = document.createElement('a');
    a.href = url; a.download = `comprobante-${receiptData.folio}.html`;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  /* ---------- devolución ---------- */
  function openReturnModal(o) {
    state.order = o;
    $('#return-form').reset();
    $('#ret-order').textContent = `#${o.id}`;
    clearPhotos('ret');
    $('#return-modal').classList.add('open');
    FX.decorate($('#return-modal'));
  }
  async function submitReturn(e) {
    e.preventDefault();
    const o = state.order; if (!o) return;
    const reason = v('#ret-reason');
    const details = v('#ret-details');
    if (!reason) return toast('Elige el motivo', 'error');
    if (reason !== 'arrepentimiento' && details.length < 10) return toast('Cuéntanos un poco más qué pasó (mínimo 10 caracteres)', 'error');
    await withBtn($('#ret-submit'), async () => {
      const photos = await uploadFiles(photoStore.ret);
      try { await api(`/orders/${o.id}/return`, { method: 'POST', body: { reason, details: details || null, photos } }); }
      catch (err) { throw new Error(notReady(err)); }
      $('#return-modal').classList.remove('open');
      toast('Solicitud enviada. El refugio la revisará 🐾', 'ok');
      refreshOrder(o.id);
    });
  }

  /* ---------- factura del comprador ---------- */
  function openInvoiceModal(o) {
    state.order = o;
    $('#invoice-form').reset();
    $('#inv-order').textContent = `#${o.id}`;
    // Si el refugio rechazó una solicitud anterior, se precargan esos datos para corregirlos
    const prev = invoiceOf(o) || {};
    fillRegimen('#inv-regimen', personType(prev.rfc), 'Elige tu régimen fiscal');
    Object.entries({ '#inv-rfc': prev.rfc, '#inv-name': prev.legal_name, '#inv-regimen': prev.regimen_fiscal, '#inv-cp': prev.postal_code, '#inv-uso': prev.uso_cfdi }).forEach(([sel, val]) => { if (val) $(sel).value = val; });
    $('#inv-email').value = prev.email || (state.me && state.me.email) || '';
    $('#invoice-modal').classList.add('open');
    FX.decorate($('#invoice-modal'));
  }
  function readInvoiceRequest() {
    return { rfc: v('#inv-rfc').toUpperCase(), legal_name: v('#inv-name').toUpperCase(), regimen_fiscal: v('#inv-regimen'), postal_code: v('#inv-cp'), uso_cfdi: v('#inv-uso'), email: v('#inv-email').toLowerCase() };
  }
  function validateInvoiceRequest(b) {
    if (!RFC_RE.test(b.rfc)) return 'Escribe un RFC válido (12 o 13 caracteres)';
    if (b.legal_name.length < 3) return 'Escribe tu nombre o razón social tal como aparece en el SAT';
    if (!b.regimen_fiscal) return 'Elige tu régimen fiscal';
    if (!(personType(b.rfc) === 'moral' ? REGIMENES_MORAL : REGIMENES_FISICA).includes(b.regimen_fiscal)) return 'Ese régimen fiscal no corresponde a tu tipo de RFC';
    if (!/^\d{5}$/.test(b.postal_code)) return 'El código postal fiscal debe tener 5 dígitos';
    if (!b.uso_cfdi) return 'Elige el uso del CFDI';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(b.email)) return 'Escribe un correo válido para recibir tu factura';
    return null;
  }
  async function submitInvoiceRequest(e) {
    e.preventDefault();
    const o = state.order; if (!o) return;
    const body = readInvoiceRequest();
    const err = validateInvoiceRequest(body);
    if (err) return toast(err, 'error');
    await withBtn($('#inv-submit'), async () => {
      try { await api(`/orders/${o.id}/invoice-request`, { method: 'POST', body }); }
      catch (er) { throw new Error(notReady(er)); }
      $('#invoice-modal').classList.remove('open');
      toast('Solicitud enviada. El refugio emitirá tu factura 🧾', 'ok');
      refreshOrder(o.id);
    });
  }

  /* ============================================================
     Panel del refugio: Mi tienda
     ============================================================ */
  const MS_TABS = ['productos', 'pedidos', 'facturas', 'fiscal', 'cobros', 'cuenta'];
  let msTab = 'productos';
  let myRefuge = null;
  function openMyShop(tab) {
    if (!state.me) return;
    navigate('my-shop');
    loadMyShop(MS_TABS.includes(tab) ? tab : undefined);
  }
  async function loadMyShop(tab) {
    const body = $('#ms-body');
    body.innerHTML = FX.inlineLoader('Abriendo tu tienda...');
    $('#ms-sub').textContent = '';
    $('#ms-tabs').classList.add('hidden');
    try { myRefuge = await api('/refuges/me'); }
    catch (e) {
      if (e.status === 404) {
        body.innerHTML = FX.empty('Aún no registras un refugio', 'Regístralo para vender en la tienda solidaria', { action: 'refuge-register', label: 'Registrar refugio' });
        FX.decorate(body);
      } else { body.innerHTML = ''; toast(e.message, 'error'); }
      return;
    }
    $('#ms-sub').textContent = myRefuge.name;
    if (myRefuge.status !== 'approved') {
      body.innerHTML = `<div class="empty">${FX.sniffDog()}<h3>${myRefuge.status === 'pending' ? 'Estamos revisando tu refugio' : 'Tu refugio no está activo'}</h3><p>${myRefuge.status === 'pending' ? 'En cuanto lo aprobemos podrás vender en la tienda solidaria.' : 'Revisa tus notificaciones para conocer el motivo.'}</p></div>`;
      return;
    }
    $('#ms-tabs').classList.remove('hidden');
    setMsTab(tab || msTab);
  }
  function setMsTab(tab) {
    msTab = tab;
    $$('#ms-tabs .chip').forEach(c => { const on = c.dataset.msTab === tab; c.classList.toggle('on', on); c.setAttribute('aria-selected', String(on)); });
    const fn = { productos: loadMsProducts, pedidos: loadMsOrders, facturas: loadMsInvoices, fiscal: loadMsFiscal, cobros: loadMsPayments, cuenta: loadMsStatements }[tab];
    if (fn) fn();
  }
  const msError = (e, fallback) => `<p class="small muted">${esc(isNotReady(e) ? fallback : e.message)}</p>`;

  /* ---------- productos ---------- */
  let msProducts = [];
  function productRow(p) {
    const rv = p.review;
    return `<div class="card p row"><div class="thumb">${imgOrDog(photo(p), 30)}</div><div class="grow"><b class="ellipsis">${esc(p.name)}</b>${rv ? ` <span class="badge ${rv.status === 'rechazado' ? 'b-red' : 'b-yellow'}">${rv.status === 'rechazado' ? 'NO APROBADO' : 'EN REVISIÓN'}</span>` : p.is_hidden ? ' <span class="badge b-gray">OCULTO</span>' : ''}${p.is_active === false ? ' <span class="badge b-gray">BAJA</span>' : ''}
      <div class="small muted">${money(p.price)} · ${p.stock} en inventario${p.stock < 1 ? ' · <b>agotado</b>' : ''}</div><div class="small muted ellipsis">${esc(shippingLabel(p))} · ${esc(shipsToLabel(p))}</div>
      ${rv ? `<div class="small shop-note mt8">${esc(rv.message || '')}</div>` : !p.category ? '<div class="small shop-note mt8">Completa la categoría y la garantía de este producto (ahora son obligatorias).</div>' : ''}</div>
      <button type="button" class="iconbtn sm" data-edit-product="${p.id}" aria-label="Editar ${esc(p.name)}"><svg width="16" height="16"><use href="#edit"/></svg></button></div>`;
  }
  async function loadMsProducts() {
    const body = $('#ms-body');
    body.innerHTML = FX.skeletonList(3);
    try { msProducts = await api('/refuges/me/products'); } catch (e) { body.innerHTML = msError(e, 'Aquí verás tus productos.'); return; }
    if (msTab !== 'productos') return;
    const ready = myRefuge && myRefuge.seller_payments_ready;
    body.innerHTML = `
      ${ready === false ? `<div class="card p small shop-note">💳 Tus productos se ven en la tienda, pero nadie puede comprarlos hasta que conectes Mercado Pago. <button type="button" class="link" data-ms-go="cobros">Conectar ahora</button></div>` : ''}
      <div class="between mt12"><span class="h2">Mis productos</span><button type="button" class="btn btn-sm btn-lila" id="ms-add-product">+ Agregar</button></div>
      <div class="col mt12">${msProducts.length ? msProducts.map(productRow).join('') : '<p class="small muted">Vende playeras, correas o placas QR para financiar tu refugio. Indica el costo de envío y a qué estados envías.</p>'}</div>
      <p class="small muted mt12">Los precios son finales en MXN (incluyen impuestos aplicables). El envío se cobra una vez por pedido: el más alto de los productos del carrito.</p>`;
    FX.decorate(body);
    $('#ms-add-product').onclick = () => openProductModal(null);
    $$('[data-edit-product]', body).forEach(b => b.onclick = () => openProductModal(msProducts.find(p => p.id == b.dataset.editProduct)));
  }
  let editingProduct = null;
  function setStateChips(chosen) {
    $$('#pm-states .chip').forEach(c => { const on = chosen.has(c.dataset.state); c.classList.toggle('on', on); c.setAttribute('aria-pressed', String(on)); });
  }
  function openProductModal(p) {
    editingProduct = p;
    $('#pm-title').textContent = p ? 'Editar producto' : 'Nuevo producto';
    $('#pm-name').value = p ? p.name : '';
    $('#pm-desc').value = p ? p.description || '' : '';
    $('#pm-price').value = p ? p.price : '';
    $('#pm-stock').value = p ? p.stock : 10;
    $('#pm-shipping').value = p && p.shipping_cost != null ? Number(p.shipping_cost) : 0;
    $('#pm-handling').value = p && p.handling_days != null ? p.handling_days : 3;
    fillSelect('#pm-category', categories(), 'Elige la categoría');
    $('#pm-category').value = (p && p.category) || '';
    const warranty = !!(p && p.warranty_days);
    $('#pm-warranty-kind').value = warranty ? 'yes' : 'none';
    $('#pm-warranty-wrap').classList.toggle('hidden', !warranty);
    $('#pm-warranty-days').value = warranty ? p.warranty_days : 90;
    $('#pm-warranty-text').value = warranty ? (p.warranty_text || '') : '';
    $('#pm-perishable').checked = !!(p && p.is_perishable);
    const nationwide = !p || p.ships_nationwide !== false;
    $('#pm-nationwide').checked = nationwide;
    $('#pm-states-wrap').classList.toggle('hidden', nationwide);
    setStateChips(new Set((p && p.ships_states) || []));
    $('#pm-delete').classList.toggle('hidden', !p || p.is_active === false);
    clearPhotos('pm');
    $('#product-modal').classList.add('open');
    FX.decorate($('#product-modal'));
  }
  function readProduct() {
    const nationwide = $('#pm-nationwide').checked;
    return {
      name: v('#pm-name'), description: v('#pm-desc') || null, price: parseFloat($('#pm-price').value), stock: parseInt($('#pm-stock').value, 10) || 0,
      shipping_cost: Math.max(0, parseFloat($('#pm-shipping').value) || 0), handling_days: Math.min(30, Math.max(0, parseInt($('#pm-handling').value, 10) || 0)),
      ships_nationwide: nationwide, ships_states: nationwide ? [] : $$('#pm-states .chip.on').map(c => c.dataset.state),
      category: v('#pm-category') || null, is_perishable: $('#pm-perishable').checked,
      ...($('#pm-warranty-kind').value === 'yes'
        ? { warranty_days: parseInt($('#pm-warranty-days').value, 10) || 0, warranty_text: v('#pm-warranty-text') }
        : { warranty_days: null, warranty_text: NO_WARRANTY }),
    };
  }
  async function submitProduct(e) {
    e.preventDefault();
    const btn = $('#product-form button[type=submit]');
    await withBtn(btn, async () => {
      const body = readProduct();
      if (!body.name || !(body.price > 0)) throw new Error('Nombre y precio son obligatorios');
      if (body.stock < 0) throw new Error('El inventario no puede ser negativo');
      if (!body.ships_nationwide && !body.ships_states.length) throw new Error('Elige al menos un estado al que envías');
      if (!body.category) throw new Error('Elige la categoría del producto');
      if (body.warranty_days !== null && body.warranty_days < 90) throw new Error('Si ofreces garantía, debe ser de 90 días o más');
      if (body.warranty_days !== null && body.warranty_text.length < 15) throw new Error('Describe la garantía: qué cubre y cómo hacerla válida');
      const newPhotos = await uploadFiles(photoStore.pm);
      let saved;
      if (editingProduct) {
        if (newPhotos.length) body.photos = newPhotos;
        saved = await api(`/products/${editingProduct.id}`, { method: 'PATCH', body });
      } else {
        if (!newPhotos.length) throw new Error('Agrega al menos una foto real del producto 📸');
        saved = await api('/products', { method: 'POST', body: { ...body, photos: newPhotos } });
      }
      $('#product-modal').classList.remove('open');
      // Lista de productos prohibidos: si coincide, el producto queda en revisión y se explica por qué
      if (saved && saved.review) toast(saved.review.message || 'Tu producto quedó en revisión', 'info');
      else toast('Producto guardado', 'ok');
      if (current === 'my-shop') loadMsProducts();
    });
  }
  async function deleteProduct() {
    if (!editingProduct || !confirm(`¿Dar de baja «${editingProduct.name}»? Dejará de verse en la tienda.`)) return;
    await withBtn($('#pm-delete'), async () => {
      await api(`/products/${editingProduct.id}`, { method: 'DELETE' });
      $('#product-modal').classList.remove('open');
      toast('Producto dado de baja', 'ok');
      if (current === 'my-shop') loadMsProducts();
    });
  }

  /* ---------- pedidos del refugio ---------- */
  const MS_ORDER_FILTERS = {
    pendientes: ['paid', 'preparing'], enviados: ['shipped', 'delivered', 'completed'],
    devoluciones: ['return_requested', 'return_approved', 'return_rejected', 'refunded', 'refund_pending'], todos: null,
  };
  let msOrderFilter = 'pendientes';
  let msOrders = [];
  function fetchMyRefugeOrders() {
    // Sin filtro de estado el backend devuelve todos los pedidos pagados o posteriores (incluye devoluciones y cancelados)
    return api('/refuges/me/orders?limit=100');
  }
  function refugeOrderCard(o) {
    const buyer = o.buyer_name || (o.buyer && o.buyer.full_name) || (o.user && o.user.full_name) || 'Cliente';
    const inv = invoiceOf(o);
    const reason = (RETURN_REASONS.find(r => r[0] === o.return_reason) || [])[1];
    const net = num(o.net_amount);
    return `<div class="card p" data-order="${o.id}">
      <div class="between"><b>Pedido #${o.id}</b>${orderBadge(o.status)}</div>
      <div class="small muted mt8">${esc(buyer)} · ${fmtDate(o.created_at)} · ${money(o.total)}${net != null ? ` (neto ${money(net)})` : ''}</div>
      <div class="chips mt8">${orderItems(o)}</div>
      <div class="small mt8">📦 ${esc(o.shipping_name || '')}${o.shipping_phone ? ` · ${esc(o.shipping_phone)}` : ''}<br>${esc(addressText(o))}</div>
      ${orderTracking(o)}
      ${o.dispatch_due_at ? `<div class="small shop-note mt8">⏰ Envíalo a más tardar el <b>${fmtDate(o.dispatch_due_at)}</b>.${o.dispatch_cancel_at ? ` Si no sale antes del ${fmtDate(o.dispatch_cancel_at)}, se cancela y se reembolsa solo.` : ''}</div>` : ''}
      ${o.status === 'cancelled' && o.cancel_reason ? `<div class="small muted mt8">Cancelado: ${esc(CANCEL_REASON[o.cancel_reason] || o.cancel_reason)}${o.cancel_note ? ` · ${esc(o.cancel_note)}` : ''}</div>` : ''}
      ${o.status === 'paid' ? `<button type="button" class="btn btn-sm btn-lila mt12" data-prep="${o.id}">Empezar a preparar</button>` : ''}
      ${['paid', 'preparing'].includes(o.status) ? `<form class="order-ship" data-ship="${o.id}" novalidate>
        <input class="inp" name="carrier" maxlength="100" placeholder="Paquetería (p. ej. Estafeta)" aria-label="Paquetería">
        <input class="inp" name="tracking" maxlength="100" placeholder="Número de guía" aria-label="Número de guía">
        <input class="inp" name="url" type="url" maxlength="500" placeholder="Enlace de rastreo (opcional, https://...)" aria-label="Enlace de rastreo">
        <button type="submit" class="btn btn-sm btn-orange">Marcar como enviado</button></form>` : ''}
      ${(o.can_cancel ?? ['paid', 'preparing'].includes(o.status)) ? `<button type="button" class="btn btn-sm btn-ghost mt8" data-scancel="${o.id}">No puedo surtirlo: cancelar y reembolsar</button>` : ''}
      ${o.status === 'shipped' ? `<button type="button" class="btn btn-sm btn-green mt12" data-deliver="${o.id}">Marcar como entregado</button>` : ''}
      ${o.status === 'return_requested' ? `<div class="card p small mt12" style="background:var(--sand)"><b>Devolución solicitada:</b> ${esc(reason || o.return_reason || '')}${o.return_details ? `<br>${esc(o.return_details)}` : ''}
        ${Array.isArray(o.return_photos) && o.return_photos.length ? `<div class="row mt8" style="gap:6px;flex-wrap:wrap">${o.return_photos.map(u => safeUrl(u) ? `<a class="thumb" style="width:44px;height:44px" href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${imgOrDog(u, 20)}</a>` : '').join('')}</div>` : ''}
        <div class="row mt12"><button type="button" class="btn btn-sm btn-green grow" data-decide="${o.id}" data-approve="1">Aprobar y reembolsar</button><button type="button" class="btn btn-sm btn-ghost grow" data-decide="${o.id}" data-approve="0">Rechazar</button></div></div>` : ''}
      ${returnNote(o) && o.status !== 'return_requested' ? `<div class="small muted mt8">Tu respuesta a la devolución: ${esc(returnNote(o))}</div>` : ''}
      ${o.refund_status === 'insufficient_funds' ? '<div class="small shop-note mt8">💳 No pudimos reembolsar: tu cuenta de Mercado Pago no tiene saldo disponible suficiente. Ingresa saldo y vuelve a intentarlo.</div>' : ''}
      ${o.refund_status === 'error' ? '<div class="small shop-note mt8">El reembolso en Mercado Pago falló; nuestro equipo lo está revisando. Puedes reintentarlo.</div>' : ''}
      ${(o.can_retry_refund ?? (o.status === 'return_approved' && REFUND_RETRYABLE.includes(o.refund_status))) ? `<button type="button" class="btn btn-sm btn-orange mt8" data-retry-refund="${o.id}">Reintentar el reembolso</button>` : ''}
      ${inv && inv.status === 'requested' ? `<div class="card p small mt12" style="background:var(--lila)">🧾 Factura solicitada: <b>${esc(inv.rfc || '')}</b> ${esc(inv.legal_name || '')}<div class="mt8"><button type="button" class="btn btn-sm" data-rinv="${o.id}">Responder a la solicitud</button></div></div>` : ''}
      ${inv && inv.status === 'issued' ? `<div class="small mt8">🧾 Factura emitida${inv.uuid ? ` · ${esc(inv.uuid)}` : ''}</div>` : ''}
      ${bonusCard(msBonuses[o.id])}
    </div>`;
  }
  /* Bonificación de LFPC art. 92 Ter que el refugio debe pagar al comprador (GET /refuges/me/bonificaciones) */
  let msBonuses = {};
  function bonusCard(b) {
    if (!b) return '';
    const [label, cls] = BONUS_STATUS[b.status] || [b.status, 'b-yellow'];
    return `<div class="card p small mt12" style="background:var(--yellow)"><div class="between"><b>🎁 Bonificación al comprador</b><span class="badge ${cls}">${esc(label)}</span></div>
      <div class="mt8">La reclamación procede: además del reembolso o la reposición, debes pagar al comprador al menos <b>${money(b.amount)}</b> (20 % del precio, LFPC art. 92 Ter)${b.status === 'pendiente' && b.due_at ? ` antes del ${fmtDate(b.due_at)}` : ''}.</div>
      ${b.payment_reference ? `<div class="mt8">Referencia: <b>${esc(b.payment_reference)}</b></div>` : ''}
      ${b.status === 'pendiente' ? `<button type="button" class="btn btn-sm mt8" data-bonus-paid="${b.order_id}">Registrar el pago</button>` : ''}</div>`;
  }
  async function loadMsOrders() {
    const body = $('#ms-body');
    body.innerHTML = `<div class="chips scrollx" id="ms-order-filters">${[['pendientes', 'Por enviar'], ['enviados', 'Enviados'], ['devoluciones', 'Devoluciones'], ['todos', 'Todos']].map(([k, l]) => `<button type="button" class="chip ${k === msOrderFilter ? 'on' : ''}" data-of="${k}">${l}</button>`).join('')}</div><div class="col mt12" id="ms-orders">${FX.skeletonList(2)}</div>`;
    $$('#ms-order-filters .chip').forEach(c => c.onclick = () => { msOrderFilter = c.dataset.of; loadMsOrders(); });
    const box = $('#ms-orders');
    try {
      const [orders, bonuses] = await Promise.all([fetchMyRefugeOrders(), api('/refuges/me/bonificaciones').catch(() => [])]);
      msOrders = orders;
      msBonuses = Object.fromEntries((bonuses || []).map(b => [b.order_id, b]));
    } catch (e) { box.innerHTML = msError(e, 'Aquí verás los pedidos de tus productos.'); return; }
    if (msTab !== 'pedidos' || !box.isConnected) return;
    const allowed = MS_ORDER_FILTERS[msOrderFilter];
    const rows = allowed ? msOrders.filter(o => allowed.includes(o.status)) : msOrders;
    box.innerHTML = rows.length ? rows.map(refugeOrderCard).join('') : `<p class="small muted">${msOrders.length ? 'No hay pedidos en esta sección.' : 'Aún no hay pedidos de tus productos.'}</p>`;
    FX.decorate(box);
    const patch = async (id, payload, msg) => {
      try { await api(`/refuges/me/orders/${id}`, { method: 'PATCH', body: payload }); } catch (e) { throw new Error(notReady(e)); }
      toast(msg, 'ok'); loadMsOrders();
    };
    $$('[data-prep]', box).forEach(b => b.onclick = () => withBtn(b, () => patch(b.dataset.prep, { status: 'preparing' }, 'Pedido en preparación. Le avisamos al comprador 📦')));
    $$('[data-ship]', box).forEach(f => f.addEventListener('submit', e => {
      e.preventDefault();
      const carrier = f.carrier.value.trim(), tracking_number = f.tracking.value.trim(), tracking_url = f.url.value.trim() || null;
      if (!carrier || !tracking_number) return toast('Escribe la paquetería y el número de guía', 'error');
      if (tracking_url && !/^https:\/\/[^\s"'<>]+$/i.test(tracking_url)) return toast('El enlace de rastreo debe empezar con https://', 'error');
      withBtn($('button[type=submit]', f), () => patch(f.dataset.ship, { status: 'shipped', carrier, tracking_number, tracking_url }, 'Pedido enviado. Le avisamos al comprador 📦'));
    }));
    $$('[data-deliver]', box).forEach(b => b.onclick = () => confirm('¿Confirmas que el comprador ya recibió el pedido?') && withBtn(b, () => patch(b.dataset.deliver, { status: 'delivered' }, '¡Pedido entregado! 🎉')));
    $$('[data-decide]', box).forEach(b => b.onclick = () => openDecisionModal(+b.dataset.decide, b.dataset.approve === '1'));
    $$('[data-scancel]', box).forEach(b => b.onclick = () => openDecisionModal(+b.dataset.scancel, false, 'cancel'));
    $$('[data-retry-refund]', box).forEach(b => b.onclick = () => withBtn(b, async () => {
      let r;
      try { r = await api(`/refuges/me/orders/${b.dataset.retryRefund}/retry-refund`, { method: 'POST' }); } catch (e) { throw new Error(notReady(e)); }
      toast(r && r.status === 'refunded' ? 'Reembolso hecho. Avisamos al comprador 💸' : 'El reembolso sigue pendiente. Revisa tu saldo en Mercado Pago', r && r.status === 'refunded' ? 'ok' : 'error');
      loadMsOrders();
    }));
    $$('[data-rinv]', box).forEach(b => b.onclick = () => openRefugeInvoiceModal(msOrders.find(o => o.id == b.dataset.rinv)));
    $$('[data-bonus-paid]', box).forEach(b => b.onclick = () => {
      const ref = (prompt('Referencia del pago de la bonificación (folio de la transferencia o del reembolso en Mercado Pago):') || '').trim();
      if (!ref) return;
      if (ref.length < 4) return toast('Escribe una referencia válida', 'error');
      withBtn(b, async () => {
        try { await api(`/refuges/me/orders/${b.dataset.bonusPaid}/bonificacion`, { method: 'POST', body: { referencia: ref } }); } catch (e) { throw new Error(notReady(e)); }
        toast('Bonificación registrada. Avisamos al comprador 💛', 'ok'); loadMsOrders();
      });
    });
  }
  /* Decisión sobre una devolución: aprobar (reembolso automático) o rechazar con nota */
  /* El mismo modal sirve para cancelar un pedido que no puedes surtir (kind 'cancel': motivo + explicación) */
  let decision = null;
  function decisionReason() {
    let box = $('#dc-reason-wrap');
    if (!box) {
      $('#dc-text').insertAdjacentHTML('afterend', '<div id="dc-reason-wrap" class="mt12 hidden"><label class="lbl" for="dc-reason">Motivo</label><select id="dc-reason" class="inp"></select></div>');
      box = $('#dc-reason-wrap');
      fillSelect('#dc-reason', SELLER_CANCEL_REASONS, 'Elige el motivo');
    }
    return box;
  }
  function openDecisionModal(orderId, approve, kind = 'return') {
    decision = { orderId, approve, kind };
    const cancel = kind === 'cancel';
    decisionReason().classList.toggle('hidden', !cancel);
    $('#dc-reason').value = '';
    $('#dc-title').textContent = cancel ? 'Cancelar pedido' : approve ? 'Aprobar devolución' : 'Rechazar devolución';
    $('#dc-text').textContent = cancel ? `Si no puedes surtir el pedido #${orderId}, cancélalo: le reembolsamos el total al comprador de inmediato y verá tu explicación. Usa esta opción solo por causas reales (queda registrada).`
      : approve ? `Se reembolsará el pedido #${orderId} al comprador en Mercado Pago y se descontará de tu estado de cuenta.` : `Explica al comprador por qué no procede la devolución del pedido #${orderId}. Recuerda que PROFECO puede revisar la negativa.`;
    $('#dc-note').value = '';
    $('#dc-submit').textContent = cancel ? 'Cancelar y reembolsar' : approve ? 'Aprobar y reembolsar' : 'Rechazar';
    $('#dc-submit').className = `btn block mt12 ${approve ? 'btn-green' : 'btn-orange'}`;
    $('#decision-modal').classList.add('open');
    FX.decorate($('#decision-modal'));
  }
  async function submitDecision() {
    if (!decision) return;
    const note = v('#dc-note');
    if (decision.kind === 'cancel') {
      const reason = v('#dc-reason');
      if (!reason) return toast('Elige el motivo de la cancelación', 'error');
      if (note.length < 10) return toast('Explica el motivo al comprador (mínimo 10 caracteres)', 'error');
      return withBtn($('#dc-submit'), async () => {
        try { await api(`/refuges/me/orders/${decision.orderId}/cancel`, { method: 'POST', body: { reason, note } }); }
        catch (e) { throw new Error(notReady(e)); }
        $('#decision-modal').classList.remove('open');
        toast('Pedido cancelado. Le reembolsamos al comprador 💸', 'ok');
        loadMsOrders();
      });
    }
    if (!decision.approve && note.length < 10) return toast('Escribe el motivo del rechazo (mínimo 10 caracteres)', 'error');
    await withBtn($('#dc-submit'), async () => {
      let r;
      try { r = await api(`/refuges/me/orders/${decision.orderId}/return-decision`, { method: 'POST', body: { approve: decision.approve, note: note || null } }); }
      catch (e) { throw new Error(notReady(e)); }
      $('#decision-modal').classList.remove('open');
      if (r && r.refund_status === 'insufficient_funds') toast('Devolución aprobada, pero tu cuenta de Mercado Pago no tiene saldo para el reembolso. Ingresa saldo y reinténtalo', 'error');
      else toast(decision.approve ? 'Devolución aprobada. Reembolso en proceso' : 'Devolución rechazada. Avisamos al comprador', 'ok');
      loadMsOrders();
    });
  }

  /* ---------- facturas (CFDI que emite el refugio) ---------- */
  async function loadMsInvoices() {
    const body = $('#ms-body');
    body.innerHTML = FX.skeletonList(2);
    // Cola de solicitudes (GET /refuges/me/invoice-requests) + pedidos para mostrar el total de cada uno
    let invoices = null;
    try {
      const [orders, list] = await Promise.all([fetchMyRefugeOrders(), api('/refuges/me/invoice-requests?status=all').catch(e => { if (isNotReady(e)) return null; throw e; })]);
      msOrders = orders; invoices = list;
    } catch (e) { body.innerHTML = msError(e, 'Aquí verás las solicitudes de factura de tus compradores.'); return; }
    if (msTab !== 'facturas') return;
    const byId = new Map(msOrders.map(o => [o.id, o]));
    // Si un pedido no vino en la primera página de pedidos, basta con su id y la solicitud
    if (Array.isArray(invoices)) invoices.forEach(inv => { const o = byId.get(inv.order_id); if (o) o.invoice = inv; else { const stub = { id: inv.order_id, total: null, invoice: inv }; byId.set(inv.order_id, stub); msOrders.push(stub); } });
    const withInv = msOrders.map(o => [o, invoiceOf(o)]).filter(([, inv]) => inv && inv.status !== 'none');
    const pending = withInv.filter(([, inv]) => inv.status === 'requested');
    const done = withInv.filter(([, inv]) => inv.status !== 'requested');
    const row = ([o, inv]) => `<div class="card p"><div class="between"><b>Pedido #${o.id}${o.total != null ? ` · ${money(o.total)}` : ''}</b><span class="badge ${inv.status === 'issued' ? 'b-green' : inv.status === 'rejected' ? 'b-red' : 'b-yellow'}">${esc({ requested: 'Por emitir', issued: 'Emitida', rejected: 'Rechazada' }[inv.status] || inv.status)}</span></div>
      <div class="small mt8"><b>${esc(inv.rfc || '')}</b> ${esc(inv.legal_name || '')}<br>Régimen ${esc(inv.regimen_fiscal || '-')} · CP ${esc(inv.postal_code || '-')} · Uso ${esc(inv.uso_cfdi || '-')}<br>${esc(inv.email || '')}${inv.requested_at ? ` · solicitada ${fmtDate(inv.requested_at)}` : ''}</div>
      ${inv.uuid ? `<div class="small muted mt8" style="word-break:break-all">UUID ${esc(inv.uuid)}</div>` : ''}${inv.note ? `<div class="small muted mt8">${esc(inv.note)}</div>` : ''}
      ${inv.status === 'requested' ? `<button type="button" class="btn btn-sm mt12" data-rinv="${o.id}">Emitir o rechazar</button>` : ''}</div>`;
    body.innerHTML = `
      <div class="card p small" style="background:var(--lila)">🧾 Tú emites el CFDI de los productos que vendes: usa tu sistema de facturación o el portal del SAT y aquí sube el XML y el PDF para que el comprador los descargue. GuauWoow te factura aparte su comisión.</div>
      <div class="between mt16"><span class="h2">Por emitir</span><span class="badge b-yellow">${pending.length}</span></div>
      <div class="col mt12">${pending.length ? pending.map(row).join('') : '<p class="small muted">No tienes solicitudes de factura pendientes.</p>'}</div>
      ${done.length ? `<div class="mt20"><span class="h2">Historial</span><div class="col mt12">${done.map(row).join('')}</div></div>` : ''}`;
    FX.decorate(body);
    $$('[data-rinv]', body).forEach(b => b.onclick = () => openRefugeInvoiceModal(msOrders.find(o => o.id == b.dataset.rinv)));
  }
  let rinvOrder = null;
  function openRefugeInvoiceModal(o) {
    if (!o) return;
    rinvOrder = o;
    const inv = invoiceOf(o) || {};
    $('#rinv-form').reset();
    $('#rinv-xml-text').textContent = 'Sin archivo';
    $('#rinv-pdf-text').textContent = 'Sin archivo';
    $('#rinv-order').textContent = `#${o.id}`;
    $('#rinv-data').innerHTML = `<b>${esc(inv.rfc || '')}</b> ${esc(inv.legal_name || '')}<br>Régimen ${esc(inv.regimen_fiscal || '-')} · CP ${esc(inv.postal_code || '-')} · Uso ${esc(inv.uso_cfdi || '-')}<br>${esc(inv.email || '')}${o.total != null ? ` · Total ${money(o.total)}` : ''}`;
    toggleRinvFields();
    $('#rinv-modal').classList.add('open');
    FX.decorate($('#rinv-modal'));
  }
  function toggleRinvFields() { $('#rinv-issued-fields').classList.toggle('hidden', $('#rinv-status').value !== 'issued'); }
  async function submitRefugeInvoice(e) {
    e.preventDefault();
    const o = rinvOrder; if (!o) return;
    const status = $('#rinv-status').value;
    const note = v('#rinv-note');
    const body = { status, note: note || null };
    const xml = $('#rinv-xml').files[0], pdf = $('#rinv-pdf').files[0];
    const typedUuid = v('#rinv-uuid').toLowerCase();
    if (status === 'issued') {
      if (typedUuid && !UUID_RE.test(typedUuid)) return toast('El folio fiscal (UUID) no tiene el formato del CFDI. Déjalo vacío y lo leemos del XML', 'error');
      if (!xml) return toast('Sube el XML timbrado del CFDI', 'error');
      if (!/\.xml$/i.test(xml.name)) return toast('El archivo del CFDI debe ser .xml', 'error');
      if (pdf && !/\.pdf$/i.test(pdf.name) && pdf.type !== 'application/pdf') return toast('La representación impresa debe ser un PDF', 'error');
    } else if (note.length < 10) return toast('Explica al comprador por qué no puedes emitir la factura (mínimo 10 caracteres)', 'error');
    await withBtn($('#rinv-submit'), async () => {
      if (status === 'issued') {
        // El backend valida el XML (CFDI timbrado) y devuelve su UUID y los RFC de emisor y receptor
        const fd = new FormData(); fd.append('file', xml);
        let info;
        try { info = await api('/upload/cfdi-xml', { method: 'POST', body: fd }); } catch (err) { throw new Error(notReady(err)); }
        const inv = invoiceOf(o) || {};
        if (typedUuid && info.uuid && typedUuid !== String(info.uuid).toLowerCase()) throw new Error('El UUID que escribiste no coincide con el del XML');
        if (info.receptor_rfc && inv.rfc && String(info.receptor_rfc).toUpperCase() !== String(inv.rfc).toUpperCase()) throw new Error(`El XML está a nombre de ${info.receptor_rfc}, pero el comprador pidió la factura para ${inv.rfc}`);
        body.xml_document_id = info.id;
        body.uuid = (typedUuid || info.uuid || '').toLowerCase() || null;
        if (pdf) body.pdf_document_id = (await uploadDocuments([pdf]))[0];
      }
      try { await api(`/refuges/me/orders/${o.id}/invoice`, { method: 'POST', body }); }
      catch (err) { throw new Error(notReady(err)); }
      $('#rinv-modal').classList.remove('open');
      toast(status === 'issued' ? 'Factura registrada. El comprador ya puede descargarla 🧾' : 'Respuesta enviada al comprador', 'ok');
      if (msTab === 'facturas') loadMsInvoices(); else loadMsOrders();
    });
  }

  /* ---------- datos fiscales del refugio ---------- */
  let fiscalProfile = null;
  let csfFile = null;
  async function loadMsFiscal() {
    const body = $('#ms-body');
    body.innerHTML = FX.skeletonList(2);
    let fp = {};
    try { fp = (await api('/refuges/me/fiscal')) || {}; }
    catch (e) { if (e.status !== 404) { body.innerHTML = msError(e, ''); return; } }
    if (msTab !== 'fiscal') return;
    fiscalProfile = fp; csfFile = null;
    const moral = fp.person_type === 'moral';
    body.innerHTML = `
      <div class="card p small" style="background:var(--lila)">🔒 Estos datos solo los ve nuestro equipo y se usan para facturarte la comisión, calcular las retenciones del SAT y armar tu estado de cuenta.</div>
      <form id="fiscal-form" class="col mt16" novalidate>
        <div><span class="lbl" id="fp-type-lbl">Tipo de persona</span><div class="seg" id="fp-type" role="radiogroup" aria-labelledby="fp-type-lbl"><button type="button" role="radio" data-v="fisica" class="${moral ? '' : 'on'}" aria-checked="${!moral}">Persona física</button><button type="button" role="radio" data-v="moral" class="${moral ? 'on' : ''}" aria-checked="${moral}">Persona moral (A.C.)</button></div></div>
        <div><label class="lbl" for="fp-rfc">RFC</label><input id="fp-rfc" class="inp" maxlength="13" autocomplete="off" style="text-transform:uppercase" value="${esc(fp.rfc || '')}" placeholder="${moral ? 'ABC010101AB1' : 'ABCD010101AB1'}"></div>
        <div><label class="lbl" for="fp-name">Nombre o razón social (como en el SAT)</label><input id="fp-name" class="inp" maxlength="255" value="${esc(fp.legal_name || '')}"></div>
        <div><label class="lbl" for="fp-regimen">Régimen fiscal</label><select id="fp-regimen" class="inp"></select></div>
        <div><label class="lbl" for="fp-cp">Código postal fiscal</label><input id="fp-cp" class="inp" inputmode="numeric" maxlength="5" value="${esc(fp.postal_code || '')}"></div>
        <label class="card p row" for="fp-donataria" style="cursor:pointer"><div class="grow"><b>Somos donataria autorizada</b><div class="small muted">Con autorización vigente del SAT para recibir donativos deducibles</div></div><input type="checkbox" class="switch" id="fp-donataria" ${fp.is_donataria ? 'checked' : ''}></label>
        <div><span class="lbl">Constancia de situación fiscal (PDF o foto)</span><div class="file-pick"><span class="grow small" id="fp-csf-text">${fp.csf_document_id ? '✅ Constancia cargada' : 'Sin constancia'}</span><button type="button" class="btn btn-sm btn-ghost" id="fp-csf-btn">${fp.csf_document_id ? 'Cambiar' : 'Subir'}</button></div><input type="file" id="fp-csf" accept="image/jpeg,image/png,image/webp,application/pdf" class="hidden"></div>
        <p class="small muted">Si eres persona física, la ley obliga a GuauWoow a retenerte ISR e IVA de tus ventas en la plataforma y a entregarte cada mes el CFDI de retenciones.</p>
        <button type="submit" class="btn block" id="fp-save">Guardar datos fiscales</button>
      </form>`;
    fillRegimen('#fp-regimen', moral ? 'moral' : 'fisica', 'Elige tu régimen');
    $('#fp-regimen').value = fp.regimen_fiscal || '';
    FX.decorate(body);
    $$('#fp-type button').forEach(b => b.onclick = () => {
      $$('#fp-type button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', String(x === b)); });
      fillRegimen('#fp-regimen', b.dataset.v, 'Elige tu régimen');
    });
    $('#fp-csf-btn').onclick = () => $('#fp-csf').click();
    $('#fp-csf').onchange = e => {
      const f = e.target.files[0]; if (!f) return;
      if (f.size > 10 * 1024 * 1024) { e.target.value = ''; return toast('La constancia debe pesar menos de 10 MB', 'error'); }
      csfFile = f; $('#fp-csf-text').textContent = `📎 ${f.name}`;
    };
    $('#fiscal-form').addEventListener('submit', submitFiscal);
  }
  function validateFiscal(b) {
    if (!RFC_RE.test(b.rfc)) return 'Escribe un RFC válido';
    if (b.person_type === 'moral' && b.rfc.length !== 12) return 'El RFC de una persona moral tiene 12 caracteres';
    if (b.person_type === 'fisica' && b.rfc.length !== 13) return 'El RFC de una persona física tiene 13 caracteres';
    if (b.legal_name.length < 3) return 'Escribe el nombre o razón social';
    if (!b.regimen_fiscal) return 'Elige el régimen fiscal';
    if (!(b.person_type === 'moral' ? REGIMENES_MORAL : REGIMENES_FISICA).includes(b.regimen_fiscal)) return 'Ese régimen fiscal no corresponde al tipo de persona';
    if (!/^\d{5}$/.test(b.postal_code)) return 'El código postal debe tener 5 dígitos';
    return null;
  }
  async function submitFiscal(e) {
    e.preventDefault();
    const body = {
      person_type: $('#fp-type button.on').dataset.v, rfc: v('#fp-rfc').toUpperCase(), legal_name: v('#fp-name').toUpperCase(), regimen_fiscal: v('#fp-regimen'),
      postal_code: v('#fp-cp'), is_donataria: $('#fp-donataria').checked,
    };
    const err = validateFiscal(body);
    if (err) return toast(err, 'error');
    await withBtn($('#fp-save'), async () => {
      if (csfFile) body.csf_document_id = (await uploadDocuments([csfFile]))[0];
      try { fiscalProfile = await api('/refuges/me/fiscal', { method: 'PATCH', body }); }
      catch (er) { throw new Error(notReady(er)); }
      toast('Datos fiscales guardados 🔒', 'ok');
      loadMsFiscal();
    });
  }

  /* ---------- cobros con Mercado Pago (Marketplace / split) ---------- */
  async function loadMsPayments() {
    const body = $('#ms-body');
    body.innerHTML = FX.skeletonList(1);
    let st = null, pending = false;
    try { st = await api('/refuges/me/payments/status'); }
    catch (e) { if (isNotReady(e)) pending = true; else { body.innerHTML = msError(e, ''); return; } }
    if (msTab !== 'cobros') return;
    const fee = st && st.fee_percent != null ? st.fee_percent : null;
    const dfee = st && st.donation_fee_percent != null ? st.donation_fee_percent : null;
    const connected = !!(st && st.connected);
    const notConfigured = !!st && st.marketplace_configured === false && !connected;
    const feeLine = fee != null ? `<div class="small mt8">Comisión de GuauWoow: <b>${esc(String(fee))} %</b> por venta${dfee != null ? ` · <b>${esc(String(dfee))} %</b> por donativo` : ''}</div>` : '';
    const notes = [];
    if (st && st.simulated) notes.push('🧪 Modo de prueba: los pagos se simulan y no se cobra dinero real.');
    if (st && st.last_error) notes.push(`⚠️ ${esc(st.last_error)}`);
    if (st && st.fiscal_profile_complete === false) notes.push('🧾 Completa tus <button type="button" class="link" data-ms-go="fiscal">datos fiscales</button> para que podamos emitirte el CFDI de la comisión.');
    body.innerHTML = `
      <div class="card p" id="mp-status" style="background:${connected ? 'var(--green)' : 'var(--yellow)'}">
        <div class="h2 row" style="gap:8px;flex-wrap:wrap">💳 Mercado Pago <span class="badge ${connected ? 'b-teal' : 'b-gray'}">${connected ? 'Conectado' : 'Sin conectar'}</span>${st && st.ready && !connected ? '<span class="badge b-lila">Cobros de prueba activos</span>' : ''}</div>
        ${connected
          ? `<p class="small mt8">Cada venta y donativo llega <b>directo a tu cuenta de Mercado Pago</b>; GuauWoow solo retiene su comisión en el mismo cobro.</p>
             <div class="small mt8">Cuenta de Mercado Pago: <b>${esc(String(st.mp_user_id || ''))}</b>${st.connected_at ? ` · conectada el ${fmtDate(st.connected_at)}` : ''}</div>
             ${feeLine}
             <button type="button" class="btn btn-sm btn-ghost mt12" id="mp-disconnect">Desconectar</button>`
          : `<p class="small mt8">${pending ? 'La conexión con Mercado Pago estará disponible muy pronto.' : notConfigured ? 'GuauWoow todavía está activando los cobros con Mercado Pago. Te avisaremos en cuanto puedas conectar tu cuenta.' : 'Conecta la cuenta de Mercado Pago de tu refugio (a su nombre y RFC) para que las ventas y donativos lleguen directo a ella. Sin cuenta conectada tus productos se ven, pero no se pueden comprar.'}</p>
             ${feeLine}
             <button type="button" class="btn block btn-orange mt12" id="mp-connect" ${pending || notConfigured ? 'disabled' : ''}>Conectar Mercado Pago</button>`}
      </div>
      ${notes.length ? `<div class="card p small mt12 col" style="gap:6px">${notes.map(n => `<span>${n}</span>`).join('')}</div>` : ''}
      <div class="card p small mt12">Al conectar, Mercado Pago te pedirá autorizar a GuauWoow para crear cobros a tu nombre. Nunca vemos tu contraseña ni tu saldo, y puedes desconectar cuando quieras. Los reembolsos de devoluciones aprobadas salen de tu cuenta de Mercado Pago.</div>`;
    FX.decorate(body);
    const c = $('#mp-connect'); if (c) c.onclick = () => withBtn(c, async () => {
      let r;
      try { r = await api('/refuges/me/payments/connect'); } catch (e) { throw new Error(notReady(e)); }
      if (!r || !safeUrl(r.url)) throw new Error('No pudimos iniciar la conexión. Inténtalo más tarde');
      FX.showLoading('Te llevamos a Mercado Pago', ['Autoriza a GuauWoow para cobrar a tu nombre'], 'run');
      location.href = r.url;
    });
    const d = $('#mp-disconnect'); if (d) d.onclick = () => confirm('¿Desconectar Mercado Pago? Tus productos dejarán de poder comprarse hasta que vuelvas a conectar.') && withBtn(d, async () => {
      try { await api('/refuges/me/payments/disconnect', { method: 'POST' }); } catch (e) { throw new Error(notReady(e)); }
      toast('Mercado Pago desconectado', 'ok');
      loadMsPayments();
    });
  }

  /* ---------- estados de cuenta ---------- */
  let msPeriod = lastPeriods(1)[0][0];
  async function loadMsStatements() {
    const body = $('#ms-body');
    body.innerHTML = `<div class="row"><select id="ms-period" class="inp grow" aria-label="Periodo del estado de cuenta"></select><button type="button" class="btn btn-sm btn-ghost" id="ms-csv">Descargar CSV</button></div><div id="ms-stmt" class="mt12">${FX.skeletonList(2)}</div>`;
    fillSelect('#ms-period', lastPeriods(12));
    $('#ms-period').value = msPeriod;
    $('#ms-period').onchange = e => { msPeriod = e.target.value; loadMsStatements(); };
    $('#ms-csv').onclick = () => downloadPrivate(`/refuges/me/statements/export?period=${encodeURIComponent(msPeriod)}`, `estado-de-cuenta-${msPeriod}.csv`);
    const box = $('#ms-stmt');
    const period = msPeriod;
    let s;
    try { s = await api(`/refuges/me/statements?period=${encodeURIComponent(period)}`); }
    catch (e) { box.innerHTML = `<p class="small muted">${esc(notReady(e))}</p>`; $('#ms-csv').disabled = true; return; }
    if (msTab !== 'cuenta' || period !== msPeriod || !box.isConnected) return;
    const stat = (label, val, color) => `<div class="card stat"><b${color ? ` style="color:${color}"` : ''}>${money(val)}</b><span>${label}</span></div>`;
    // Deducciones con signo: un mes con más reembolsos que ventas devuelve parte de la comisión (+)
    const minus = val => { const n = Number(val || 0); return n > 0 ? `− ${money(n)}` : n < 0 ? `+ ${money(-n)}` : money(0); };
    const refunds = s.refunds || [];
    box.innerHTML = `
      <div class="row"><div class="card stat"><b>${Number(s.orders_count || 0)}</b><span>Pedidos</span></div>${stat('Ventas', s.gross)}${stat('Recibido neto', s.net_received, 'var(--teal-d)')}</div>
      <div class="card p mt12 sum">
        <div class="between"><span>Ventas (incluye envío)</span><b>${money(s.gross)}</b></div>
        <div class="between small muted"><span>de las cuales, envíos cobrados</span><span>${money(s.shipping)}</span></div>
        <div class="between"><span>Reembolsos del mes${Number(s.refunds_count) ? ` (${Number(s.refunds_count)})` : ''}</span><b>${minus(s.refunds_total)}</b></div>
        <div class="between"><span>Comisión GuauWoow (IVA incluido)</span><b>${minus(s.platform_fee)}</b></div>
        <div class="between small muted"><span>(incluye IVA ${money(s.fee_iva)})</span><span></span></div>
        <div class="between"><span>ISR retenido</span><b>${minus(s.isr_retenido)}</b></div>
        <div class="between"><span>IVA retenido</span><b>${minus(s.iva_retenido)}</b></div>
        <div class="between total"><span>Neto recibido en tu Mercado Pago</span><b>${money(s.net_received)}</b></div>
        <div class="between mt8"><span>Donativos${Number(s.donations_count) ? ` (${Number(s.donations_count)})` : ''}</span><b>${money(s.donations_gross)}</b></div>
        <div class="between"><span>Comisión por donativos</span><b>${minus(s.donations_fee)}</b></div>
        ${s.donations_net != null ? `<div class="between"><span>Donativos netos</span><b>${money(s.donations_net)}</b></div>` : ''}
      </div>
      <p class="small muted mt8">El dinero llega directo a tu cuenta de Mercado Pago con cada venta; este resumen te sirve para conciliar y para tu contabilidad. Los reembolsos cuentan en el mes en que se hacen y Mercado Pago regresa en proporción la comisión y las retenciones. El CFDI de la comisión y, si aplica, el de retenciones se emiten los primeros días del mes siguiente.</p>
      <div class="mt16"><span class="h2">Pedidos del periodo</span><div class="col mt12">${(s.orders || []).length ? s.orders.map(o => `<div class="card p between"><div><b>Pedido #${o.id}</b><div class="small muted">${fmtDate(o.paid_at || o.created_at)}${o.status ? ` · ${esc(orderLabel(o.status))}` : ''}</div></div><div style="text-align:right"><b>${money(o.total)}</b>${o.net_amount != null ? `<div class="small muted">neto ${money(o.net_amount)}</div>` : ''}</div></div>`).join('') : '<p class="small muted">Sin pedidos pagados en este periodo.</p>'}</div></div>
      ${refunds.length ? `<div class="mt16"><span class="h2">Reembolsos del periodo</span><div class="col mt12">${refunds.map(r => `<div class="card p between"><div><b>Pedido #${r.order_id}</b><div class="small muted">${fmtDate(r.at)} · ${r.is_full ? 'reembolso total' : 'reembolso parcial'}</div></div><div style="text-align:right"><b>− ${money(r.amount)}</b><div class="small muted">a tu cargo ${money(r.net_reversed)}</div></div></div>`).join('')}</div></div>` : ''}`;
    FX.decorate(box);
  }

  /* ============================================================
     Ganchos para app.js (deep links y notificaciones)
     ============================================================ */
  /* Regreso de la conexión OAuth con Mercado Pago (#mp=connected|error, guardado por init() en state.mpReturn) */
  function onMpReturn(mp) {
    const ok = mp === 'connected';
    toast(ok ? '¡Mercado Pago conectado! Ya puedes recibir ventas y donativos 💳' : 'No se pudo conectar Mercado Pago. Inténtalo de nuevo', ok ? 'ok' : 'error');
    openMyShop('cobros');
  }
  /* Devuelve true si la notificación es de la tienda y ya se abrió su pantalla */
  function onNotification(type, data = {}) {
    if (!shopOn()) return false;
    const tab = SELLER_NOTIF[type] || (data.seller_view || data.for_refuge ? 'pedidos' : null);
    if (tab) { openMyShop(data.tab || tab); return true; }
    // Avisos que llegan con el mismo tipo al comprador y al refugio (p. ej. order_return_requested): se abre el
    // pedido como comprador y, si no es suyo, "Mi tienda"
    if (data.order_id && (type.startsWith('order') || type.startsWith('invoice'))) { openOrder(+data.order_id, { fallbackShop: true }); return true; }
    return false;
  }

  /* ============================================================
     Eventos
     ============================================================ */
  (function bindShopEvents() {
    const on = (sel, ev, fn) => { const el = $(sel); if (el) el.addEventListener(ev, fn); };
    // Carrito
    on('#cart-btn', 'click', openCart);
    on('#cart-close', 'click', () => $('#cart-modal').classList.remove('open'));
    on('#cart-checkout', 'click', openCheckout);
    // Checkout
    fillSelect('#co-state', MX_STATES.map(s => [s, stateLabel(s)]), 'Elige tu estado');
    on('#checkout-form', 'submit', submitCheckout);
    on('#co-cp', 'input', e => { e.target.value = e.target.value.replace(/\D/g, '').slice(0, 5); });
    on('#co-forget-address', 'click', e => {
      forgetAddress();
      e.currentTarget.classList.add('hidden');
      ['#co-street', '#co-ext', '#co-int', '#co-neigh', '#co-cp', '#co-refs'].forEach(sel => { const el = $(sel); if (el) el.value = ''; });
      toast('Listo: borramos la dirección guardada en este dispositivo', 'ok');
    });
    // Pedidos del comprador
    on('#return-form', 'submit', submitReturn);
    fillSelect('#ret-reason', RETURN_REASONS, 'Elige el motivo');
    on('#invoice-form', 'submit', submitInvoiceRequest);
    fillRegimen('#inv-regimen', null, 'Elige tu régimen fiscal');
    on('#inv-rfc', 'input', e => fillRegimen('#inv-regimen', personType(e.target.value), 'Elige tu régimen fiscal'));
    fillSelect('#inv-uso', satOptions(SAT_USOS_CFDI), 'Elige el uso del CFDI');
    $$('[data-close-modal]').forEach(b => b.addEventListener('click', () => { const m = b.closest('.modal'); if (m) m.classList.remove('open'); }));
    // Panel del refugio
    on('#product-form', 'submit', submitProduct);
    on('#pm-delete', 'click', deleteProduct);
    on('#pm-nationwide', 'change', e => $('#pm-states-wrap').classList.toggle('hidden', e.target.checked));
    on('#pm-warranty-kind', 'change', e => $('#pm-warranty-wrap').classList.toggle('hidden', e.target.value !== 'yes'));
    on('#rc-download', 'click', downloadReceipt);
    loadRules();  // categorías de productos y plazos (GET /cumplimiento/reglas)
    const pmStates = $('#pm-states');
    if (pmStates) {
      pmStates.innerHTML = MX_STATES.map(s => `<button type="button" class="chip" data-state="${esc(s)}" aria-pressed="false">${esc(stateLabel(s))}</button>`).join('');
      $$('.chip', pmStates).forEach(c => c.addEventListener('click', () => { c.classList.toggle('on'); c.setAttribute('aria-pressed', String(c.classList.contains('on'))); }));
    }
    on('#pm-states-all', 'click', () => setStateChips(new Set(MX_STATES)));
    on('#pm-states-none', 'click', () => setStateChips(new Set()));
    $$('#ms-tabs .chip').forEach(c => c.addEventListener('click', () => setMsTab(c.dataset.msTab)));
    on('#dc-submit', 'click', submitDecision);
    on('#rinv-form', 'submit', submitRefugeInvoice);
    on('#rinv-status', 'change', toggleRinvFields);
    // Selectores de archivo con texto en español (el <input type=file> nativo usa el idioma del navegador)
    $$('[data-pick]').forEach(b => {
      const input = $(`#${b.dataset.pick}`), label = $(`#${b.dataset.pick}-text`);
      b.addEventListener('click', () => input.click());
      input.addEventListener('change', () => {
        const f = input.files[0];
        if (f && f.size > 10 * 1024 * 1024) { input.value = ''; label.textContent = 'Sin archivo'; return toast('El archivo debe pesar menos de 10 MB', 'error'); }
        label.textContent = f ? `📎 ${f.name}` : 'Sin archivo';
      });
    });
    // Delegación: abrir pedidos, "Mi tienda" y atajos entre pestañas
    device.addEventListener('click', e => {
      const t = e.target.closest('[data-order-open],[data-act="my-shop"],[data-ms-go]');
      if (!t) return;
      if (t.dataset.orderOpen) openOrder(+t.dataset.orderOpen);
      else if (t.dataset.msGo) setMsTab(t.dataset.msGo);
      else if (t.dataset.act === 'my-shop') openMyShop();
    });
  })();

  /* Lo que usan app.js (navegación, perfil, notificaciones, deep links) y test-e2e.mjs */
  return {
    MX_STATES, ORDER_STATUS, RETURN_REASONS, RETURN_WINDOW_DAYS, CANCEL_REASON, validateAddress, validateInvoiceRequest, validateFiscal, joinAddress,
    feeSplit, feeText, savedAddress,
    businessDaysSince, addBusinessDays, buildTimeline, canReturn, canCancel, loadShop, openProduct, openCart, openCheckout,
    openMyOrders, openOrder, renderOrder, openMyShop, addToCart, onMpReturn, onNotification, stateLabel,
    openReceipt, loadRules, warrantyLabel,
  };
})();

/* Puntos de entrada que app.js llama por su nombre (navegación, delegación de clics y perfil) */
window.loadShop = Tienda.loadShop;
window.openProduct = Tienda.openProduct;
window.openMyOrders = Tienda.openMyOrders;
