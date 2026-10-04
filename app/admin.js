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
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (currentToken) headers.Authorization = `Bearer ${currentToken}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  let body = null;
  const text = await res.text();
  if (text) {
    try { body = JSON.parse(text); } catch { body = { detail: text }; }
  }
  if (res.status === 401) {
    logout();
    throw new Error("Tu sesión expiró. Inicia sesión de nuevo.");
  }
  if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Error ${res.status}`);
  return body;
}

const jsonOpts = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

// Ejecuta una acción y muestra el error en un alert en lugar de fallar en silencio
async function run(fn) {
  try { return await fn(); } catch (err) { alert(err.message); }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

const fmtDate = (d) => (d ? new Date(d).toLocaleString("es-MX") : "-");
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

function button(label, onclick, className = "") {
  return el("button", { class: className, onclick, text: label });
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
        td.className = "actions";
        [].concat(cell).forEach((c) => td.append(c));
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

function thumb(photos) {
  const url = (photos || [])[0];
  if (!url) return "-";
  const small = url.startsWith("/uploads/") ? url.replace(/\.(jpg|jpeg|png|webp)$/i, "_thumb.jpg") : url;
  return `<a href="${escapeHtml(url)}" target="_blank"><img class="thumb" src="${escapeHtml(small)}" alt="" onerror="this.src='${escapeHtml(url)}'"></a>`;
}

const statusBadge = (status) => {
  const cls = { paid: "ok", approved: "ok", completed: "ok", active: "warn", pending: "warn", pending_payment: "warn",
    pending_application: "warn", cancelled: "bad", rejected: "bad" }[status] || "";
  return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
};

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

function logout() {
  currentToken = null;
  localStorage.removeItem(TOKEN_KEY);
  showLogin();
}

async function init() {
  if (!currentToken) { showLogin(); return; }
  try {
    const me = await api("/users/me");
    if (!["admin", "superadmin"].includes(me.role)) { logout(); return; }
    showApp(me.full_name);
  } catch {
    logout();
  }
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  const params = new URLSearchParams();
  params.append("username", $("#email").value);
  params.append("password", $("#password").value);
  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params,
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "No se pudo iniciar sesión");
    currentToken = body.access_token;
    localStorage.setItem(TOKEN_KEY, currentToken);
    const me = await api("/users/me");
    if (!["admin", "superadmin"].includes(me.role)) {
      logout();
      $("#login-error").textContent = "Esta cuenta no tiene permisos de administrador.";
      return;
    }
    showApp(me.full_name);
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#logout-btn").addEventListener("click", logout);

/* ------------------------------------------------------------------ navegación */
const loaders = {
  dashboard: () => loadDashboard(),
  users: () => loadUsers(),
  dogs: () => loadDogs(),
  matches: () => loadMatches(),
  refuges: () => loadRefuges(),
  "foster-homes": () => loadFosterHomes(),
  products: () => loadProducts(),
  orders: () => loadOrders(),
  donations: () => loadDonations(),
  "lost-reports": () => loadLostReports(),
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
    return [
      u.id, escapeHtml(u.full_name), escapeHtml(u.email),
      `${escapeHtml(u.phone || "-")} ${u.phone_verified ? '<span class="badge ok">verificado</span>' : ""}`,
      escapeHtml(u.city || "-"), [roleSelect, save], u.is_active ? "Sí" : "No", fmtDate(u.created_at),
    ];
  });
  renderTable("users-table", ["ID", "Nombre", "Correo", "Teléfono", "Ciudad", "Rol", "Activo", "Creado"], rows);
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
    return [d.id, thumb(d.photos), escapeHtml(d.name), escapeHtml(d.breed || "-"), escapeHtml(d.city || "-"),
      escapeHtml(d.owner?.full_name || d.owner_id), [st, save], fmtDate(d.created_at)];
  });
  renderTable("dogs-table", ["ID", "Foto", "Nombre", "Raza", "Ciudad", "Publicó", "Estado", "Creado"], rows);
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
      button("Documentos", () => run(async () => {
        const data = await api(`/admin/refuges/${r.id}/documents`);
        const list = data.documents.length
          ? data.documents.map((u) => `<li><a href="${escapeHtml(u)}" target="_blank">${escapeHtml(u)}</a></li>`).join("")
          : "<li>Sin documentos</li>";
        openModal(`<h3>Documentos de ${escapeHtml(r.name)}</h3><ul>${list}</ul>`);
      })),
    ],
  ]);
  renderTable("refuges-table", ["ID", "Nombre", "Ciudad", "Usuario", "Creado", "Acciones"], rows);
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
  const rows = products.map((p) => [p.id, thumb(p.photos), escapeHtml(p.name), p.refuge_id, fmtMoney(p.price), p.stock,
    p.is_active ? "Sí" : "No", fmtDate(p.created_at)]);
  renderTable("products-table", ["ID", "Foto", "Nombre", "Refugio", "Precio", "Stock", "Activo", "Creado"], rows);
}

async function loadOrders() {
  const params = new URLSearchParams({ limit: 200 });
  if (adminState.orders.status) params.set("status", adminState.orders.status);
  const orders = await api(`/admin/orders?${params}`);
  const rows = orders.map((o) => [
    o.id, escapeHtml(o.user?.full_name || o.user_id),
    o.items.map((i) => `${i.quantity} × ${escapeHtml(i.product?.name || i.product_id)}`).join("<br>"),
    fmtMoney(o.total), statusBadge(o.status), escapeHtml(o.provider || "-"), escapeHtml(o.provider_payment_id || "-"),
    escapeHtml(o.shipping_address), fmtDate(o.paid_at), fmtDate(o.created_at),
  ]);
  renderTable("orders-table", ["ID", "Cliente", "Productos", "Total", "Estado", "Proveedor", "ID de pago", "Envío", "Pagado", "Creado"], rows);
}

$("#orders-filter-btn").addEventListener("click", () => { adminState.orders.status = $("#orders-filter-status").value; run(loadOrders); });

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
  ]);
  renderTable("donations-table", ["ID", "Donante", "Refugio", "Monto", "Estado", "Proveedor", "ID de pago", "Fecha"], rows);
}

$("#donations-filter-btn").addEventListener("click", () => { adminState.donations.status = $("#donations-filter-status").value; run(loadDonations); });

/* ------------------------------------------------------------------ perdidos / encontrados */
async function loadLostReports() {
  const params = new URLSearchParams({ limit: 200 });
  if (adminState.lost.status) params.set("status", adminState.lost.status);
  if (adminState.lost.source) params.set("source", adminState.lost.source);
  const reports = await api(`/admin/lost-reports?${params}`);
  const rows = reports.map((r) => {
    const st = select([["active", "Activo"], ["resolved", "Resuelto"], ["closed", "Cerrado"]], r.status);
    const save = button("Guardar", () => run(async () => {
      await api(`/admin/lost-reports/${r.id}/status`, jsonOpts("PATCH", { status: st.value }));
      loadLostReports();
    }));
    const contact = r.contact_phone
      ? `<a href="https://wa.me/${escapeHtml(r.contact_phone.replace(/\D/g, ""))}" target="_blank">${escapeHtml(r.contact_phone)}</a>`
      : escapeHtml(r.reporter?.full_name || "-");
    const origin = r.external_url ? ` <a href="${escapeHtml(r.external_url)}" target="_blank">↗</a>` : "";
    return [
      r.id, thumb(r.photos), escapeHtml(r.dog_name), r.report_type === "lost" ? "Perdido" : "Encontrado",
      `<span class="badge ${escapeHtml(r.source)}">${escapeHtml(r.source)}</span>${origin}`, contact,
      escapeHtml(r.city || "-"), [st, save], fmtDate(r.created_at),
    ];
  });
  renderTable("lost-reports-table", ["ID", "Foto", "Nombre", "Tipo", "Fuente", "Contacto", "Ciudad", "Estado", "Creado"], rows);
}

$("#lost-filter-btn").addEventListener("click", () => {
  adminState.lost.status = $("#lost-filter-status").value;
  adminState.lost.source = $("#lost-filter-source").value;
  run(loadLostReports);
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
async function loadFacebook() {
  run(async () => {
    const st = await api("/facebook/status");
    $("#facebook-status").innerHTML = st.pages_enabled
      ? `<span class="badge ok">Páginas conectadas</span> Graph API ${escapeHtml(st.graph_api_version)}. Las páginas se leen cada hora.`
      : '<span class="badge warn">Sin token de página</span> Solo está disponible la importación manual.';
  });
  const sources = await api("/facebook/groups");
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
      `<a href="${escapeHtml(g.url)}" target="_blank">${escapeHtml(g.url)}</a>`, escapeHtml(g.city || "-"),
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
    $("#facebook-import-result").innerHTML = `Reporte #${report.id} creado con ${report.photos.length} foto(s). Buscando coincidencias…`;
    e.target.reset();
  });
});

/* ------------------------------------------------------------------ modal */
const modal = el("div", { id: "modal", class: "modal hidden" });
modal.innerHTML = `<div class="modal-backdrop"></div><div class="modal-card"><button class="modal-close" aria-label="Cerrar">&times;</button><div id="modal-body"></div></div>`;
document.body.appendChild(modal);
modal.querySelector(".modal-close").addEventListener("click", () => modal.classList.add("hidden"));
modal.querySelector(".modal-backdrop").addEventListener("click", () => modal.classList.add("hidden"));

init();
