/* ============================================================
   GuauWoow — Tabla de plazos vigentes (conservacion.html §2, contrato K-CONSERV)
   Llena #tabla-conservacion con GET /cumplimiento/conservacion: la misma configuración
   (backend/app/services/retention.py) que usa la purga diaria para borrar o anonimizar.
   Filtro por texto y por forma de aplicación; en el teléfono cada fila se lee como tarjeta.
   Sin manejadores en línea (CSP); todo el contenido se inserta como texto.
   ============================================================ */
(function () {
  'use strict';
  var mount = document.getElementById('tabla-conservacion');
  if (!mount) return;

  var APLICACION_CLASE = {
    automatica: 'ok', caduca_sola: 'ok', al_eliminar: 'info', bloqueo: 'pend',
    procedimiento: 'pend', proveedor: 'info', navegador: 'info', no_se_guarda: 'ok'
  };

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }
  function fecha(iso) {
    if (!iso) return null;
    var d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    if (isNaN(d.getTime())) return null;
    return d.toLocaleString('es-MX', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit',
      timeZone: 'America/Mexico_City' });
  }
  function message(text) {
    mount.textContent = '';
    mount.appendChild(el('p', {}, text));
  }
  function norm(s) {
    return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  function render(data) {
    var rows = (data && data.categorias) || [];
    if (!rows.length) { message('Por ahora no pudimos cargar la tabla. Consulta el resumen de la sección 3.'); return; }
    mount.textContent = '';

    var info = el('p', { class: 'legal-refs ct-meta' });
    var parts = ['Versión de la tabla: ' + (data.version || '—') + '.'];
    if (data.purga) {
      var ultima = fecha(data.purga.ultima);
      parts.push(data.purga.activa ? 'Purga automática diaria activa.' : 'Purga automática en pausa temporal.');
      if (ultima) parts.push('Última ejecución: ' + ultima + (data.purga.estado ? ' (' + data.purga.estado + ').' : '.'));
    }
    info.textContent = parts.join(' ');
    mount.appendChild(info);

    // Filtros
    var tools = el('div', { class: 'ct-tools' });
    var qLabel = el('label', { for: 'ct-q' }, 'Buscar un dato');
    var q = el('input', { id: 'ct-q', type: 'search', placeholder: 'Ej. chats, facturas, INE', autocomplete: 'off' });
    var fLabel = el('label', { for: 'ct-f' }, 'Cómo se aplica');
    var f = el('select', { id: 'ct-f' });
    f.appendChild(el('option', { value: '' }, 'Todas'));
    var seen = {};
    rows.forEach(function (r) {
      if (seen[r.aplicacion]) return;
      seen[r.aplicacion] = true;
      f.appendChild(el('option', { value: r.aplicacion }, r.aplicacion_texto || r.aplicacion));
    });
    var qBox = el('div', {}); qBox.appendChild(qLabel); qBox.appendChild(q);
    var fBox = el('div', {}); fBox.appendChild(fLabel); fBox.appendChild(f);
    tools.appendChild(qBox); tools.appendChild(fBox);
    mount.appendChild(tools);

    var wrap = el('div', { class: 'table-wrap ct-wrap' });
    var table = el('table', { class: 'ct-table' });
    table.appendChild(el('caption', {}, 'Plazos vigentes de conservación (configuración del sistema)'));
    var thead = el('thead');
    var hr = el('tr');
    ['Dato', 'Plazo', 'Desde', 'Al vencer', 'Cómo se aplica', 'Fundamento'].forEach(function (h) {
      hr.appendChild(el('th', { scope: 'col' }, h));
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = el('tbody');
    rows.forEach(function (r) {
      var tr = el('tr', { 'data-aplicacion': r.aplicacion, 'data-texto': norm([r.categoria, r.plazo, r.accion, r.fundamento].join(' ')) });
      tr.appendChild(el('th', { scope: 'row', 'data-label': 'Dato' }, r.categoria));
      tr.appendChild(el('td', { 'data-label': 'Plazo' }, r.plazo));
      tr.appendChild(el('td', { 'data-label': 'Desde' }, r.desde || '—'));
      tr.appendChild(el('td', { 'data-label': 'Al vencer' }, r.accion || '—'));
      var how = el('td', { 'data-label': 'Cómo se aplica' });
      how.appendChild(el('span', { class: 'badge ' + (APLICACION_CLASE[r.aplicacion] || 'info') }, r.aplicacion_texto || r.aplicacion));
      tr.appendChild(how);
      tr.appendChild(el('td', { 'data-label': 'Fundamento', class: 'legal-refs' }, r.fundamento || '—'));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    mount.appendChild(wrap);
    var empty = el('p', { class: 'legal-refs', hidden: '' }, 'Ningún dato coincide con tu búsqueda.');
    var count = el('p', { class: 'legal-refs', 'aria-live': 'polite' }, rows.length + ' categorías.');
    mount.appendChild(empty);
    mount.appendChild(count);

    function apply() {
      var text = norm(q.value.trim());
      var kind = f.value;
      var shown = 0;
      Array.prototype.forEach.call(tbody.rows, function (tr) {
        var ok = (!text || tr.getAttribute('data-texto').indexOf(text) !== -1) && (!kind || tr.getAttribute('data-aplicacion') === kind);
        tr.hidden = !ok;
        if (ok) shown += 1;
      });
      empty.hidden = shown !== 0;
      count.textContent = shown + (shown === 1 ? ' categoría.' : ' categorías.');
    }
    q.addEventListener('input', apply);
    f.addEventListener('change', apply);
  }

  fetch('/cumplimiento/conservacion', { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
    .then(function (res) { if (!res.ok) throw new Error(String(res.status)); return res.json(); })
    .then(render)
    .catch(function () {
      message('Por ahora no pudimos cargar la tabla vigente. Consulta el resumen de la sección 3 o inténtalo más tarde.');
    });
})();
