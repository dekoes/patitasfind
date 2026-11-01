/* ============================================================
   GuauWoow Admin — Facebook (F2)
   - Catálogo de grupos públicos por estado (proveedor externo: Apify):
     filtros, alta/edición, activar/pausar, importación CSV, estadísticas por grupo,
     gasto del día contra el presupuesto y lectura manual.
   - Páginas de Facebook (Graph API), fuentes manuales e importación manual de publicaciones
     (lo que antes vivía en admin.js).
   Se carga después de admin.js y usa sus utilidades globales
   (api, jsonOpts, run, escapeHtml, link, fmtDate, el, button, renderTable, $).
   ============================================================ */
"use strict";

/* Nombres oficiales cortos (los mismos que backend/app/data/estados_mx.py); "México" es el Estado de México */
const FB_STATES = [
  "Aguascalientes", "Baja California", "Baja California Sur", "Campeche", "Chiapas", "Chihuahua", "Ciudad de México",
  "Coahuila", "Colima", "Durango", "Guanajuato", "Guerrero", "Hidalgo", "Jalisco", "México", "Michoacán", "Morelos",
  "Nayarit", "Nuevo León", "Oaxaca", "Puebla", "Querétaro", "Quintana Roo", "San Luis Potosí", "Sinaloa", "Sonora",
  "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz", "Yucatán", "Zacatecas",
];
const FB_STATE_LABEL = { "México": "Estado de México" };
const fbStateLabel = (s) => FB_STATE_LABEL[s] || s || "";
const FB_NO_STATE = "__sin_estado__";
const FB_CSV_HEADER = ["name", "state", "city", "group_url", "active"];  // "active" es opcional (vacío = pausado)
const FB_GROUP_URL_RE = /^https?:\/\/(?:www\.|m\.|web\.|mobile\.|touch\.)?facebook\.com\/groups\/[A-Za-z0-9._-]+\/?(?:[?#].*)?$/i;

const fbAdmin = { groups: [], stats: null, editing: null, filters: { state: "", active: "", q: "" } };

/* Moderación (admin.js): etiqueta del motivo de las solicitudes «Soy el autor: retirar» que llegan sin cuenta.
   El reporte ya está oculto; si no descartas la solicitud, su texto y fotos se borran a las 72 h. */
if (typeof REASON_ES === "object" && REASON_ES) REASON_ES.retiro_autor = "Retiro pedido por el autor (sin cuenta)";

/* El primer valor definido entre varias claves posibles (el backend puede nombrar distinto algunos totales) */
function fbPick(obj, ...keys) {
  if (!obj || typeof obj !== "object") return undefined;
  for (const k of keys) if (obj[k] !== undefined && obj[k] !== null) return obj[k];
  return undefined;
}
const fbNum = (v) => (v === undefined || v === null || v === "" || Number.isNaN(Number(v)) ? null : Number(v));
function fbUsd(v, digits = 2) {
  const n = fbNum(v);
  return n === null ? "-" : `$${n.toLocaleString("es-MX", { minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, 4) })} USD`;
}
const fbInt = (v) => (fbNum(v) === null ? "0" : Number(v).toLocaleString("es-MX"));

/* Estilos propios de esta sección (barra de gasto, aviso del proveedor, chips de estados) */
(function fbInjectStyles() {
  const css = `
  .fb-banner { background: var(--card); border-radius: 10px; padding: .85rem 1rem; margin-bottom: 1rem; display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }
  .fb-banner code { background: var(--bg); padding: .1rem .35rem; border-radius: 4px; }
  .fb-meter { height: 12px; background: var(--bg); border-radius: 999px; overflow: hidden; margin: .5rem 0 .25rem; }
  .fb-meter > i { display: block; height: 100%; border-radius: 999px; background: var(--success); transition: width .4s; }
  .fb-meter.warn > i { background: #d97706; }
  .fb-meter.full > i { background: var(--danger); }
  .fb-chips { display: flex; flex-wrap: wrap; gap: .35rem; margin-top: .5rem; }
  .fb-chips .badge { font-weight: 500; }
  .fb-error { color: var(--danger); font-size: .8rem; max-width: 220px; display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
  .fb-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
  .fb-check { flex-direction: row !important; align-items: center; gap: .4rem; }
  .fb-check input { width: auto; min-width: 0 !important; }
  #facebook .table-wrap td { vertical-align: top; }`;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.append(style);
})();

function fbFillStateSelect(sel, firstLabel, withNone = false) {
  if (!sel || sel.options.length > 1) return;
  sel.innerHTML = "";
  sel.append(el("option", { value: "", text: firstLabel }));
  if (withNone) sel.append(el("option", { value: FB_NO_STATE, text: "Sin estado" }));
  FB_STATES.forEach((s) => sel.append(el("option", { value: s, text: fbStateLabel(s) })));
}

/* ------------------------------------------------------------------ carga */
async function loadFacebook() {
  fbFillStateSelect($("#fbg-filter-state"), "Todos los estados", true);
  fbFillStateSelect($("#fbg-state"), "Elige el estado");
  await Promise.all([fbLoadStats(), fbLoadGroups(), fbLoadPagesStatus(), fbLoadPages()].map((p) => p.catch((err) => {
    if (!err.silent) console.warn(err);
  })));
  fbRenderSummary();
  if (fbAdmin.groups.length || $("#fbg-table").querySelector("table")) fbRenderGroups();  // con las estadísticas ya cargadas
}

async function fbLoadStats() {
  try {
    fbAdmin.stats = await api("/admin/facebook/stats");
  } catch (err) {
    fbAdmin.stats = null;
    if (err.silent) throw err;
    $("#fb-provider").innerHTML = `<span class="badge bad">Sin estadísticas</span> No pudimos leer <code>/admin/facebook/stats</code>: ${escapeHtml(err.message)}`;
    return;
  }
  fbRenderProvider();
}

/* Catálogo de grupos públicos: GET /admin/facebook/groups?kind=group[&state=] (lista completa, sin paginar).
   "Sin estado", situación y búsqueda se filtran aquí. */
async function fbFetchGroups() {
  const params = new URLSearchParams({ kind: "group" });
  const { state } = fbAdmin.filters;
  if (state && state !== FB_NO_STATE) params.set("state", state);
  const res = await api(`/admin/facebook/groups?${params}`);
  return Array.isArray(res) ? res : (res && (res.items || res.groups)) || [];
}

async function fbLoadGroups() {
  let groups;
  try {
    groups = await fbFetchGroups();
  } catch (err) {
    if (err.silent) throw err;
    $("#fbg-table").innerHTML = `<p class="error">No pudimos cargar los grupos: ${escapeHtml(err.message)}</p>`;
    fbAdmin.groups = [];
    return;
  }
  fbAdmin.groups = groups.filter((g) => !g.kind || g.kind === "group");
  fbRenderGroups();
}

/* ------------------------------------------------------------------ proveedor y gasto */
function fbSettings() {
  const st = fbAdmin.stats || {};
  return st.settings || st.config || {};
}

function fbProviderInfo() {
  const st = fbAdmin.stats || {};
  const prov = typeof st.provider === "object" && st.provider ? st.provider : {};
  const configured = fbPick(st, "provider_configured", "configured", "enabled", "fb_groups_enabled", "apify_configured")
    ?? fbPick(prov, "configured", "enabled");
  return {
    configured: configured === true,
    name: (typeof st.provider === "string" ? st.provider : fbPick(prov, "name")) || "apify",
    actor: fbPick(st, "actor", "apify_actor", "apify_fb_groups_actor") || fbPick(prov, "actor") || fbPick(fbSettings(), "apify_fb_groups_actor", "actor"),
  };
}

/* GET /admin/facebook/stats → budget {daily_budget_usd, spent_today_usd, remaining_usd, exhausted, cost_per_1000_posts_usd} */
function fbBudgetInfo() {
  const st = fbAdmin.stats || {};
  const b = typeof st.budget === "object" && st.budget ? st.budget : {};
  const d = st.daily && typeof st.daily === "object" && !Array.isArray(st.daily) ? st.daily : {};
  const spent = fbNum(fbPick(st, "spent_today_usd", "spent_today", "daily_spend_usd", "spend_today_usd", "today_spent_usd")
    ?? fbPick(b, "spent_today_usd", "spent_usd", "spent") ?? fbPick(d, "spent_usd", "spent"));
  const budget = fbNum(fbPick(st, "daily_budget_usd", "budget_usd") ?? (typeof st.budget === "number" ? st.budget : undefined)
    ?? fbPick(b, "daily_budget_usd", "budget_usd", "limit_usd", "limit", "daily") ?? fbPick(d, "budget_usd", "budget")
    ?? fbPick(fbSettings(), "fb_groups_daily_budget_usd", "daily_budget_usd"));
  let remaining = fbNum(fbPick(st, "remaining_usd", "remaining_budget_usd", "remaining") ?? fbPick(b, "remaining_usd", "remaining"));
  if (remaining === null && spent !== null && budget !== null) remaining = Math.max(0, budget - spent);
  const exhausted = fbPick(b, "exhausted") === true || (budget !== null && spent !== null && budget > 0 && spent >= budget);
  return { spent, budget, remaining, exhausted };
}

function fbRenderProvider() {
  const p = fbProviderInfo();
  const s = fbSettings();
  const interval = fbPick(s, "fb_groups_fetch_interval_hours", "fetch_interval_hours");
  const ttl = fbPick(s, "fb_groups_post_ttl_days", "post_ttl_days");
  const extra = [
    interval ? `cada grupo se lee como máximo cada ${escapeHtml(interval)} h` : "",
    ttl ? `los reportes importados caducan a los ${escapeHtml(ttl)} días de publicados y luego se borran` : "",
  ].filter(Boolean).join(" · ");
  $("#fb-provider").innerHTML = p.configured
    ? `<span class="badge ok">Proveedor configurado</span> ${escapeHtml(p.name === "apify" ? "Apify" : p.name)}${p.actor ? ` · actor <code>${escapeHtml(p.actor)}</code>` : ""}${extra ? ` · ${extra}` : ""}.`
    : `<span class="badge warn">Proveedor no configurado (APIFY_TOKEN)</span> Puedes armar el catálogo de grupos; no se leerá ninguno hasta configurar <code>APIFY_TOKEN</code> en el servidor.`;
  // Interruptor legal: sin FB_GROUPS_ENABLED=true no se importa nada aunque el proveedor esté configurado
  if ((fbAdmin.stats || {}).import_enabled === false) {
    $("#fb-provider").innerHTML += ` <span class="badge warn">Importación apagada (FB_GROUPS_ENABLED=false)</span> No se lee ningún grupo hasta que el dueño la active con la opinión legal registrada (FB_GROUPS_LEGAL_OPINION_REF).`;
  }
}

/* Todos los grupos (sin el filtro de estado de la tabla): los de /admin/facebook/stats si llegaron */
function fbAllGroups() {
  const rows = fbPick(fbAdmin.stats || {}, "groups", "per_group");
  return Array.isArray(rows) ? rows : fbAdmin.groups;
}

function fbRenderSummary() {
  const groups = fbAllGroups();
  const active = groups.filter((g) => g.is_active);
  const coveredStates = new Set(active.map((g) => g.state).filter(Boolean));
  const sum = (key) => groups.reduce((acc, g) => acc + (fbNum(g[key]) || 0), 0);
  const { spent, budget, remaining, exhausted } = fbBudgetInfo();
  const st = fbAdmin.stats || {};

  let meter = "";
  if (budget !== null && budget > 0 && spent !== null) {
    const pct = Math.min(100, Math.round((spent / budget) * 100));
    const cls = pct >= 100 || exhausted ? "full" : pct >= 75 ? "warn" : "";
    meter = `<div class="fb-meter ${cls}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="Gasto del día"><i style="width:${pct}%"></i></div>
      <div class="hint">${fbUsd(spent)} de ${fbUsd(budget)} (${pct} %) · quedan ${fbUsd(remaining)}${exhausted ? " · <strong>Presupuesto del día agotado:</strong> las lecturas se reanudan mañana (00:00 UTC)." : ""}</div>`;
  } else if (fbAdmin.stats) {
    meter = `<div class="hint">Gasto de hoy: ${fbUsd(spent)}${budget !== null ? ` de ${fbUsd(budget)}` : ""}</div>`;
  } else {
    meter = '<div class="hint">Sin datos de gasto.</div>';
  }

  const postsToday = fbNum(fbPick(st, "posts_today", "posts_fetched_today"));
  const reportsToday = fbNum(fbPick(st, "reports_today", "reports_created_today"));
  const totals = st.totals && typeof st.totals === "object" ? st.totals : {};
  const volunteerReports = fbNum(fbPick(totals, "volunteer_reports"));
  const missing = FB_STATES.filter((s) => !coveredStates.has(s));
  $("#fb-spend").innerHTML = `
    <div class="fb-grid">
      <div class="panel">
        <h3>Gasto de hoy contra el presupuesto diario</h3>
        ${meter}
        ${postsToday !== null || reportsToday !== null ? `<div class="hint">Hoy: ${fbInt(postsToday)} publicaciones leídas · ${fbInt(reportsToday)} reportes creados</div>` : ""}
      </div>
      <div class="panel">
        <h3>Catálogo</h3>
        <div class="mini-stats">
          <div class="mini-stat"><span>Grupos activos</span><strong>${active.length} de ${groups.length}</strong></div>
          <div class="mini-stat"><span>Estados cubiertos</span><strong>${coveredStates.size} de ${FB_STATES.length}</strong></div>
          <div class="mini-stat"><span>Publicaciones leídas</span><strong>${fbInt(sum("posts_fetched_total"))}</strong></div>
          <div class="mini-stat"><span>Reportes creados</span><strong>${fbInt(sum("reports_created_total"))}</strong></div>
          <div class="mini-stat"><span>Costo estimado acumulado</span><strong>${fbUsd(sum("cost_estimate_total"))}</strong></div>
          ${volunteerReports !== null ? `<div class="mini-stat"><span>Reportes de voluntarios</span><strong>${fbInt(volunteerReports)}</strong></div>` : ""}
        </div>
      </div>
    </div>
    ${missing.length && !fbAdmin.filters.state ? `<div class="panel" style="margin-bottom:1rem"><h3>Estados sin grupos activos (${missing.length})</h3><div class="fb-chips">${missing.map((s) => `<span class="badge warn">${escapeHtml(fbStateLabel(s))}</span>`).join("")}</div></div>` : ""}`;
  fbRenderHistory();
}

/* Historial de gasto por día (stats.daily = [{date, spent_usd}], últimos 7 días) */
function fbRenderHistory() {
  const st = fbAdmin.stats || {};
  const days = [st.daily, st.days, st.history, st.daily_history].find(Array.isArray);
  const box = $("#fbg-history");
  const title = $("#fbg-history-title");
  if (!Array.isArray(days) || !days.length) {
    box.innerHTML = "";
    title.classList.add("hidden");
    return;
  }
  title.classList.remove("hidden");
  const { budget } = fbBudgetInfo();
  const hasCounts = days.some((d) => fbPick(d, "posts", "posts_fetched", "reports", "reports_created") !== undefined);
  const rows = days.map((d) => {
    const spentDay = fbNum(fbPick(d, "spent_usd", "spent", "usd", "cost_usd"));
    const row = [
      escapeHtml(fbPick(d, "date", "day") || "-"),
      fbUsd(spentDay),
      budget ? `${Math.min(100, Math.round(((spentDay || 0) / budget) * 100))} %` : "-",
    ];
    if (hasCounts) row.push(fbInt(fbPick(d, "posts", "posts_fetched")), fbInt(fbPick(d, "reports", "reports_created")));
    return row;
  });
  renderTable("fbg-history", ["Día (UTC)", "Gasto estimado", "Del presupuesto"].concat(hasCounts ? ["Publicaciones", "Reportes"] : []), rows);
}

/* ------------------------------------------------------------------ tabla de grupos */
function fbGroupStats(g) {
  // Estadísticas por grupo de /admin/facebook/stats solo completan lo que falte: los datos del propio grupo
  // (lista recién pedida) mandan, porque stats puede llegar antes o después y traer is_active viejo
  const list = fbPick(fbAdmin.stats || {}, "groups", "per_group");
  const extra = Array.isArray(list) ? list.find((x) => (x.id ?? x.group_id) === g.id) : null;
  const own = Object.fromEntries(Object.entries(g).filter(([, v]) => v !== undefined && v !== null));
  return { ...(extra || {}), ...own, id: g.id };
}

function fbFilteredGroups() {
  const { state, active, q } = fbAdmin.filters;
  const needle = q.trim().toLowerCase();
  return fbAdmin.groups.filter((g) => {
    if (state === FB_NO_STATE && g.state) return false;
    if (state && state !== FB_NO_STATE && g.state !== state) return false;
    if (active === "true" && !g.is_active) return false;
    if (active === "false" && g.is_active) return false;
    if (needle && ![g.name, g.city, g.group_url || g.url, g.state].some((v) => String(v || "").toLowerCase().includes(needle))) return false;
    return true;
  }).sort((a, b) => String(a.state || "~").localeCompare(String(b.state || "~"), "es") || String(a.name).localeCompare(String(b.name), "es"));
}

function fbRenderGroups() {
  const groups = fbFilteredGroups();
  $("#fbg-count").textContent = `${groups.length} grupo(s)${groups.length !== fbAdmin.groups.length ? ` de ${fbAdmin.groups.length}` : ""}`;
  const rows = groups.map((raw) => {
    const g = fbGroupStats(raw);
    const url = g.group_url || g.url;
    const err = g.last_error ? `<span class="fb-error" title="${escapeHtml(g.last_error)}">${escapeHtml(g.last_error)}</span>` : "-";
    const actions = [
      button("Leer ahora", () => fbFetchNow(g), ""),
      button("Editar", () => fbEdit(g), "btn-secondary"),
      button(g.is_active ? "Pausar" : "Activar", () => fbToggle(g), "btn-secondary"),
      button("Eliminar", () => fbDelete(g), "btn-danger"),
    ];
    return [
      g.id,
      `<strong>${escapeHtml(g.name)}</strong><br>${link(url, "Abrir grupo")}`,
      escapeHtml(fbStateLabel(g.state) || "-"),
      escapeHtml(g.city || "-"),
      g.is_active ? '<span class="badge ok">Activo</span>' : '<span class="badge warn">Pausado</span>',
      g.last_fetched_at ? fmtDate(g.last_fetched_at) : "Nunca",
      g.last_post_at ? fmtDate(g.last_post_at) : "-",
      fbInt(g.posts_fetched_total),
      fbInt(g.reports_created_total),
      fbUsd(g.cost_estimate_total, 2),
      err,
      actions,
    ];
  });
  renderTable("fbg-table", ["ID", "Grupo", "Estado", "Ciudad", "Situación", "Última lectura", "Última publicación",
    "Leídas", "Reportes", "Costo estimado", "Último error", "Acciones"], rows);
}

/* ------------------------------------------------------------------ acciones por grupo */
/* Costo máximo de una corrida: publicaciones × precio + arranque (el backend lo manda como budget.max_run_cost_usd) */
function fbMaxRunCost() {
  const s = fbSettings();
  const b = (fbAdmin.stats && fbAdmin.stats.budget) || {};
  const direct = fbNum(fbPick(b, "max_run_cost_usd"));
  if (direct !== null) return direct;
  const posts = fbNum(fbPick(s, "fb_groups_max_posts_per_run", "max_posts_per_run"));
  const per1000 = fbNum(fbPick(s, "fb_groups_cost_per_1000_posts_usd", "cost_per_1000_posts_usd") ?? fbPick(b, "cost_per_1000_posts_usd"));
  const perRun = fbNum(fbPick(s, "fb_groups_cost_per_run_usd", "cost_per_run_usd") ?? fbPick(b, "cost_per_run_usd")) || 0;
  return posts !== null && per1000 !== null ? (posts * per1000) / 1000 + perRun : null;
}

function fbFetchNow(g) {
  run(async () => {
    if (!fbProviderInfo().configured && fbAdmin.stats) {
      alert("Proveedor no configurado (APIFY_TOKEN). Configúralo en el servidor para leer grupos.");
      return;
    }
    const max = fbMaxRunCost();
    const costTxt = max !== null ? ` (hasta ${fbUsd(max)})` : "";
    if (!confirm(`¿Leer ahora "${g.name}"? Cuenta para el presupuesto del día${costTxt}.`)) return;
    const res = await api(`/admin/facebook/groups/${g.id}/fetch`, { method: "POST" });
    alert(fbFetchMessage(res));
    loadFacebook();
  });
}

function fbFetchMessage(res) {
  if (!res || typeof res !== "object") return "Lectura encargada.";
  if (res.message && res.posts === undefined) return res.message;
  const err = fbPick(res, "error", "last_error");
  if (err) return `El proveedor respondió con un error: ${err}`;
  if (res.skipped || res.reason) return `No se leyó: ${res.reason || res.skipped}`;
  if (res.queued || res.task_id) return "Lectura encargada. Los resultados aparecerán en la tabla en unos minutos.";
  const created = Array.isArray(res.created) ? res.created.length : fbNum(res.created ?? res.reports_created) || 0;
  return `Listo: ${fbInt(res.posts ?? res.posts_fetched)} publicaciones leídas, ${created} reporte(s) nuevo(s), costo estimado ${fbUsd(res.cost ?? res.cost_usd)}.`;
}

function fbEdit(g) {
  fbAdmin.editing = g.id;
  $("#fbg-form-title").textContent = `Editar grupo #${g.id}`;
  $("#fbg-name").value = g.name || "";
  $("#fbg-url").value = g.group_url || g.url || "";
  $("#fbg-state").value = g.state || "";
  $("#fbg-city").value = g.city || "";
  $("#fbg-active").checked = !!g.is_active;
  $("#fbg-form-wrap").classList.remove("hidden");
  $("#fbg-name").focus();
  $("#fbg-form-wrap").scrollIntoView({ behavior: "smooth", block: "center" });
}

function fbNew() {
  fbAdmin.editing = null;
  $("#fbg-form").reset();
  $("#fbg-active").checked = true;
  if (fbAdmin.filters.state && fbAdmin.filters.state !== FB_NO_STATE) $("#fbg-state").value = fbAdmin.filters.state;
  $("#fbg-form-title").textContent = "Agregar grupo público";
  $("#fbg-form-wrap").classList.remove("hidden");
  $("#fbg-name").focus();
}

function fbCloseForm() {
  fbAdmin.editing = null;
  $("#fbg-form").reset();
  $("#fbg-form-wrap").classList.add("hidden");
}

function fbToggle(g) {
  run(async () => {
    await api(`/admin/facebook/groups/${g.id}`, jsonOpts("PATCH", { is_active: !g.is_active }));
    loadFacebook();
  });
}

function fbDelete(g) {
  run(async () => {
    if (!confirm(`¿Eliminar el grupo "${g.name}"? Los reportes que ya importó se conservan hasta que caduquen.`)) return;
    await api(`/admin/facebook/groups/${g.id}`, { method: "DELETE" });
    if (fbAdmin.editing === g.id) fbCloseForm();
    loadFacebook();
  });
}

$("#fbg-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const groupUrl = $("#fbg-url").value.trim();
  if (!FB_GROUP_URL_RE.test(groupUrl)) {
    alert("La URL debe ser la de un grupo público: https://www.facebook.com/groups/<nombre o número>");
    return;
  }
  const state = $("#fbg-state").value;
  if (!state) { alert("Elige el estado que cubre el grupo."); return; }
  const data = {
    name: $("#fbg-name").value.trim(),
    group_url: groupUrl,
    state,
    city: $("#fbg-city").value.trim() || null,
    is_active: $("#fbg-active").checked,
  };
  run(async () => {
    if (fbAdmin.editing) {
      await api(`/admin/facebook/groups/${fbAdmin.editing}`, jsonOpts("PATCH", data));
    } else {
      await api("/admin/facebook/groups", jsonOpts("POST", { ...data, kind: "group", url: groupUrl }));
    }
    fbCloseForm();
    loadFacebook();
  });
});

$("#fbg-add-btn").addEventListener("click", fbNew);
$("#fbg-cancel").addEventListener("click", fbCloseForm);

/* ------------------------------------------------------------------ filtros */
function fbApplyFilters() {
  const prevState = fbAdmin.filters.state;
  fbAdmin.filters = { state: $("#fbg-filter-state").value, active: $("#fbg-filter-active").value, q: $("#fbg-filter-q").value };
  // El estado se filtra también en el servidor; activos y búsqueda, aquí
  if (prevState !== fbAdmin.filters.state) run(async () => { await fbLoadGroups(); fbRenderSummary(); });
  else fbRenderGroups();
}
$("#fbg-filter-btn").addEventListener("click", fbApplyFilters);
$("#fbg-filter-state").addEventListener("change", fbApplyFilters);
$("#fbg-filter-active").addEventListener("change", fbApplyFilters);
$("#fbg-filter-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); fbApplyFilters(); } });

/* ------------------------------------------------------------------ importación CSV */
/* Revisión rápida antes de enviar (el backend valida cada fila): separa por comas o por punto y coma
   (Excel en español guarda con ";"), respeta comillas y acepta los encabezados en español que acepta el backend. */
const FB_CSV_ALIASES = { nombre: "name", estado: "state", ciudad: "city", municipio: "city", url: "group_url", url_grupo: "group_url", enlace: "group_url", activo: "active", is_active: "active" };
const FB_CSV_MAX_BYTES = 512 * 1024;

function fbParseCsvLine(line, delim = ",") {
  const out = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') quoted = false; else cur += c;
    } else if (c === '"') quoted = true;
    else if (c === delim) { out.push(cur); cur = ""; } else cur += c;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

function fbCheckCsv(text) {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return "El archivo está vacío.";
  const first = lines[0];
  const delim = (first.match(/;/g) || []).length > (first.match(/,/g) || []).length ? ";" : ",";
  const header = fbParseCsvLine(first, delim).map((h) => { const k = h.toLowerCase(); return FB_CSV_ALIASES[k] || k; });
  const missing = ["name", "state", "group_url"].filter((h) => !header.includes(h));
  if (missing.length) return `Faltan columnas en el encabezado: ${missing.join(", ")}. El formato es: ${FB_CSV_HEADER.join(",")} (active es opcional)`;
  if (lines.length < 2) return "El archivo solo tiene el encabezado.";
  return "";
}

function fbCsvResultHtml(res) {
  if (!res || typeof res !== "object") return "Importación terminada.";
  const created = fbNum(fbPick(res, "created", "inserted", "added"));
  const updated = fbNum(fbPick(res, "updated"));
  const skipped = fbNum(fbPick(res, "skipped", "duplicates", "unchanged"));
  const errors = fbPick(res, "errors", "invalid") || [];
  const parts = [];
  if (created !== null) parts.push(`${created} nuevo(s)`);
  if (updated !== null) parts.push(`${updated} actualizado(s)`);
  if (skipped !== null) parts.push(`${skipped} sin cambios u omitido(s)`);
  const paused = fbNum(fbPick(res, "created_paused"));
  if (paused) parts.push(`${paused} nuevo(s) pausado(s): pruébalos con «Leer ahora» y actívalos`);
  let html = `<span class="badge ok">Importado</span> ${escapeHtml(parts.join(" · ") || res.message || "Listo")}`;
  if (Array.isArray(errors) && errors.length) {
    const items = errors.slice(0, 20).map((er) => {
      if (typeof er === "string") return `<li>${escapeHtml(er)}</li>`;
      const line = fbPick(er, "line", "row");
      return `<li>${line !== undefined ? `Línea ${escapeHtml(line)}: ` : ""}${escapeHtml(fbPick(er, "error", "detail", "message") || JSON.stringify(er))}</li>`;
    }).join("");
    html += `<br><span class="badge bad">${errors.length} fila(s) con error</span><ul>${items}</ul>${errors.length > 20 ? "<p>…</p>" : ""}`;
  }
  return html;
}

$("#fbg-csv-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const file = $("#fbg-csv-file").files[0];
  const out = $("#fbg-csv-result");
  if (!file) { alert("Elige un archivo CSV."); return; }
  if (file.size > FB_CSV_MAX_BYTES) { alert("El CSV pesa más de 512 KB. Divídelo en varios archivos."); return; }
  run(async () => {
    const text = await file.text();
    const problem = fbCheckCsv(text);
    if (problem) { out.innerHTML = `<span class="badge bad">CSV no válido</span> ${escapeHtml(problem)}`; return; }
    out.textContent = "Importando…";
    let res;
    try {
      // Se manda el archivo original: el backend acepta UTF-8 y también Latin-1 (CSV de Excel en Windows)
      const fd = new FormData();
      fd.append("file", file, file.name || "grupos.csv");
      res = await api("/admin/facebook/groups/import-csv", { method: "POST", body: fd });
    } catch (err) {
      // Si el backend espera el texto en JSON en lugar de un archivo
      if (err.status !== 422 && err.status !== 415) { out.innerHTML = `<span class="badge bad">Error</span> ${escapeHtml(err.message)}`; throw err; }
      res = await api("/admin/facebook/groups/import-csv", jsonOpts("POST", { csv: text }));
    }
    out.innerHTML = fbCsvResultHtml(res);
    e.target.reset();
    loadFacebook();
  });
});

/* Plantilla de ejemplo (los datos de ejemplo NO son grupos reales) */
$("#fbg-csv-template").addEventListener("click", (e) => {
  e.preventDefault();
  const csv = "﻿" + FB_CSV_HEADER.join(",") + "\n"
    + "\"Perritos perdidos Zapopan (ejemplo, reemplázalo)\",Jalisco,Zapopan,https://www.facebook.com/groups/ejemplo-zapopan,no\n"
    + "\"Mascotas perdidas Monterrey (ejemplo, reemplázalo)\",Nuevo León,Monterrey,https://www.facebook.com/groups/ejemplo-monterrey,no\n";
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = el("a", { href: url, download: "grupos-facebook-plantilla.csv" });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
});

/* ------------------------------------------------------------------ Páginas (Graph API) y fuentes manuales */
async function fbLoadPagesStatus() {
  const st = await api("/facebook/status");
  $("#facebook-status").innerHTML = st.pages_enabled
    ? `<span class="badge ok">Páginas conectadas</span> Graph API ${escapeHtml(st.graph_api_version)}. Las páginas se leen cada hora.`
    : '<span class="badge warn">Sin token de página</span> Las Páginas no se leen; la importación manual sí funciona.';
}

async function fbLoadPages() {
  const sources = (await api("/facebook/groups")).filter((g) => g.kind !== "group");
  const rows = sources.map((g) => {
    const actions = [];
    if (g.kind === "page") {
      actions.push(button("Leer ahora", () => run(async () => {
        const res = await api(`/facebook/scrape?group_id=${g.id}`, { method: "POST" });
        alert(res.message);
        loadFacebook();
      })));
    }
    actions.push(button("Eliminar", () => run(async () => {
      if (!confirm(`¿Eliminar la fuente "${g.name}"?`)) return;
      await api(`/facebook/groups/${g.id}`, { method: "DELETE" });
      loadFacebook();
    }), "btn-danger"));
    return [
      g.id, escapeHtml(g.name), g.kind === "page" ? "Página" : "Manual", escapeHtml(g.page_id || "-"),
      link(g.url, g.url), escapeHtml(g.city || "-"),
      g.last_scraped ? fmtDate(g.last_scraped) : "Nunca", actions,
    ];
  });
  renderTable("facebook-table", ["ID", "Nombre", "Tipo", "ID página", "URL", "Ciudad", "Última lectura", "Acciones"], rows);
}

$("#facebook-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const kind = $("#fb-kind").value;
  const data = {
    name: $("#fb-name").value,
    url: $("#fb-url").value,
    kind,
    page_id: $("#fb-page-id").value.trim() || null,
    city: $("#fb-city").value.trim() || null,
  };
  run(async () => {
    await api("/facebook/groups", jsonOpts("POST", data));
    e.target.reset();
    loadFacebook();
  });
});

$("#facebook-scrape-all").addEventListener("click", () => run(async () => {
  const res = await api("/facebook/scrape-all", { method: "POST" });
  alert(res.message);
  loadFacebook();
}));

$("#facebook-import-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const data = {
    post_url: $("#fbi-url").value.trim() || null,
    text: $("#fbi-text").value,
    image_urls: $("#fbi-images").value.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 3),
    report_type: $("#fbi-type").value,
    city: $("#fbi-city").value.trim() || null,
  };
  run(async () => {
    const report = await api("/facebook/import", jsonOpts("POST", data));
    $("#facebook-import-result").innerHTML = `Reporte #${report.id} creado con ${(report.photos || []).length} foto(s). Buscando coincidencias…`;
    e.target.reset();
  });
});
