/* ============================================================
   GuauWoow — Tablero de estado (estado-del-servicio.html §1, contrato K-ESTADO)
   Llena #estado-servicio con GET /cumplimiento/estado: estado general, cada componente
   (sitio, API, base de datos, tareas, correo, pagos, SMS, WhatsApp, IA), mantenimientos
   programados e incidentes publicados (solo su resumen). Se actualiza cada 60 s mientras la
   pestaña está visible. Sin manejadores en línea (CSP); todo se inserta como texto.
   ============================================================ */
(function () {
  'use strict';
  var mount = document.getElementById('estado-servicio');
  if (!mount) return;

  var REFRESH_MS = 60000;
  var GENERAL = {
    operativo: ['Todo funciona con normalidad', 'ok'],
    degradado: ['Algunos servicios presentan fallas', 'pend'],
    mantenimiento: ['Mantenimiento en curso', 'info'],
    interrupcion: ['Interrupción del servicio', 'warn']
  };
  var COMPONENTE = {
    operativo: ['Funciona', 'ok'],
    degradado: ['Con fallas', 'pend'],
    interrumpido: ['Sin servicio', 'warn'],
    mantenimiento: ['En mantenimiento', 'info'],
    no_configurado: ['No disponible por ahora', 'info']
  };
  var CATEGORIA = { vulneracion: 'Seguridad', disponibilidad: 'Falla del servicio', mantenimiento: 'Mantenimiento' };
  var timer = null;

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
    return d.toLocaleString('es-MX', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
      timeZone: 'America/Mexico_City' });
  }
  function badge(map, key) {
    var v = map[key] || [key, 'info'];
    return el('span', { class: 'badge ' + v[1] }, v[0]);
  }

  function incidentItem(inc, componentes) {
    var li = el('li', { class: 'es-incident' });
    var head = el('p', { class: 'es-incident-head' });
    head.appendChild(el('b', {}, inc.titulo || 'Incidente'));
    head.appendChild(document.createTextNode(' '));
    head.appendChild(el('span', { class: 'badge ' + (inc.estado === 'resuelto' ? 'ok' : 'pend') },
      inc.estado === 'resuelto' ? 'Resuelto' : (inc.categoria === 'mantenimiento' ? 'Programado' : 'En curso')));
    li.appendChild(head);
    var meta = [CATEGORIA[inc.categoria] || inc.categoria];
    if (inc.inicio) meta.push('Inicio: ' + fecha(inc.inicio));
    if (inc.fin) meta.push('Fin: ' + fecha(inc.fin));
    var names = (inc.componentes || []).map(function (c) { return (componentes[c] && componentes[c].nombre) || c; });
    if (names.length) meta.push('Afecta: ' + names.join(', '));
    li.appendChild(el('p', { class: 'legal-refs' }, meta.join(' · ')));
    if (inc.resumen) li.appendChild(el('p', {}, inc.resumen));
    return li;
  }

  function render(data) {
    mount.textContent = '';
    var general = GENERAL[data.estado] || GENERAL.degradado;
    var banner = el('div', { class: 'es-banner es-' + (data.estado || 'degradado'), role: 'status' });
    banner.appendChild(el('span', { class: 'badge ' + general[1] }, general[0]));
    var when = fecha(data.actualizado);
    if (when) banner.appendChild(el('span', { class: 'legal-refs' }, 'Revisado: ' + when));
    mount.appendChild(banner);

    var componentes = data.componentes || {};
    var list = el('ul', { class: 'es-components' });
    Object.keys(componentes).forEach(function (key) {
      var c = componentes[key];
      var li = el('li', { class: 'es-component' });
      li.appendChild(el('span', { class: 'es-name' }, c.nombre || key));
      li.appendChild(badge(COMPONENTE, c.estado));
      if (c.detalle) li.appendChild(el('span', { class: 'es-detail legal-refs' }, c.detalle));
      list.appendChild(li);
    });
    mount.appendChild(list);

    var mant = data.mantenimientos || [];
    if (mant.length) {
      mount.appendChild(el('h3', {}, 'Mantenimientos programados'));
      var ml = el('ul', { class: 'es-incidents' });
      mant.forEach(function (m) { ml.appendChild(incidentItem(m, componentes)); });
      mount.appendChild(ml);
    }
    mount.appendChild(el('h3', {}, 'Incidentes de los últimos 90 días'));
    var incs = data.incidentes || [];
    if (!incs.length) {
      mount.appendChild(el('p', {}, 'Sin incidentes publicados en los últimos 90 días.'));
    } else {
      var il = el('ul', { class: 'es-incidents' });
      incs.forEach(function (i) { il.appendChild(incidentItem(i, componentes)); });
      mount.appendChild(il);
    }
  }

  function load() {
    fetch('/cumplimiento/estado', { headers: { Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store' })
      .then(function (res) { if (!res.ok) throw new Error(String(res.status)); return res.json(); })
      .then(render)
      .catch(function () {
        mount.textContent = '';
        var box = el('div', { class: 'es-banner es-interrupcion', role: 'status' });
        box.appendChild(el('span', { class: 'badge warn' }, 'No pudimos consultar el estado'));
        box.appendChild(el('span', { class: 'legal-refs' }, 'Puede ser tu conexión o nuestro servidor. Intenta más tarde.'));
        mount.appendChild(box);
      });
  }

  function schedule() {
    if (timer) clearInterval(timer);
    timer = setInterval(function () { if (!document.hidden) load(); }, REFRESH_MS);
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });
  load();
  schedule();
})();
