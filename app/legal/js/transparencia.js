/* ============================================================
   GuauWoow · Informe de transparencia (contrato K-TRANSP)
   Punto de montaje: #transparencia-metricas[data-vista="general" | "fondos"]
     general -> informe-transparencia.html (dinero, moderación, ARCO, importados, verificados, autoridades)
     fondos  -> transparencia-fondos.html («A dónde va tu dinero»: tablero por Refugio y serie mensual)
   ?refugio=ID abre el detalle de un Refugio (GET /cumplimiento/transparencia/refugios/{id}).
   Gráficas con SVG y CSS simples; cada cifra está también en una tabla accesible. Sin manejadores en línea (CSP).
   Colores de las marcas validados (dataviz validate_palette): donativos #008C7E, ventas #6A43C2.
   ============================================================ */
"use strict";

(() => {
  const API = "/cumplimiento/transparencia";
  const TZ = "America/Mexico_City";
  const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => Number(n || 0).toLocaleString("es-MX", { style: "currency", currency: "MXN" });
  const num = (n) => Number(n || 0).toLocaleString("es-MX");
  const compact = (n) => Number(n || 0).toLocaleString("es-MX", { notation: "compact", maximumFractionDigits: 1 });
  const toDate = (v) => { if (!v) return null; const s = String(v); return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`); };
  const fmtDateTime = (v) => { const d = toDate(v); return d ? d.toLocaleString("es-MX", { timeZone: TZ, day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " h" : ""; };
  const monthLabel = (p) => { const [y, m] = String(p).split("-").map(Number); return `${MONTHS[m - 1]} de ${y}`; };
  const monthShort = (p) => MONTHS[Number(String(p).split("-")[1]) - 1].slice(0, 3);
  let k = 5;
  let uid = 0;

  async function get(path) {
    let res;
    try { res = await fetch(path, { credentials: "same-origin" }); }
    catch { throw new Error("No hay conexión. Revisa tu internet e inténtalo de nuevo."); }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && typeof data.detail === "string" && data.detail) || "No pudimos cargar las cifras. Inténtalo más tarde.");
    return data;
  }

  /* ---------------------------------------------------------------- piezas */
  const suppressed = () => `<span class="tr-sup" title="No publicamos desgloses con menos de ${k} casos">menos de ${k}</span>`;
  const cell = (block, key, fmt = money) => (!block || block.suprimido ? suppressed() : esc(fmt(block[key])));
  const count = (block) => (!block || block.suprimido ? suppressed() : esc(num(block.casos)));

  function tiles(items) {
    return `<div class="tr-tiles">${items.map(([label, value, note]) =>
      `<div class="tr-tile"><span class="tr-tile-label">${esc(label)}</span><span class="tr-tile-value">${value}</span>${note ? `<span class="tr-tile-note">${esc(note)}</span>` : ""}</div>`).join("")}</div>`;
  }

  // Desglose como tabla con una barra por fila (un solo color: la longitud ya dice la magnitud)
  function barTable(caption, header, rows) {
    if (!rows || !rows.length) return `<p class="tr-empty">${esc(caption)}: sin casos en el periodo.</p>`;
    const max = Math.max(1, ...rows.map((r) => r.casos || 0));
    return `<div class="table-wrap"><table class="compact tr-bars"><caption>${esc(caption)}</caption>
      <thead><tr><th scope="col">${esc(header)}</th><th scope="col">Casos</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><th scope="row">${esc(r.texto)}</th><td>${r.casos == null ? suppressed()
        : `<span class="tr-bar" aria-hidden="true"><span data-w="${(100 * r.casos / max).toFixed(1)}"></span></span><span class="tr-bar-value">${esc(num(r.casos))}</span>`}</td></tr>`).join("")}
      </tbody></table></div>`;
  }

  function meter(label, pct) {
    if (pct == null) return tiles([[label, "—", "Sin solicitudes respondidas en el periodo"]]);
    const mid = `trm-${++uid}`;
    return `<div class="tr-meter"><span class="tr-tile-label" id="${mid}">${esc(label)}</span>
      <span class="tr-tile-value">${esc(pct.toLocaleString("es-MX"))} %</span>
      <span class="tr-meter-track" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${esc(pct)}" aria-labelledby="${mid}"><span data-w="${Math.max(0, Math.min(100, pct))}"></span></span></div>`;
  }

  // Columnas por mes con SVG (una serie por gráfica: no hay dos escalas en el mismo eje)
  function columns(title, series, key, colorClass) {
    const W = 640, H = 220, L = 52, R = 12, T = 18, B = 30;
    const vals = series.map((m) => (m.bloque && !m.bloque.suprimido && m.bloque.casos ? Number(m.bloque[key] || 0) : 0));
    const max = Math.max(...vals, 0);
    const top = max > 0 ? niceCeil(max) : 1;
    const band = (W - L - R) / Math.max(1, series.length);
    const bw = Math.min(24, band * 0.6);
    const y = (v) => T + (H - T - B) * (1 - v / top);
    const grid = [0, 0.5, 1].map((f) => {
      const yy = y(top * f);
      return `<line x1="${L}" x2="${W - R}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" class="tr-grid"/><text x="${L - 6}" y="${(yy + 4).toFixed(1)}" class="tr-axis" text-anchor="end">${esc(compact(top * f))}</text>`;
    }).join("");
    let lastIdx = -1;
    vals.forEach((v, i) => { if (v > 0) lastIdx = i; });
    const bars = series.map((m, i) => {
      const v = vals[i];
      const x = L + band * i + (band - bw) / 2;
      const yy = y(v), h = (H - B) - yy;
      const tip = m.bloque && m.bloque.suprimido ? `${monthLabel(m.mes)}: menos de ${k} operaciones (no se publica)` : `${monthLabel(m.mes)}: ${money(v)}`;
      const shape = h > 0.5 ? `<path d="${roundedTop(x, yy, bw, h, Math.min(4, h, bw / 2))}" class="${colorClass}"/>` : "";
      const label = i === lastIdx && v > 0 ? `<text x="${(x + bw / 2).toFixed(1)}" y="${(yy - 5).toFixed(1)}" class="tr-val" text-anchor="middle">${esc(compact(v))}</text>` : "";
      return `<g><title>${esc(tip)}</title><rect x="${(L + band * i).toFixed(1)}" y="${T}" width="${band.toFixed(1)}" height="${H - T - B}" class="tr-hit"/>${shape}${label}
        <text x="${(L + band * i + band / 2).toFixed(1)}" y="${H - 10}" class="tr-axis" text-anchor="middle">${esc(monthShort(m.mes))}</text></g>`;
    }).join("");
    return `<figure class="tr-chart"><figcaption>${esc(title)}</figcaption>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}. Los valores están en la tabla de abajo." preserveAspectRatio="xMidYMid meet">
        ${grid}<line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" class="tr-baseline"/>${bars}</svg></figure>`;
  }

  function roundedTop(x, y, w, h, r) {
    return `M${x.toFixed(1)},${(y + h).toFixed(1)} V${(y + r).toFixed(1)} Q${x.toFixed(1)},${y.toFixed(1)} ${(x + r).toFixed(1)},${y.toFixed(1)} H${(x + w - r).toFixed(1)} Q${(x + w).toFixed(1)},${y.toFixed(1)} ${(x + w).toFixed(1)},${(y + r).toFixed(1)} V${(y + h).toFixed(1)} Z`;
  }

  function niceCeil(v) {
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const f = v / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }

  function monthlyTable(series) {
    return `<details class="tr-details"><summary>Ver la tabla por mes</summary><div class="table-wrap"><table class="compact">
      <caption>Donativos y ventas por mes (neto: después de la comisión de GuauWoow y las retenciones, antes de la de Mercado Pago)</caption>
      <thead><tr><th scope="col">Mes</th><th scope="col">Donativos</th><th scope="col">Donativos: bruto</th><th scope="col">Donativos: neto</th>
        <th scope="col">Ventas</th><th scope="col">Ventas: bruto</th><th scope="col">Ventas: neto</th></tr></thead><tbody>
      ${series.map((m) => `<tr><th scope="row">${esc(monthLabel(m.mes))}</th>
        <td>${m.donativos.casos === 0 ? "0" : count(m.donativos)}</td><td>${m.donativos.casos === 0 ? "—" : cell(m.donativos, "bruto")}</td><td>${m.donativos.casos === 0 ? "—" : cell(m.donativos, "neto")}</td>
        <td>${m.ventas.casos === 0 ? "0" : count(m.ventas)}</td><td>${m.ventas.casos === 0 ? "—" : cell(m.ventas, "bruto")}</td><td>${m.ventas.casos === 0 ? "—" : cell(m.ventas, "neto")}</td></tr>`).join("")}
      </tbody></table></div></details>`;
  }

  function charts(series) {
    if (!series || !series.length) return "";
    const d = series.map((m) => ({ mes: m.mes, bloque: m.donativos }));
    const v = series.map((m) => ({ mes: m.mes, bloque: m.ventas }));
    return `<div class="tr-charts">${columns("Donativos por mes: lo que recibieron los Refugios (neto)", d, "neto", "tr-c1")}
      ${columns("Ventas de la tienda por mes: lo que recibieron los Refugios (neto)", v, "neto", "tr-c2")}</div>${monthlyTable(series)}`;
  }

  /* ---------------------------------------------------------------- dinero */
  function funds(f, view) {
    const t = f.totales;
    // Un total se suprime si con él se pudieran despejar, restando, las cifras de pocos Refugios sin nombre
    const anySup = t.ventas.suprimido || t.donativos.suprimido;
    const sumOf = (key) => (anySup ? suppressed() : esc(money((t.ventas[key] || 0) + (t.donativos[key] || 0))));
    const countNote = (block, noun) => (block.suprimido ? "Se agrupa para no identificar a ningún Refugio" : `${num(block.casos)} ${noun}`);
    const rows = f.refugios.map((r) => `<tr>
        <th scope="row">${esc(r.nombre)}${r.ciudad ? `<span class="tr-sub">${esc(r.ciudad)}</span>` : ""}${r.donataria_autorizada ? `<span class="badge ok">Donataria autorizada</span>` : ""}</th>
        <td>${count(r.donativos)}</td><td>${cell(r.donativos, "bruto")}</td><td>${cell(r.donativos, "comision")}</td><td>${cell(r.donativos, "neto")}</td>
        <td>${count(r.ventas)}</td><td>${cell(r.ventas, "bruto")}</td><td>${cell(r.ventas, "reembolsos")}</td><td>${cell(r.ventas, "comision")}</td><td>${cell(r.ventas, "retenciones")}</td><td>${cell(r.ventas, "neto")}</td>
        ${view === "fondos" ? `<td><button type="button" class="tr-btn" data-refugio="${esc(r.id)}">Ver detalle</button></td>` : ""}</tr>`).join("");
    const o = f.otros_refugios;
    const othersCount = o && o.refugios != null ? esc(num(o.refugios)) : `menos de ${esc((o && o.refugios_minimo) || 3)}`;
    const others = o ? `<tr class="tr-others"><th scope="row">Otros Refugios (${othersCount})<span class="tr-sub">Personas físicas que no aceptaron publicar su nombre, Refugios con menos de ${k} operaciones y los rubros con menos de ${k} operaciones de los Refugios con nombre</span></th>
        <td>${count(o.donativos)}</td><td>${cell(o.donativos, "bruto")}</td><td>${cell(o.donativos, "comision")}</td><td>${cell(o.donativos, "neto")}</td>
        <td>${count(o.ventas)}</td><td>${cell(o.ventas, "bruto")}</td><td>${cell(o.ventas, "reembolsos")}</td><td>${cell(o.ventas, "comision")}</td><td>${cell(o.ventas, "retenciones")}</td><td>${cell(o.ventas, "neto")}</td>
        ${view === "fondos" ? "<td></td>" : ""}</tr>` : "";
    const platform = f.donativos_cobrados_por_la_plataforma == null
      ? `<p class="tr-note warn">En el periodo, algunos donativos se cobraron con la cuenta de GuauWoow porque el Refugio aún no vinculaba su Mercado Pago; GuauWoow debe entregar ese monto a cada Refugio. No publicamos la cifra porque fueron menos de 3 Refugios.</p>`
      : f.donativos_cobrados_por_la_plataforma > 0
      ? `<p class="tr-note warn">En el periodo, ${esc(money(f.donativos_cobrados_por_la_plataforma))} en donativos se cobraron con la cuenta de GuauWoow porque el Refugio aún no vinculaba su Mercado Pago; GuauWoow debe entregar ese monto a cada Refugio.</p>` : "";
    return `
      <h3 class="tr-h">Donativos y ventas por Refugio</h3>
      ${tiles([
        ["Donativos recibidos (bruto)", cell(t.donativos, "bruto"), countNote(t.donativos, "donativos")],
        ["Ventas de la tienda (bruto)", cell(t.ventas, "bruto"), countNote(t.ventas, "pedidos cobrados")],
        ["Comisión de GuauWoow", sumOf("comision"), `${f.comision_donativos_porcentaje} % en donativos · ${f.comision_tienda_porcentaje} % en ventas`],
        ["Retenciones de impuestos (ventas)", cell(t.ventas, "retenciones"), "ISR e IVA que aplican"],
        ["Neto para los Refugios", sumOf("neto"), "Antes de la comisión de Mercado Pago"],
      ])}
      ${platform}
      ${view === "fondos" ? charts(f.serie_mensual) : ""}
      ${rows || others ? `<div class="table-wrap"><table class="tr-money">
        <caption>Por Refugio: donativos y ventas hechos en GuauWoow (solo totales; sin datos de quienes donan o compran)</caption>
        <thead><tr><th scope="col" rowspan="2">Refugio</th><th scope="colgroup" colspan="4">Donativos</th><th scope="colgroup" colspan="6">Ventas</th>${view === "fondos" ? '<th scope="col" rowspan="2"><span class="tr-sr">Detalle</span></th>' : ""}</tr>
          <tr><th scope="col">Casos</th><th scope="col">Bruto</th><th scope="col">Comisión</th><th scope="col">Neto</th>
          <th scope="col">Pedidos</th><th scope="col">Bruto</th><th scope="col">Reembolsos</th><th scope="col">Comisión</th><th scope="col">Retenciones</th><th scope="col">Neto</th></tr></thead>
        <tbody>${rows}${others}</tbody></table></div>` : `<p class="tr-empty">Sin donativos ni ventas en el periodo.</p>`}
      ${view === "fondos" ? `<div class="tr-detail" id="tr-detalle-refugio" tabindex="-1" hidden></div>` : `<p><a href="transparencia-fondos.html">Ver el detalle por Refugio y por mes →</a></p>`}`;
  }

  /* ---------------------------------------------------------------- otras secciones */
  function moderation(m) {
    const items = [
      ["Reportes recibidos", esc(num(m.reportes_recibidos))],
      ["Contenidos retirados", esc(num(m.contenidos_retirados))],
      ["Retenidas por pedir dinero", esc(num(m.retenidas_por_pedir_dinero)), "Fichas de adopción que mencionaban cobros o venta"],
      ["Retiradas por venta o cobro", esc(num(m.retirados_por_venta_o_cobro))],
      ["Cuentas suspendidas", esc(num(m.cuentas_suspendidas))],
      ["Tiempo medio de atención", m.tiempo_medio_de_atencion_horas == null ? "—" : `${esc(m.tiempo_medio_de_atencion_horas.toLocaleString("es-MX"))} h`],
    ];
    const r = m.resultados || {};
    const ap = m.apelaciones;
    return `<h3 class="tr-h">Moderación</h3>${tiles(items)}
      ${barTable("Reportes recibidos por motivo", "Motivo", m.por_motivo)}
      ${barTable("Resultado de los reportes", "Resultado", [
        { texto: "Atendidos (con alguna medida)", casos: r.atendidos }, { texto: "Descartados (no incumplían las reglas)", casos: r.descartados },
        { texto: "En revisión", casos: r.abiertos }].filter((x) => x.casos))}
      ${m.retirados_por_deteccion ? barTable("Contenidos retirados según cómo se detectaron", "Detección", m.retirados_por_deteccion) : ""}
      ${ap ? tiles([["Apelaciones recibidas", esc(num(ap.recibidas))], ["Decisiones revertidas", esc(num(ap.decisiones_revertidas)),
        ap.porcentaje_revertidas == null ? "" : `${ap.porcentaje_revertidas.toLocaleString("es-MX")} % de las resueltas`]]) : ""}`;
  }

  function privacy(p) {
    return `<h3 class="tr-h">Solicitudes de privacidad (ARCO)</h3>
      ${tiles([["Solicitudes recibidas", esc(num(p.recibidas))], ["Respondidas", esc(num(p.respondidas))],
        ["Ampliaciones de plazo", esc(num(p.ampliaciones))], ["Revocaciones del consentimiento", esc(num(p.revocaciones))]])}
      ${meter("Respondidas en 20 días hábiles o menos", p.porcentaje_en_plazo)}
      ${barTable("Solicitudes por tipo", "Tipo", p.por_tipo)}
      ${barTable("Negativas por causa", "Causa", p.negativas_por_causa)}`;
  }

  function imported(i) {
    return `<h3 class="tr-h">Contenido importado</h3>
      <p class="tr-note">${i.importacion_activa ? "La importación de grupos públicos de Facebook está activa." : "La importación de grupos públicos de Facebook está desactivada; los envíos de voluntarios siguen activos."}</p>
      ${tiles([["Importadas de grupos", esc(num(i.importadas_de_grupos))], ["Enviadas por voluntarios", esc(num(i.enviadas_por_voluntarios))],
        ["Caducadas y borradas", esc(num(i.caducadas_y_borradas)), "A los 30 días, con borrado real"],
        ["Retiradas a petición de su autor", esc(num(i.retiradas_a_peticion))],
        ["Leídas y descartadas antes de guardarse", esc(num(i.leidas_y_no_guardadas_acumulado)), "Acumulado desde el inicio"]])}`;
  }

  function verified(v) {
    return `<h3 class="tr-h">Refugios y Clínicas verificados</h3>
      ${tiles([["Refugios verificados", esc(num(v.refugios_verificados)), "Hoy"], ["Clínicas verificadas", esc(num(v.clinicas_verificadas)), "Hoy"]])}
      <p><a href="verificacion.html">Qué revisamos para verificar →</a></p>`;
  }

  function authorities(a) {
    if (!a || !a.disponible) return `<h3 class="tr-h">Solicitudes de autoridades</h3><p class="tr-empty">Todavía no hay registro de solicitudes de autoridades.</p>`;
    return `<h3 class="tr-h">Solicitudes de autoridades</h3>
      ${tiles([["Requerimientos recibidos", esc(num(a.recibidas))], ["Denuncias y alertas que presentamos", esc(num(a.alertas_y_denuncias_enviadas))]])}
      ${barTable("Cómo atendimos los requerimientos", "Resultado", a.por_resultado)}
      <p><a href="autoridades.html">Cómo atendemos esas solicitudes →</a></p>`;
  }

  /* ---------------------------------------------------------------- detalle de un Refugio */
  async function openRefuge(root, refugeId, focus = true) {
    const box = root.querySelector("#tr-detalle-refugio");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = `<p class="tr-empty">Cargando…</p>`;
    try {
      const d = await get(`${API}/refugios/${encodeURIComponent(refugeId)}`);
      const r = d.refugio;
      const info = [["Ciudad", r.ciudad || "—"], ["Verificado desde", r.verificado_desde ? new Date(`${r.verificado_desde}T12:00:00Z`).toLocaleDateString("es-MX", { timeZone: TZ, day: "numeric", month: "long", year: "numeric" }) : "—"],
        ["Forma jurídica", r.forma_juridica || "Sin datos fiscales"], ["Donataria autorizada", r.donataria_autorizada ? "Sí (confírmalo en el directorio del SAT)" : "No: los donativos no son deducibles"],
        ["Cobra con su propia cuenta de Mercado Pago", r.cobra_con_su_cuenta_de_mercado_pago ? "Sí" : "No"]];
      box.innerHTML = `<h3 class="tr-h">A dónde va tu dinero: ${esc(r.nombre)}</h3>
        <p class="tr-meta">Últimos 12 meses · calculado el ${esc(fmtDateTime(d.calculado_en))}</p>
        <dl class="kv">${info.map(([a, b]) => `<dt>${esc(a)}</dt><dd>${esc(b)}</dd>`).join("")}</dl>
        ${d.publicado ? `${tiles([
          ["Donativos (bruto)", cell(d.totales.donativos, "bruto"), d.totales.donativos.suprimido ? "" : `${num(d.totales.donativos.casos)} donativos`],
          ["Donativos (neto)", cell(d.totales.donativos, "neto")],
          ["Ventas (bruto)", cell(d.totales.ventas, "bruto"), d.totales.ventas.suprimido ? "" : `${num(d.totales.ventas.casos)} pedidos`],
          ["Ventas (neto)", cell(d.totales.ventas, "neto"), "Después de comisión, reembolsos y retenciones"]])}
          ${charts(d.serie_mensual)}` : `<p class="tr-note">${esc(d.mensaje)}</p>`}
        <div class="sol-actions"><button type="button" class="tr-btn" data-close>Cerrar detalle</button></div>`;
      box.querySelector("[data-close]").addEventListener("click", () => { box.hidden = true; box.innerHTML = ""; });
      widths(box);
      if (focus) box.focus();
    } catch (err) {
      box.innerHTML = `<p class="tr-note warn">${esc(err.message)}</p>`;
    }
  }

  /* ---------------------------------------------------------------- arranque */
  function widths(root) {
    root.querySelectorAll("[data-w]").forEach((el) => { el.style.width = `${el.dataset.w}%`; });
  }

  function periodOptions(selected) {
    const now = new Date();
    const fmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit" });
    const [y, m] = fmt.format(now).split("-").map(Number);
    const out = [["12m", "Últimos 12 meses"]];
    for (let i = 0; i < 12; i++) {
      const total = y * 12 + (m - 1) - i;
      const p = `${Math.floor(total / 12)}-${String(total % 12 + 1).padStart(2, "0")}`;
      out.push([p, monthLabel(p)]);
    }
    return out.map(([v, l]) => `<option value="${v}"${v === selected ? " selected" : ""}>${esc(l)}</option>`).join("");
  }

  async function load(root, view, periodo) {
    const body = root.querySelector(".tr-body");
    body.setAttribute("aria-busy", "true");
    try {
      const data = await get(`${API}?vista=${encodeURIComponent(view)}&periodo=${encodeURIComponent(periodo)}`);
      k = data.umbral || 5;
      const label = data.periodo === "12m" ? "últimos 12 meses" : monthLabel(data.periodo);
      let html = `<p class="tr-meta">Cifras calculadas el <strong>${esc(fmtDateTime(data.calculado_en))}</strong> · Periodo: ${esc(label)}.
        Solo totales agregados; no publicamos desgloses con menos de ${esc(k)} casos.</p>`;
      html += funds(data.fondos, view);
      if (view === "general") {
        html += moderation(data.moderacion) + privacy(data.privacidad) + imported(data.importados)
          + verified(data.verificados) + authorities(data.autoridades);
      }
      body.innerHTML = html;
      widths(body);
      body.querySelectorAll("[data-refugio]").forEach((b) => b.addEventListener("click", () => openRefuge(root, b.dataset.refugio)));
    } catch (err) {
      body.innerHTML = `<p class="tr-note warn">${esc(err.message)}</p>`;
    } finally { body.removeAttribute("aria-busy"); }
  }

  function init() {
    const root = document.getElementById("transparencia-metricas");
    if (!root || root.dataset.trMounted) return;
    root.dataset.trMounted = "1";
    const view = root.dataset.vista === "fondos" ? "fondos" : "general";
    const params = new URLSearchParams(location.search);
    const periodo = /^(12m|\d{4}-\d{2})$/.test(params.get("periodo") || "") ? params.get("periodo") : "12m";
    root.innerHTML = `<form class="tr-controls" novalidate><label for="tr-periodo">Periodo</label>
      <select id="tr-periodo" name="periodo">${periodOptions(periodo)}</select></form>
      <div class="tr-body" aria-live="polite"><p class="tr-empty">Cargando cifras…</p></div>`;
    const select = root.querySelector("#tr-periodo");
    select.addEventListener("change", () => load(root, view, select.value));
    load(root, view, periodo).then(() => {
      const refugio = params.get("refugio");
      if (view === "fondos" && /^\d{1,10}$/.test(refugio || "")) openRefuge(root, refugio);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
