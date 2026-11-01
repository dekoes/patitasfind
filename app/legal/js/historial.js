/* ============================================================
   GuauWoow — Registro de versiones (historial.html §1, contrato K-DOCS)
   Llena #historial-versiones con GET /cumplimiento/documentos: por documento, la versión vigente con su fecha
   de publicación y de entrada en vigor, el resumen de cambios, la huella SHA-256 y si pidió aceptarla de nuevo;
   la próxima versión (si hay aviso previo) y todas las anteriores. Sin manejadores en línea (CSP).
   ============================================================ */
(function () {
  'use strict';
  var mount = document.getElementById('historial-versiones');
  if (!mount) return;

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }
  function parse(iso) {
    if (!iso) return null;
    var d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    return isNaN(d.getTime()) ? null : d;
  }
  function fecha(iso, fallback) {
    var d = parse(iso);
    if (!d) return fallback || '—';
    return d.toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'America/Mexico_City' });
  }
  function badge(text, kind) { return el('span', { class: 'badge ' + kind }, text); }
  function shaCode(sha) {
    var c = el('code', { class: 'sha256', title: 'Huella SHA-256 del texto publicado' }, sha || '');
    return c;
  }
  function safeHref(url) {
    return /^\/app\/legal\/[a-z0-9-]+\.html(#[\w-]+)?$/.test(url || '') ? url : null;
  }
  function message(text) {
    mount.textContent = '';
    mount.appendChild(el('p', {}, text));
  }

  function versionBlock(v, label) {
    var box = el('div', { class: 'hv-version' });
    var head = el('p', { class: 'hv-head' });
    head.appendChild(el('b', {}, label + ': ' + v.version + ' '));
    if (v.requires_reacceptance) head.appendChild(badge('Pidió aceptarla de nuevo', 'warn'));
    else head.appendChild(badge('Cambio menor', 'info'));
    box.appendChild(head);
    var dl = el('dl', { class: 'kv hv-kv' });
    dl.appendChild(el('dt', {}, 'Publicada'));
    dl.appendChild(el('dd', {}, fecha(v.published_at, 'En espera de registro')));
    dl.appendChild(el('dt', {}, 'Vigente desde'));
    dl.appendChild(el('dd', {}, v.effective_at ? fecha(v.effective_at) : 'Desde su publicación'));
    dl.appendChild(el('dt', {}, 'Resumen'));
    dl.appendChild(el('dd', {}, v.summary || 'Sin resumen registrado.'));
    dl.appendChild(el('dt', {}, 'SHA-256'));
    var dd = el('dd', {});
    dd.appendChild(shaCode(v.sha256));
    dl.appendChild(dd);
    box.appendChild(dl);
    return box;
  }

  function historyTable(doc) {
    var wrap = el('div', { class: 'table-wrap' });
    var table = el('table', { class: 'compact hv-table' });
    var cap = el('caption', {}, 'Todas las versiones de «' + doc.title + '»');
    table.appendChild(cap);
    var thead = el('thead', {});
    var tr = el('tr', {});
    ['Versión', 'Estado', 'Publicada', 'Vigente desde', 'Resumen', 'SHA-256', '¿Pidió aceptación?'].forEach(function (h) {
      tr.appendChild(el('th', { scope: 'col' }, h));
    });
    thead.appendChild(tr);
    table.appendChild(thead);
    var tbody = el('tbody', {});
    (doc.versiones || []).forEach(function (v) {
      var row = el('tr', {});
      row.appendChild(el('th', { scope: 'row' }, v.version));
      var st = el('td', {});
      st.appendChild(v.status === 'vigente' ? badge('Vigente', 'ok') : v.status === 'proxima' ? badge('Próxima', 'pend') : badge('Anterior', 'info'));
      row.appendChild(st);
      row.appendChild(el('td', {}, fecha(v.published_at)));
      row.appendChild(el('td', {}, v.effective_at ? fecha(v.effective_at) : 'Al publicarse'));
      // El resumen de la vigente y de la próxima ya se muestra arriba completo
      row.appendChild(el('td', {}, v.status === 'anterior' ? (v.summary || '—') : 'Ver el resumen arriba'));
      var sha = el('td', {});
      sha.appendChild(shaCode(v.sha256));
      row.appendChild(sha);
      row.appendChild(el('td', {}, v.requires_reacceptance ? 'Sí' : 'No'));
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function render(data) {
    var docs = (data && data.documentos) || [];
    mount.textContent = '';
    if (!docs.length) {
      message('Todavía no hay versiones registradas. Vuelve a intentarlo más tarde o escríbenos para pedir una versión.');
      return;
    }
    var intro = el('p', { class: 'hv-intro' },
      docs.length + ' documentos registrados. Toca un documento para ver su historial completo.');
    mount.appendChild(intro);
    docs.forEach(function (doc) {
      var details = el('details', { class: 'hv-doc', id: 'version-' + doc.slug });
      var summary = el('summary', {});
      summary.appendChild(el('b', {}, doc.title));
      var current = doc.vigente || doc.proxima;
      if (current) summary.appendChild(el('span', { class: 'hv-sum-ver' }, ' · versión ' + current.version));
      if (doc.proxima) { summary.appendChild(document.createTextNode(' ')); summary.appendChild(badge('Cambio próximo', 'pend')); }
      details.appendChild(summary);
      var href = safeHref(doc.url);
      if (href) {
        var p = el('p', {});
        p.appendChild(el('a', { href: href }, 'Leer «' + doc.title + '»'));
        details.appendChild(p);
      }
      if (doc.vigente) details.appendChild(versionBlock(doc.vigente, 'Versión vigente'));
      if (doc.proxima) {
        var note = el('div', { class: 'callout peach' });
        note.appendChild(el('p', { class: 'callout-title' }, 'Próxima versión: entra en vigor el ' + fecha(doc.proxima.effective_at)));
        note.appendChild(versionBlock(doc.proxima, 'Próxima versión'));
        details.appendChild(note);
      }
      details.appendChild(historyTable(doc));
      mount.appendChild(details);
    });
    // Abre el documento del enlace (#version-<slug>)
    var target = location.hash && document.getElementById(location.hash.slice(1));
    if (target && target.tagName === 'DETAILS') { target.open = true; target.scrollIntoView(); }
  }

  if (!window.fetch) { message('Tu navegador no puede cargar el registro. Escríbenos para pedir cualquier versión.'); return; }
  fetch('/cumplimiento/documentos', { headers: { Accept: 'application/json' } })
    .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
    .then(render)
    .catch(function () {
      message('No pudimos cargar el registro de versiones en este momento. Inténtalo de nuevo en unos minutos o escríbenos para pedir cualquier versión.');
    });
})();
