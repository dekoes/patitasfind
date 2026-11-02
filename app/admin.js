const API_BASE = "";
const TOKEN_KEY = "patitasfind_admin_token";
const PAGE_SIZE = 25;

let currentToken = localStorage.getItem(TOKEN_KEY);
const adminState = {
  dogs: { page: 0, status: "", city: "" },
  matches: { page: 0, status: "" },
  users: { page: 0 },
  orders: { status: "" },
  donations: { status: "" },
  lost: { status: "", source: "" },
  reports: { status: "open", page: 0 },
  audit: { page: 0, action: "" },
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (currentToken) headers.Authorization = `Bearer ${currentToken}`;
  let res;
  try { res = await fetch(`${API_BASE}${path}`, { ...options, headers }); }
  catch { throw new Error("Sin conexión con el servidor."); }
  let body = null;
  const text = await res.text();
  // Las páginas de error HTML (p. ej. el 429 de Nginx) no se muestran tal cual
  if (text) {
    try { body = JSON.parse(text); } catch { body = null; }
  }
  if (res.status === 401) {
    // Token vencido (las sesiones de admin duran 8 horas) o revocado
    logout("Tu sesión expiró. Inicia sesión de nuevo.");
    const err = new Error("Tu sesión expiró. Inicia sesión de nuevo.");
    err.silent = true;
    throw err;
  }
  if (!res.ok) {
    let detail = body?.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join(", ");
    if (typeof detail !== "string" || !detail) {
      detail = res.status === 429 ? "Demasiadas solicitudes seguidas. Espera un momento e inténtalo de nuevo."
        : res.status >= 500 ? "Error del servidor. Inténtalo de nuevo en un momento." : `Error ${res.status}`;
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return body;
}

const jsonOpts = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

// Ejecuta una acción y muestra el error en un alert en lugar de fallar en silencio
async function run(fn) {
  try { return await fn(); } catch (err) { if (!err.silent) alert(err.message); }
}

// Escapa también comillas: los valores se usan dentro de atributos (href, src, title)
function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Solo se enlazan rutas /uploads/ del sitio, blob: (documentos descargados) y https:
function safeUrl(url) {
  const s = String(url ?? "").trim();
  return /^(\/uploads\/|blob:|https:\/\/)[^\s"'<>`]+$/i.test(s) ? s : "";
}

function link(url, label) {
  const safe = safeUrl(url);
  return safe ? `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label ?? url)}</a>` : escapeHtml(label ?? url ?? "-");
}

// El backend guarda UTC sin zona ("2026-10-17T17:55:06"): sin "Z" el navegador lo leería como hora local
const fmtDate = (d) => {
  if (!d) return "-";
  const iso = String(d);
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) || !iso.includes("T") ? iso : iso + "Z").toLocaleString("es-MX");
};
const fmtMoney = (n) => Number(n || 0).toLocaleString("es-MX", { style: "currency", currency: "MXN" });

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "onclick") node.addEventListener("click", v);
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  });
  [].concat(children).forEach((c) => c != null && node.append(c));
  return node;
}

// Mientras la acción (una promesa, p. ej. run(...)) está en curso el botón se desactiva: un segundo clic en
// «Reembolsar», «Cancelar» o «Aceptar pago» no manda una segunda operación de dinero.
function button(label, onclick, className = "") {
  const node = el("button", { class: className, text: label });
  node.addEventListener("click", async (ev) => {
    if (node.disabled) return;
    node.disabled = true;
    try { await onclick(ev); } finally { node.disabled = false; }
  });
  return node;
}

function select(options, value) {
  const s = el("select");
  options.forEach(([val, label]) => {
    const o = el("option", { value: val, text: label });
    if (val === value) o.selected = true;
    s.append(o);
  });
  return s;
}

/* Cada celda puede ser HTML (string) o un nodo/array de nodos del DOM.
   Así los botones conservan sus eventos (antes se perdían al usar outerHTML). */
function renderTable(containerId, headers, rows) {
  const container = $(`#${containerId}`);
  container.innerHTML = "";
  if (!rows.length) {
    container.append(el("p", { class: "empty", text: "No hay datos para mostrar." }));
    return;
  }
  const table = el("table");
  table.append(el("thead", {}, el("tr", {}, headers.map((h) => el("th", { text: h })))));
  const tbody = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    row.forEach((cell) => {
      const td = el("td");
      if (cell instanceof Node || Array.isArray(cell)) {
        // El flex va en un div interno: un <td> con display:flex rompe la tabla
        const box = el("div", { class: "actions" });
        [].concat(cell).forEach((c) => box.append(c));
        td.append(box);
      } else {
        td.innerHTML = cell == null ? "-" : String(cell);
      }
      tr.append(td);
    });
    tbody.append(tr);
  });
  table.append(tbody);
  container.append(table);
}

function renderPagination(containerId, page, hasMore, onPage) {
  const container = $(`#${containerId}`);
  if (!container) return;
  container.innerHTML = "";
  container.append(
    el("button", { onclick: () => onPage(page - 1), text: "← Anterior", ...(page <= 0 ? { disabled: "" } : {}) }),
    el("span", { text: `Página ${page + 1}` }),
    el("button", { onclick: () => onPage(page + 1), text: "Siguiente →", ...(!hasMore ? { disabled: "" } : {}) }),
  );
}

/* Miniatura con respaldo a la imagen completa: data-full + listener global de "error"
   (sin onerror en línea, que la CSP bloquea) */
function thumb(photos) {
  const url = safeUrl((photos || [])[0]);
  if (!url) return "-";
  const small = /^\/uploads\/[^/]+\.(jpe?g|png|webp)$/i.test(url) ? url.replace(/\.(jpe?g|png|webp)$/i, "_thumb.jpg") : url;
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"><img class="thumb" src="${escapeHtml(small)}" data-full="${escapeHtml(url)}" alt="" loading="lazy" decoding="async"></a>`;
}

document.addEventListener("error", (e) => {
  const img = e.target;
  if (img instanceof HTMLImageElement && img.dataset.full && img.getAttribute("src") !== img.dataset.full) img.src = img.dataset.full;
}, true);

const STATUS_ES = {
  paid: "pagado", approved: "aprobado", completed: "completado", active: "activo", pending: "pendiente",
  pending_payment: "pago pendiente", pending_application: "pendiente", cancelled: "cancelado", rejected: "rechazado",
  shipped: "enviado", delivered: "entregado", refunded: "reembolsado", refund_pending: "reembolso pendiente",
  amount_mismatch: "monto distinto", expired: "expirado", resolved: "resuelto", closed: "cerrado", open: "abierto",
  dismissed: "descartado", suspended: "suspendido", charged_back: "contracargo",
};
const statusBadge = (status) => {
  const cls = { paid: "ok", approved: "ok", completed: "ok", delivered: "ok", resolved: "ok", shipped: "ok", active: "warn",
    pending: "warn", pending_payment: "warn", pending_application: "warn", open: "warn", amount_mismatch: "bad",
    refund_pending: "bad", cancelled: "bad", rejected: "bad", refunded: "bad", suspended: "bad", expired: "" }[status] || "";
  return `<span class="badge ${cls}" title="${escapeHtml(status)}">${escapeHtml(STATUS_ES[status] || status)}</span>`;
};
const hiddenBadge = (item) => (item.is_hidden ? ' <span class="badge bad">oculto</span>' : "");

/* Ocultar o volver a mostrar contenido (moderación) */
function hideButton(type, item, reload) {
  return button(item.is_hidden ? "Mostrar" : "Ocultar", () => run(async () => {
    if (!item.is_hidden && !confirm("¿Ocultar este contenido del público?")) return;
    await api(`/admin/content/${type}/${item.id}`, jsonOpts("PATCH", { hidden: !item.is_hidden }));
    reload();
  }), item.is_hidden ? "btn-secondary" : "btn-danger");
}

/* ------------------------------------------------------------------ sesión */
function showLogin() {
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}

function showApp(name) {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#admin-name").textContent = name;
  loadDashboard();
}

function logout(message = "") {
  currentToken = null;
  localStorage.removeItem(TOKEN_KEY);
  showLogin();
  $("#login-error").textContent = typeof message === "string" ? message : "";
}

async function init() {
  // Google OAuth de un admin: el segundo paso llega en el fragmento (#mfa=<token>&enroll=0|1)
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("mfa")) {
    history.replaceState(null, "", location.pathname);
    showLogin();
    startMfaStep(hash.get("mfa"), hash.get("enroll") === "1");
    return;
  }
  if (!currentToken) { showLogin(); return; }
  try {
    const me = await api("/users/me");
    if (!["admin", "superadmin"].includes(me.role)) { logout(); return; }
    showApp(me.full_name);
  } catch {
    logout();
  }
}

/* Sesión lista (contraseña, o contraseña + verificación en dos pasos) */
async function finishLogin(token) {
  currentToken = token;
  localStorage.setItem(TOKEN_KEY, currentToken);
  const me = await api("/users/me");
  if (!["admin", "superadmin"].includes(me.role)) {
    logout();
    $("#login-error").textContent = "Esta cuenta no tiene permisos de administrador.";
    return;
  }
  resetMfaStep();
  showApp(me.full_name);
}

/* Verificación en dos pasos: código de la app (o de recuperación); el alta la dibuja admin-seguridad.js */
let mfaToken = null;
function resetMfaStep() {
  mfaToken = null;
  $("#mfa-form").classList.add("hidden");
  $("#mfa-enroll").classList.add("hidden");
  $("#mfa-enroll").innerHTML = "";
  $("#login-form").classList.remove("hidden");
}
function startMfaStep(token, enroll) {
  mfaToken = token;
  $("#login-form").classList.add("hidden");
  $("#mfa-error").textContent = "";
  if (enroll) {
    if (!window.AdminSeguridad) { $("#login-error").textContent = "No se pudo cargar la configuración de seguridad."; resetMfaStep(); return; }
    $("#mfa-enroll").classList.remove("hidden");
    window.AdminSeguridad.startEnrollment($("#mfa-enroll"), token, (session) => finishLogin(session), resetMfaStep);
    return;
  }
  $("#mfa-form").classList.remove("hidden");
  $("#mfa-code").value = "";
  $("#mfa-code").focus();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  const params = new URLSearchParams();
  params.append("username", $("#email").value);
  params.append("password", $("#password").value);
  const submit = e.submitter || $("#login-form button[type=submit]");
  if (submit) submit.disabled = true;  // cada doble clic gastaba dos intentos del límite de 10 por minuto
  try {
    let res;
    try {
      res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params,
      });
    } catch { throw new Error("Sin conexión con el servidor. Revisa tu internet e inténtalo de nuevo."); }
    // Nginx responde 429/502 con una página HTML: no es JSON
    const body = await res.json().catch(() => ({}));
    if (res.status === 429) throw new Error("Demasiados intentos. Espera un minuto e inténtalo de nuevo.");
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `No se pudo iniciar sesión (error ${res.status}).`);
    $("#password").value = "";
    if (body.mfa_required) { startMfaStep(body.mfa_token, !!body.mfa_enrollment_required); return; }
    await finishLogin(body.access_token);
  } catch (err) {
    $("#login-error").textContent = err.message;
  } finally {
    if (submit) submit.disabled = false;
  }
});

$("#mfa-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#mfa-error").textContent = "";
  try {
    const res = await fetch(`${API_BASE}/auth/mfa/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mfa_token: mfaToken, code: $("#mfa-code").value.trim() }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401 && /venció/.test(body.detail || "")) resetMfaStep();
      throw new Error(body.detail || "No se pudo verificar el código.");
    }
    await finishLogin(body.access_token);
  } catch (err) {
    ($("#mfa-form").classList.contains("hidden") ? $("#login-error") : $("#mfa-error")).textContent = err.message;
  }
});

$("#mfa-cancel").addEventListener("click", () => resetMfaStep());

$("#logout-btn").addEventListener("click", () => logout());

/* ------------------------------------------------------------------ navegación */
const loaders = {
  dashboard: () => loadDashboard(),
  users: () => loadUsers(),
  dogs: () => loadDogs(),
  matches: () => loadMatches(),
  refuges: () => loadRefuges(),
  "foster-homes": () => loadFosterHomes(),
  products: () => loadProducts(),
  orders: () => window.AdminTienda && AdminTienda.loadOrders(),  // admin-tienda.js
  donations: () => loadDonations(),
  "lost-reports": () => loadLostReports(),
  reports: () => loadReports(),
  audit: () => loadAudit(),
  whatsapp: () => loadWhatsappInteractions(),
  facebook: () => loadFacebook(),
};

function showSection(id) {
  $$(".section").forEach((s) => s.classList.remove("active"));
  $(`#${id}`).classList.add("active");
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.section === id));
  run(loaders[id]);
}

$$(".nav-btn").forEach((btn) => btn.addEventListener("click", () => showSection(btn.dataset.section)));

/* ------------------------------------------------------------------ dashboard */
async function loadDashboard() {
  const data = await api("/admin/dashboard");
  const t = data.totals;
  const cards = [
    ["Usuarios", t.users], ["Perros", t.dogs], ["Matches", t.matches], ["Solicitudes pendientes", t.pending_matches],
    ["Refugios pend.", t.pending_refuges], ["Casas de paso pend.", t.pending_foster_homes], ["Productos", t.products],
    ["Reportes", t.lost_reports], ["Pedidos pagados", t.orders_paid ?? 0], ["Donaciones", fmtMoney(t.donations_total)],
  ];
  $("#stats-grid").innerHTML = cards
    .map(([label, value]) => `<div class="stat-card"><div class="value">${value}</div><div class="label">${label}</div></div>`)
    .join("");
  $("#recent-activity").innerHTML = `
    <div class="mini-stat"><span>Usuarios (7 días)</span><strong>${data.recent.users_week}</strong></div>
    <div class="mini-stat"><span>Usuarios (30 días)</span><strong>${data.recent.users_month}</strong></div>
    <div class="mini-stat"><span>Perros (7 días)</span><strong>${data.recent.dogs_week}</strong></div>
    <div class="mini-stat"><span>Matches (7 días)</span><strong>${data.recent.matches_week}</strong></div>`;
  $("#users-by-city").innerHTML = data.by_city.length
    ? data.by_city.map((c) => `<div class="list-stat"><span>${escapeHtml(c.city)}</span><strong>${c.count}</strong></div>`).join("")
    : "<p class='empty'>Sin datos</p>";
  const s = data.dogs_by_status;
  $("#dogs-by-status").innerHTML = [
    ["Disponibles", s.available], ["En proceso", s.in_process ?? 0], ["Adoptados", s.adopted],
    ["En casa de paso", s.in_foster], ["No disponibles", s.unavailable],
  ].map(([l, v]) => `<div class="list-stat"><span>${l}</span><strong>${v}</strong></div>`).join("");
}

/* ------------------------------------------------------------------ usuarios */
async function loadUsers() {
  const users = await api(`/admin/users?skip=${adminState.users.page * PAGE_SIZE}&limit=${PAGE_SIZE}`);
  const rows = users.map((u) => {
    const roleSelect = select(["user", "refuge", "foster", "admin", "superadmin"].map((r) => [r, r]), u.role);
    const save = button("Guardar", () => run(async () => {
      await api(`/admin/users/${u.id}/role`, jsonOpts("PATCH", { role: roleSelect.value }));
      alert("Rol actualizado");
      loadUsers();
    }));
    const toggle = button(u.is_active ? "Suspender" : "Reactivar", () => run(async () => {
      if (u.is_active && !confirm(`¿Suspender la cuenta de ${u.full_name}? Se cerrarán todas sus sesiones.`)) return;
      await api(`/admin/users/${u.id}/active`, jsonOpts("PATCH", { is_active: !u.is_active }));
      loadUsers();
    }), u.is_active ? "btn-danger" : "btn-success");
    return [
      u.id, escapeHtml(u.full_name),
      `${escapeHtml(u.email)} ${u.email_verified ? '<span class="badge ok">verificado</span>' : ""}`,
      `${escapeHtml(u.phone || "-")} ${u.phone_verified ? '<span class="badge ok">verificado</span>' : ""}`,
      escapeHtml(u.city || "-"), [roleSelect, save], [el("span", { text: u.is_active ? "Sí " : "No " }), toggle], fmtDate(u.created_at),
    ];
  });
  renderTable("users-table", ["ID", "Nombre", "Correo", "Teléfono", "Ciudad", "Rol", "Activo", "Creado"], rows);
  renderPagination("users-pagination", adminState.users.page, users.length >= PAGE_SIZE, (p) => { adminState.users.page = p; run(loadUsers); });
}

/* ------------------------------------------------------------------ perros */
const DOG_STATUSES = [["available", "Disponible"], ["in_process", "En proceso"], ["adopted", "Adoptado"],
  ["in_foster", "En casa de paso"], ["unavailable", "No disponible"]];

async function loadDogs() {
  const params = new URLSearchParams({ skip: adminState.dogs.page * PAGE_SIZE, limit: PAGE_SIZE + 1 });
  if (adminState.dogs.status) params.set("status", adminState.dogs.status);
  if (adminState.dogs.city) params.set("city", adminState.dogs.city);
  const dogs = await api(`/admin/dogs?${params}`);
  const hasMore = dogs.length > PAGE_SIZE;
  const rows = dogs.slice(0, PAGE_SIZE).map((d) => {
    const st = select(DOG_STATUSES, d.status);
    const save = button("Guardar", () => run(async () => {
      await api(`/admin/dogs/${d.id}/status`, jsonOpts("PATCH", { status: st.value }));
      loadDogs();
    }));
    return [d.id, thumb(d.photos), escapeHtml(d.name) + hiddenBadge(d), escapeHtml(d.breed || "-"), escapeHtml(d.city || "-"),
      escapeHtml(d.owner?.full_name || d.owner_id), [st, save], hideButton("dog", d, () => run(loadDogs)), fmtDate(d.created_at)];
  });
  renderTable("dogs-table", ["ID", "Foto", "Nombre", "Raza", "Ciudad", "Publicó", "Estado", "Visibilidad", "Creado"], rows);
  renderPagination("dogs-pagination", adminState.dogs.page, hasMore, (p) => { adminState.dogs.page = p; run(loadDogs); });
}

$("#dogs-filter-btn").addEventListener("click", () => {
  adminState.dogs.status = $("#dogs-filter-status").value;
  adminState.dogs.city = $("#dogs-filter-city").value.trim();
  adminState.dogs.page = 0;
  run(loadDogs);
});

/* ------------------------------------------------------------------ matches */
function openModal(html) {
  $("#modal-body").innerHTML = html;
  $("#modal").classList.remove("hidden");
}

async function loadMatches() {
  const params = new URLSearchParams({ skip: adminState.matches.page * PAGE_SIZE, limit: PAGE_SIZE + 1 });
  if (adminState.matches.status) params.set("status", adminState.matches.status);
  const matches = await api(`/admin/matches?${params}`);
  const hasMore = matches.length > PAGE_SIZE;
  const rows = matches.slice(0, PAGE_SIZE).map((m) => {
    const appBtn = button(m.application ? "Ver cuestionario" : "Sin cuestionario", () => {
      const answers = Object.entries(m.application.answers || {})
        .map(([k, v]) => `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`)
        .join("");
      const compat = m.application.compatibility != null ? `<p>Compatibilidad estimada: <strong>${m.application.compatibility}%</strong></p>` : "";
      openModal(`<h3>${escapeHtml(m.user.full_name)} → ${escapeHtml(m.dog.name)}</h3>${compat}<table>${answers}</table>`);
    });
    if (!m.application) appBtn.disabled = true;
    return [m.id, escapeHtml(m.user.full_name), escapeHtml(m.user.email), escapeHtml(m.dog.name), statusBadge(m.status),
      appBtn, fmtDate(m.created_at)];
  });
  renderTable("matches-table", ["ID", "Adoptante", "Correo", "Perro", "Estado", "Cuestionario", "Creado"], rows);
  renderPagination("matches-pagination", adminState.matches.page, hasMore, (p) => { adminState.matches.page = p; run(loadMatches); });
}

$("#matches-filter-btn").addEventListener("click", () => {
  adminState.matches.status = $("#matches-filter-status").value;
  adminState.matches.page = 0;
  run(loadMatches);
});

/* ------------------------------------------------------------------ refugios / casas de paso */
async function loadRefuges() {
  const refuges = await api("/admin/refuges/pending");
  const rows = refuges.map((r) => [
    r.id, escapeHtml(r.name), escapeHtml(r.city || "-"), r.user_id, fmtDate(r.created_at),
    [
      button("Aprobar", () => run(async () => { await api(`/admin/refuges/${r.id}/approve`, { method: "POST" }); loadRefuges(); }), "btn-success"),
      button("Rechazar", () => run(async () => {
        const reason = prompt("Motivo del rechazo (opcional):") || null;
        await api(`/admin/refuges/${r.id}/reject`, jsonOpts("POST", { reason }));
        loadRefuges();
      }), "btn-danger"),
      button(`Documentos (${r.documents ? r.documents.length : "?"})`, () => run(async () => {
        const docs = r.documents || (await api(`/admin/refuges/${r.id}/documents`)).documents || [];
        openModal(`<h3>Documentos de ${escapeHtml(r.name)}</h3><p class="hint">Solo los administradores pueden verlos. No los compartas.</p><ul id="doc-list"></ul>`);
        const ul = $("#doc-list");
        if (!docs.length) ul.append(el("li", { text: "Sin documentos" }));
        docs.forEach((d, i) => ul.append(el("li", {}, button(`Abrir documento ${i + 1} (${docLabel(d)})`, () => run(() => openDocument(d))))));
      })),
    ],
  ]);
  renderTable("refuges-table", ["ID", "Nombre", "Ciudad", "Usuario", "Creado", "Acciones"], rows);
}

/* Id de documento: "<uuid>.<ext>" o ruta antigua "/uploads/<archivo>" (se pide por su nombre) */
function docId(d) { return String(d || "").replace(/^\/uploads\//, ""); }
function docLabel(d) { const ext = (docId(d).split(".").pop() || "").toUpperCase(); return ext || "archivo"; }
async function openDocument(d) {
  const win = window.open("", "_blank");  // se abre antes del await para que el navegador no la bloquee
  try {
    const res = await fetch(`${API_BASE}/admin/documents/${encodeURIComponent(docId(d))}`, { headers: { Authorization: `Bearer ${currentToken}` } });
    if (res.status === 401) { logout("Tu sesión expiró. Inicia sesión de nuevo."); throw Object.assign(new Error(""), { silent: true }); }
    if (!res.ok) throw new Error(res.status === 404 ? "No encontramos ese documento." : `No se pudo abrir el documento (error ${res.status}).`);
    const url = URL.createObjectURL(await res.blob());
    if (win) win.location.href = url; else window.open(url, "_blank");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (err) {
    if (win) win.close();
    throw err;
  }
}

async function loadFosterHomes() {
  const homes = await api("/admin/foster-homes/pending");
  const rows = homes.map((h) => [
    h.id, h.user_id, escapeHtml(h.city || "-"), h.capacity, fmtDate(h.created_at),
    [
      button("Aprobar", () => run(async () => { await api(`/admin/foster-homes/${h.id}/approve`, { method: "POST" }); loadFosterHomes(); }), "btn-success"),
      button("Rechazar", () => run(async () => {
        const reason = prompt("Motivo del rechazo (opcional):") || null;
        await api(`/admin/foster-homes/${h.id}/reject`, jsonOpts("POST", { reason }));
        loadFosterHomes();
      }), "btn-danger"),
    ],
  ]);
  renderTable("foster-homes-table", ["ID", "Usuario", "Ciudad", "Capacidad", "Creado", "Acciones"], rows);
}

/* ------------------------------------------------------------------ tienda */
async function loadProducts() {
  const products = await api("/admin/products");
  const rows = products.map((p) => [p.id, thumb(p.photos), escapeHtml(p.name) + hiddenBadge(p), p.refuge_id, fmtMoney(p.price), p.stock,
    p.is_active ? "Sí" : "No", hideButton("product", p, () => run(loadProducts)), fmtDate(p.created_at)]);
  renderTable("products-table", ["ID", "Foto", "Nombre", "Refugio", "Precio", "Stock", "Activo", "Visibilidad", "Creado"], rows);
}

/* Pedidos (filtros, reembolsos), CFDI de la plataforma y estados de cuenta: admin-tienda.js */

/* Pagos en revisión (monto distinto o reembolso pendiente): aceptar el pago o reembolsarlo */
const REVIEW_STATUSES = ["amount_mismatch", "refund_pending"];
function resolveButtons(kind, item, reload) {
  if (!REVIEW_STATUSES.includes(item.status)) return "-";
  const act = (action, question) => button(action === "mark_paid" ? "Aceptar pago" : "Reembolsar", () => run(async () => {
    if (!confirm(question)) return;
    const notes = prompt("Nota para la bitácora (opcional):") || null;
    await api(`/admin/${kind}/${item.id}/resolve`, jsonOpts("POST", { action, notes }));
    reload();
  }), action === "mark_paid" ? "btn-success" : "btn-danger");
  return [act("mark_paid", "¿Aceptar este pago como válido?"), act("refund", "¿Reembolsar este pago en Mercado Pago?")];
}

async function loadDonations() {
  const params = new URLSearchParams({ limit: 200 });
  if (adminState.donations.status) params.set("status", adminState.donations.status);
  const donations = await api(`/admin/donations?${params}`);
  const approved = donations.filter((d) => d.status === "approved");
  $("#donations-summary").innerHTML = `
    <div class="mini-stat"><span>Aprobadas (en la lista)</span><strong>${approved.length}</strong></div>
    <div class="mini-stat"><span>Total aprobado</span><strong>${fmtMoney(approved.reduce((s, d) => s + Number(d.amount), 0))}</strong></div>`;
  const rows = donations.map((d) => [
    d.id, escapeHtml(d.user?.full_name || d.user_id), escapeHtml(d.refuge_name || d.refuge_id), fmtMoney(d.amount),
    statusBadge(d.status), escapeHtml(d.provider || "-"), escapeHtml(d.provider_payment_id || "-"), fmtDate(d.created_at),
    resolveButtons("donations", d, () => run(loadDonations)),
  ]);
  renderTable("donations-table", ["ID", "Donante", "Refugio", "Monto", "Estado", "Proveedor", "ID de pago", "Fecha", "Revisión"], rows);
}

$("#donations-filter-btn").addEventListener("click", () => { adminState.donations.status = $("#donations-filter-status").value; run(loadDonations); });

/* ------------------------------------------------------------------ perdidos / encontrados */
async function loadLostReports() {
  const params = new URLSearchParams({ limit: 200 });
  if (adminState.lost.status) params.set("status", adminState.lost.status);
  if (adminState.lost.source) params.set("source", adminState.lost.source);
  const reports = await api(`/admin/lost-reports?${params}`);
  const rows = reports.map((r) => {
    const st = select([["active", "Activo"], ["resolved", "Resuelto"], ["expired", "Expirado"], ["closed", "Cerrado"]], r.status);
    const save = button("Guardar", () => run(async () => {
      await api(`/admin/lost-reports/${r.id}/status`, jsonOpts("PATCH", { status: st.value }));
      loadLostReports();
    }));
    const contact = r.contact_phone
      ? `<a href="https://wa.me/${escapeHtml(r.contact_phone.replace(/\D/g, ""))}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.contact_phone)}</a>`
      : escapeHtml(r.reporter?.full_name || "-");
    const origin = safeUrl(r.external_url) ? ` ${link(r.external_url, "↗")}` : "";
    return [
      r.id, thumb(r.photos), escapeHtml(r.dog_name) + hiddenBadge(r), r.report_type === "lost" ? "Perdido" : "Encontrado",
      `<span class="badge ${escapeHtml(r.source)}">${escapeHtml(r.source)}</span>${origin}`, contact,
      escapeHtml(r.city || "-"), [st, save], hideButton("lost_report", r, () => run(loadLostReports)), fmtDate(r.created_at),
    ];
  });
  renderTable("lost-reports-table", ["ID", "Foto", "Nombre", "Tipo", "Fuente", "Contacto", "Ciudad", "Estado", "Visibilidad", "Creado"], rows);
}

$("#lost-filter-btn").addEventListener("click", () => {
  adminState.lost.status = $("#lost-filter-status").value;
  adminState.lost.source = $("#lost-filter-source").value;
  run(loadLostReports);
});

/* ------------------------------------------------------------------ reportes de contenido (moderación) */
const REASON_ES = { spam: "Spam o venta", fraude: "Fraude o estafa", maltrato: "Maltrato animal",
  contenido_inapropiado: "Contenido inapropiado", datos_falsos: "Datos falsos", otro: "Otro" };
const ACTION_ES = { hide_content: "Contenido oculto", suspend_user: "Cuenta suspendida" };

function reportTarget(r) {
  const t = r.target || {};
  const flags = (t.is_hidden ? ' <span class="badge bad">oculto</span>' : "")
    + (t.is_active === false ? ' <span class="badge bad">inactivo</span>' : "")
    + (t.exists === false ? ' <span class="badge">eliminado</span>' : "");
  const url = /^\/app\/\?(dog|report)=\d+$/.test(t.url || "") ? ` <a href="${escapeHtml(t.url)}" target="_blank" rel="noopener">ver ↗</a>` : "";
  const owner = t.owner_name ? `<br><small>de ${escapeHtml(t.owner_name)}${t.owner_id ? ` (#${escapeHtml(t.owner_id)})` : ""}</small>` : "";
  const pic = t.photo ? `${thumb([t.photo])} ` : "";
  return `${pic}<strong>${escapeHtml(t.label || r.target_type)}</strong>: ${escapeHtml(t.title || `#${r.target_id}`)}${flags}${url}${owner}`;
}

function reportActions(r) {
  const options = [["", "Sin acción"]];
  // A un usuario no se le "oculta": se suspende su cuenta
  if (r.target_type !== "user") options.push(["hide_content", r.target_type === "refuge" ? "Suspender refugio" : "Ocultar contenido"]);
  options.push(["suspend_user", "Suspender usuario"]);
  const action = select(options, "");
  const notes = el("input", { type: "text", placeholder: "Notas (opcional)", maxlength: "2000" });
  const send = (status) => run(async () => {
    const chosen = status === "resolved" ? action.value || null : null;
    if (chosen === "suspend_user" && !confirm("¿Suspender la cuenta? Se cerrarán todas sus sesiones y se ocultará su contenido.")) return;
    await api(`/admin/reports/${r.id}`, jsonOpts("PATCH", { status, action: chosen, notes: notes.value.trim() || null }));
    loadReports();
  });
  return [action, notes, button("Resolver", () => send("resolved"), "btn-success"), button("Descartar", () => send("dismissed"), "btn-secondary")];
}

async function loadReports() {
  const st = adminState.reports;
  const params = new URLSearchParams({ skip: st.page * PAGE_SIZE, limit: PAGE_SIZE + 1 });
  if (st.status) params.set("status", st.status);
  const reports = await api(`/admin/reports?${params}`);
  const hasMore = reports.length > PAGE_SIZE;
  const rows = reports.slice(0, PAGE_SIZE).map((r) => {
    const done = `${escapeHtml(ACTION_ES[r.action] || "Sin acción")}${r.admin_notes ? `<br><small>${escapeHtml(r.admin_notes)}</small>` : ""}`
      + `${r.resolved_by ? `<br><small>por ${escapeHtml(r.resolved_by.full_name)} · ${fmtDate(r.resolved_at)}</small>` : ""}`;
    const many = r.open_reports_for_target > 1 ? ` <span class="badge bad">${r.open_reports_for_target} abiertos</span>` : "";
    return [
      r.id, reportTarget(r), escapeHtml(REASON_ES[r.reason] || r.reason) + many, escapeHtml(r.details || "-"),
      r.reporter ? `${escapeHtml(r.reporter.full_name)}<br><small>${escapeHtml(r.reporter.email || "")}</small>` : "-",
      statusBadge(r.status), r.status === "open" ? reportActions(r) : done, fmtDate(r.created_at),
    ];
  });
  renderTable("reports-table", ["ID", "Contenido", "Motivo", "Detalles", "Reportó", "Estado", "Acción", "Fecha"], rows);
  renderPagination("reports-pagination", st.page, hasMore, (p) => { st.page = p; run(loadReports); });
}

$("#reports-filter-btn").addEventListener("click", () => {
  adminState.reports.status = $("#reports-filter-status").value;
  adminState.reports.page = 0;
  run(loadReports);
});

/* ------------------------------------------------------------------ bitácora de administración */
async function loadAudit() {
  const st = adminState.audit;
  const params = new URLSearchParams({ skip: st.page * PAGE_SIZE, limit: PAGE_SIZE + 1 });
  if (st.action) params.set("action", st.action);
  let entries;
  try { entries = await api(`/admin/audit-log?${params}`); }
  catch (err) {
    if (err.status !== 403) throw err;
    $("#audit-table").innerHTML = '<p class="empty">Solo un superadmin puede ver la bitácora.</p>';
    return;
  }
  const hasMore = entries.length > PAGE_SIZE;
  const rows = entries.slice(0, PAGE_SIZE).map((a) => [
    fmtDate(a.created_at), escapeHtml(a.actor_name || a.actor_email || a.actor_id || "-"), escapeHtml(a.action),
    `${escapeHtml(a.target_type)}${a.target_id != null ? ` #${escapeHtml(a.target_id)}` : ""}`,
    a.details ? `<pre>${escapeHtml(JSON.stringify(a.details, null, 1))}</pre>` : "-", escapeHtml(a.ip || "-"),
  ]);
  renderTable("audit-table", ["Fecha", "Quién", "Acción", "Objetivo", "Detalles", "IP"], rows);
  renderPagination("audit-pagination", st.page, hasMore, (p) => { st.page = p; run(loadAudit); });
}

$("#audit-filter-btn").addEventListener("click", () => {
  adminState.audit.action = $("#audit-filter-action").value.trim();
  adminState.audit.page = 0;
  run(loadAudit);
});

/* ------------------------------------------------------------------ WhatsApp */
async function loadWhatsappInteractions() {
  run(async () => {
    const cfg = await api("/auth/config");
    $("#whatsapp-status").textContent = cfg.whatsapp_enabled
      ? "WhatsApp Cloud API conectada: los mensajes reales se responden automáticamente. El simulador no envía nada a WhatsApp."
      : "WhatsApp Cloud API sin configurar (WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID). Usa el simulador para probar el flujo.";
  });
  const interactions = await api("/admin/bot-interactions");
  const rows = interactions.map((i) => [
    i.id, escapeHtml(i.phone), escapeHtml(i.stage), `<pre>${escapeHtml(JSON.stringify(i.data, null, 2))}</pre>`,
    `<pre>${escapeHtml(i.last_message || "-")}</pre>`, fmtDate(i.updated_at),
  ]);
  renderTable("whatsapp-interactions", ["ID", "Teléfono", "Etapa", "Datos", "Última respuesta", "Actualizado"], rows);
}

async function sendToBot(payload) {
  const response = await api("/whatsapp/webhook", jsonOpts("POST", payload));
  $("#whatsapp-response").textContent = `Etapa: ${response.stage}\n\n${response.response}`;
  const quick = $("#whatsapp-quick");
  quick.innerHTML = "";
  (response.buttons || []).forEach((b) => {
    quick.append(button(b.title, () => run(() => sendToBot({ phone: payload.phone, message: b.id }))));
  });
  loadWhatsappInteractions();
}

$("#whatsapp-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const lat = $("#wa-lat").value;
  const lon = $("#wa-lon").value;
  const payload = {
    phone: $("#wa-phone").value.trim(),
    message: $("#wa-message").value || null,
    media_url: $("#wa-media").value.trim() || null,
  };
  if (lat && lon) { payload.latitude = Number(lat); payload.longitude = Number(lon); }
  run(async () => {
    await sendToBot(payload);
    $("#wa-message").value = "";
    $("#wa-media").value = "";
    $("#wa-lat").value = "";
    $("#wa-lon").value = "";
  });
});

/* ------------------------------------------------------------------ Facebook */
/* La sección de Facebook (grupos públicos por estado, gasto, Páginas e importación manual)
   vive en admin-facebook.js, que define loadFacebook(). */

/* ------------------------------------------------------------------ modal */
const modal = el("div", { id: "modal", class: "modal hidden" });
modal.innerHTML = `<div class="modal-backdrop"></div><div class="modal-card"><button class="modal-close" aria-label="Cerrar">&times;</button><div id="modal-body"></div></div>`;
document.body.appendChild(modal);
modal.querySelector(".modal-close").addEventListener("click", () => modal.classList.add("hidden"));
modal.querySelector(".modal-backdrop").addEventListener("click", () => modal.classList.add("hidden"));

init();
