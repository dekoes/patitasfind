/* ============================================================
   GuauWoow Admin — Veterinarias (V2/V4)
   Cola de verificación: lista por estado, cédula privada (se descarga con el token en la
   cabecera Authorization, nunca con un enlace público), verificar, rechazar con nota y
   ocultar por moderación. Todas las acciones quedan en la bitácora (record_admin_action).
   Endpoints: GET /admin/veterinaries?status&q&skip&limit,
   POST /admin/veterinaries/{id}/verify {carrera, evidence_document_id} (captura fechada del cotejo en el RNP,
   subida con POST /upload/document), POST /admin/veterinaries/{id}/reject {note},
   GET /admin/veterinaries/{id}/cedula, GET /admin/veterinaries/{id}/evidence,
   GET /admin/veterinary-requests?status, POST /admin/veterinary-requests/{id}/resolve {action, note}.
   Se carga después de admin.js y usa sus utilidades globales
   (api, jsonOpts, run, escapeHtml, link, fmtDate, el, button, renderTable, renderPagination,
   thumb, hideButton, openDocument, loaders, REASON_ES, STATUS_ES, currentToken, API_BASE, logout, $).
   ============================================================ */
"use strict";

(() => {
  const VET_STATUS = { pending: ["pendiente", "warn"], verified: ["verificada", "ok"], rejected: ["rechazada", "bad"] };
  const st = { status: "pending", q: "", page: 0 };
  const SEARCH_LIMIT = 200;  // máximo que acepta GET /admin/veterinaries
  // Buscador del Registro Nacional de Profesionistas (SEP): ahí se coteja la cédula
  const SEP_URL = "https://www.cedulaprofesional.sep.gob.mx/";

  // Motivos de reporte nuevos (clínicas y reseñas) para la pestaña Reportes
  if (typeof REASON_ES === "object") Object.assign(REASON_ES, {
    honor_reputacion: "Afecta honor o reputación", resena_falsa: "Reseña falsa o pagada", datos_personales: "Datos personales",
    cedula_falsa: "Cédula o veterinario falso", condiciones_sanitarias: "Condiciones sanitarias", publicidad_enganosa: "Publicidad engañosa",
  });
  if (typeof STATUS_ES === "object") Object.assign(STATUS_ES, { verified: "verificada" });

  const missing = (e) => e && e.status === 404 && (e.message === "Not Found" || e.message === "Error 404");
  function vetBadge(s) {
    const [label, cls] = VET_STATUS[s] || [s, ""];
    return `<span class="badge ${cls}" title="${escapeHtml(s)}">${escapeHtml(label)}</span>`;
  }

  /* Captura del cotejo (privada): blob con Authorization */
  async function openEvidence(v) {
    const win = window.open("", "_blank");
    try {
      const res = await fetch(`${API_BASE}/admin/veterinaries/${encodeURIComponent(v.id)}/evidence`, { headers: { Authorization: `Bearer ${currentToken}` } });
      if (res.status === 401) { logout("Tu sesión expiró. Inicia sesión de nuevo."); throw Object.assign(new Error(""), { silent: true }); }
      if (!res.ok) {
        let body = null;
        try { body = await res.json(); } catch { body = null; }
        throw new Error((body && typeof body.detail === "string" && body.detail) || `No se pudo abrir la captura (error ${res.status}).`);
      }
      const url = URL.createObjectURL(await res.blob());
      if (win) win.location.href = url; else window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      if (win) win.close();
      throw err;
    }
  }

  /* Cédula privada: blob con Authorization (mismo patrón que openDocument de admin.js) */
  async function openCedula(v) {
    const win = window.open("", "_blank");  // antes del await para que el navegador no la bloquee
    try {
      const res = await fetch(`${API_BASE}/admin/veterinaries/${encodeURIComponent(v.id)}/cedula`, { headers: { Authorization: `Bearer ${currentToken}` } });
      if (res.status === 401) { logout("Tu sesión expiró. Inicia sesión de nuevo."); throw Object.assign(new Error(""), { silent: true }); }
      const type = res.headers.get("content-type") || "";
      if (!res.ok || type.includes("application/json")) {
        let body = null;
        try { body = await res.json(); } catch { body = null; }
        // Respaldo: si el servidor responde con el id del documento (o aún no tiene la ruta), se abre por /admin/documents
        const id = (body && (body.document_id || body.cedula_document_id)) || (res.status === 404 && body && body.detail === "Not Found" ? v.cedula_document_id : null);
        if (res.ok || id) {
          if (!id) throw new Error("Esta clínica no tiene cédula cargada.");
          if (win) win.close();
          return openDocument(id);
        }
        const detail = body && typeof body.detail === "string" ? body.detail : "";
        throw new Error(detail || (res.status === 404 ? "Esta clínica no tiene cédula cargada." : `No se pudo abrir la cédula (error ${res.status}).`));
      }
      const url = URL.createObjectURL(await res.blob());
      if (win) win.location.href = url; else window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      if (win) win.close();
      throw err;
    }
  }

  /* Verificación con evidencia (gap-veterinarias-y-resenas 03 y 16): carrera que muestra el RNP y captura
     fechada de la consulta, que se guarda como documento privado (12 meses tras la baja o el rechazo). */
  function verify(v) {
    const body = $("#modal-body");
    body.innerHTML = `<h3>Verificar «${escapeHtml(v.name)}»</h3>
      <ol class="hint" style="padding-left:18px">
        <li>Abre la cédula que envió la clínica («Ver cédula»).</li>
        <li>Busca la cédula <strong>${escapeHtml(v.cedula_profesional || "")}</strong> de <strong>${escapeHtml(v.responsible_vet_name || "")}</strong> en el
          <a href="${SEP_URL}" target="_blank" rel="noopener noreferrer">Registro Nacional de Profesionistas (SEP)</a>.</li>
        <li>Toma una captura de pantalla del resultado donde se vean la fecha, el nombre, el número y la carrera.</li>
      </ol>
      <form id="vet-verify-form" novalidate>
        <label for="vv-carrera">Carrera que muestra el RNP</label>
        <input id="vv-carrera" maxlength="255" required value="${escapeHtml(v.cedula_carrera || "Médico Veterinario Zootecnista")}" style="width:100%">
        <label for="vv-file" style="display:block;margin-top:10px">Captura del cotejo (JPG, PNG, WebP o PDF; privada)</label>
        <input id="vv-file" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" required>
        <label style="display:flex;gap:8px;align-items:flex-start;margin-top:10px;text-align:left"><input type="checkbox" id="vv-ok" style="width:auto;flex:0 0 auto;margin-top:3px">
          <span style="flex:1">El nombre, el número y la carrera (Medicina Veterinaria y Zootecnia o afín) coinciden con la cédula enviada.</span></label>
        <p class="hint">Al verificarla, la clínica aparece en el directorio y en el mapa con la insignia «Cédula verificada» durante 12 meses.</p>
        <div style="display:flex;gap:8px;margin-top:12px"><button type="submit" class="btn-success" id="vv-send">Verificar</button>
          <button type="button" class="btn-secondary" id="vv-cancel">Cancelar</button></div>
      </form>`;
    modal.classList.remove("hidden");
    $("#vv-cancel").addEventListener("click", () => modal.classList.add("hidden"));
    $("#vet-verify-form").addEventListener("submit", (e) => {
      e.preventDefault();
      run(async () => {
        const carrera = $("#vv-carrera").value.trim();
        const file = $("#vv-file").files[0];
        if (carrera.length < 3) throw new Error("Escribe la carrera tal como aparece en el RNP.");
        if (!file) throw new Error("Sube la captura del cotejo en el RNP.");
        if (file.size > 10 * 1024 * 1024) throw new Error("La captura debe pesar menos de 10 MB.");
        if (!$("#vv-ok").checked) throw new Error("Confirma que los datos coinciden.");
        const send = $("#vv-send");
        send.disabled = true;
        try {
          const fd = new FormData();
          fd.append("file", file);
          const up = await api("/upload/document", { method: "POST", body: fd });
          await api(`/admin/veterinaries/${v.id}/verify`, jsonOpts("POST", { carrera, evidence_document_id: up.id }));
          modal.classList.add("hidden");
          loadVeterinaries();
        } finally { send.disabled = false; }
      });
    });
  }

  async function reject(v) {
    const note = (prompt(`Motivo del rechazo de «${v.name}» (lo verá la clínica para corregirlo):`, "") || "").trim();
    if (!note) return;
    if (note.length < 3) { alert("Escribe un motivo de al menos 3 caracteres."); return; }
    await api(`/admin/veterinaries/${v.id}/reject`, jsonOpts("POST", { note }));
    loadVeterinaries();
  }

  function clinicCell(v) {
    const where = [v.address, v.city, v.state, v.postal_code ? `C.P. ${v.postal_code}` : ""].filter(Boolean).join(", ");
    const contact = [v.phone ? `Tel. ${v.phone}` : "", v.whatsapp ? `WhatsApp ${v.whatsapp}` : "", v.email || ""].filter(Boolean).join(" · ");
    const web = v.website ? `<br>${link(v.website, v.website)}` : "";
    const extra = (v.emergency_24h ? ' <span class="badge warn">24 h</span>' : "") + (v.is_hidden ? ' <span class="badge bad">oculta</span>' : "");
    const pub = v.status === "verified" ? ` <a href="/app/?vet=${encodeURIComponent(v.id)}" target="_blank" rel="noopener">ver ↗</a>` : "";
    return `<strong>${escapeHtml(v.name)}</strong>${extra}${pub}<br><small>${escapeHtml(where || "-")}</small>${contact ? `<br><small>${escapeHtml(contact)}</small>` : ""}${web}`;
  }

  function responsibleCell(v) {
    return `${escapeHtml(v.responsible_vet_name || "-")}<br><small>Cédula <strong>${escapeHtml(v.cedula_profesional || "-")}</strong>`
      + `${v.cedula_institution ? ` · ${escapeHtml(v.cedula_institution)}` : ""}</small>`
      + `<br><small><a href="${SEP_URL}" target="_blank" rel="noopener noreferrer">Buscar en el RNP (SEP) ↗</a></small>`;
  }

  function statusCell(v) {
    let out = vetBadge(v.status);
    if (v.status === "verified" && v.verified_at) out += `<br><small>${escapeHtml(fmtDate(v.verified_at))}</small>`;
    if (v.cedula_carrera) out += `<br><small>Carrera: ${escapeHtml(v.cedula_carrera)}</small>`;
    if (v.verification_expires_at) out += `<br><small>vence ${escapeHtml(fmtDate(v.verification_expires_at))}</small>`;
    if (v.rejection_note) out += `<br><small>${escapeHtml(v.rejection_note)}</small>`;
    return out;
  }

  function actions(v) {
    const cedula = button("Ver cédula", () => run(() => openCedula(v)), "btn-secondary");
    if (!v.cedula_document_id && v.cedula_document_id !== undefined) {
      cedula.disabled = true;
      // La imagen se borra 30 días después de la decisión (tabla de conservación); queda la constancia del cotejo
      cedula.title = v.cedula_document_purged_at ? "Imagen borrada a los 30 días de la verificación; coteja el número en el RNP"
        : "La clínica no subió la cédula";
    }
    const out = [cedula];
    if (v.verification_evidence_document_id) out.push(button("Ver captura del cotejo", () => run(() => openEvidence(v)), "btn-secondary"));
    if (v.status !== "verified") out.push(button("Verificar", () => verify(v), "btn-success"));
    else out.push(button("Reverificar", () => verify(v), "btn-secondary"));
    if (v.status !== "rejected") out.push(button(v.status === "verified" ? "Revocar" : "Rechazar", () => run(() => reject(v)), "btn-danger"));
    if (v.status === "verified" && typeof hideButton === "function") out.push(hideButton("veterinary", v, loadVeterinaries));
    return out;
  }

  async function loadVeterinaries() {
    // Con búsqueda el servidor filtra por texto (q) y se piden hasta 200 de una vez
    const searching = !!st.q;
    const params = searching ? new URLSearchParams({ skip: 0, limit: SEARCH_LIMIT }) : new URLSearchParams({ skip: st.page * PAGE_SIZE, limit: PAGE_SIZE + 1 });
    if (st.status) params.set("status", st.status);
    if (st.q) params.set("q", st.q);
    let items;
    try { items = await api(`/admin/veterinaries?${params}`); }
    catch (e) {
      if (!missing(e)) throw e;
      $("#veterinaries-table").innerHTML = '<p class="empty">El módulo de veterinarias del servidor todavía no está disponible.</p>';
      $("#veterinaries-pagination").innerHTML = "";
      return;
    }
    items = Array.isArray(items) ? items : (items && items.items) || [];
    const hasMore = !searching && items.length > PAGE_SIZE;
    const fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    const q = fold(st.q);
    const shown = (searching ? items : items.slice(0, PAGE_SIZE)).filter((v) => !q
      || [v.name, v.city, v.state, v.cedula_profesional, v.responsible_vet_name, v.owner_email].some((x) => fold(x).includes(q)));
    const rows = shown.map((v) => [
      v.id, thumb(v.photos), clinicCell(v), responsibleCell(v),
      v.owner ? `${escapeHtml(v.owner.full_name)}${v.owner_email ? `<br><small>${escapeHtml(v.owner_email)}</small>` : ""}` : escapeHtml(v.owner_email || `#${v.owner_user_id}`),
      statusCell(v), v.google_place_id || v.google_linked ? (v.google_maps_url ? link(v.google_maps_url, "Vinculada ↗") : "Vinculada") : "-",
      fmtDate(v.created_at), actions(v),
    ]);
    renderTable("veterinaries-table", ["ID", "Foto", "Clínica", "Responsable", "Registró", "Estado", "Google Maps", "Creada", "Acciones"], rows);
    if (searching) {
      $("#veterinaries-pagination").innerHTML = `<span>${rows.length} resultado(s)${items.length >= SEARCH_LIMIT ? ` (se muestran los primeros ${SEARCH_LIMIT}; afina la búsqueda)` : ""}.</span>`;
    } else renderPagination("veterinaries-pagination", st.page, hasMore, (p) => { st.page = p; run(loadVeterinaries); });
  }

  /* Reseñas retenidas por el filtro (insultos o imputaciones) u ocultas por moderación:
     GET /admin/veterinary-reviews?hidden=true; publicar = PATCH /admin/content/veterinary_review/{id} {hidden:false} */
  async function loadHeldReviews() {
    let items;
    try { items = await api("/admin/veterinary-reviews?hidden=true&limit=100"); }
    catch (e) { if (missing(e)) { $("#vet-reviews-table").innerHTML = ""; return; } throw e; }
    const rows = (items || []).map((r) => [
      r.id, escapeHtml(r.veterinary_name || `#${r.veterinary_id}`),
      `${escapeHtml((r.user && r.user.full_name) || r.author_name || "-")}${r.user_email ? `<br><small>${escapeHtml(r.user_email)}</small>` : ""}`,
      `${"★".repeat(Math.max(0, Math.min(5, +r.rating || 0)))}`, `<div style="max-width:420px;white-space:pre-line">${escapeHtml(r.text || "-")}</div>`,
      fmtDate(r.updated_at || r.created_at),
      typeof hideButton === "function" ? hideButton("veterinary_review", r, loadHeldReviews) : "-",
    ]);
    renderTable("vet-reviews-table", ["ID", "Clínica", "Autor", "Calificación", "Texto", "Fecha", "Acción"], rows);
  }

  /* Aclaraciones y quejas (también de personas sin cuenta): plazo de 5 días hábiles (aclaración) o 72 horas
     hábiles (queja). Publicar = la aclaración aparece junto a la reseña, sin comentarios. */
  const REQ_KIND = { aclaracion: "Aclaración", queja: "Queja" };
  const REQ_STATUS = { pending: ["pendiente", "warn"], published: ["publicada", "ok"], resolved: ["atendida", "ok"], rejected: ["no procede", "bad"] };
  const REQ_RELATION = { clinica: "La clínica", aludido: "Persona aludida", cliente: "Cliente", otro: "Otra relación" };
  const REQ_REASON = {
    honor_reputacion: "Afecta honor o reputación", resena_falsa: "Reseña falsa o pagada", datos_personales: "Datos personales",
    cedula_falsa: "Cédula o veterinario falso", condiciones_sanitarias: "Condiciones sanitarias", publicidad_enganosa: "Publicidad engañosa", otro: "Otro",
  };
  async function resolveRequest(r, action) {
    const ask = { publish: "Nota para quien la pidió (se publicará la aclaración tal cual, sin comentarios):",
      resolve: "¿Qué hiciste? (se le envía a quien la presentó):", reject: "Motivo por el que no procede (se le envía a quien la presentó):" }[action];
    const note = (prompt(ask, action === "publish" ? "Publicamos tu aclaración junto a la reseña." : "") || "").trim();
    if (!note) return;
    if (note.length < 3) { alert("Escribe una nota de al menos 3 caracteres."); return; }
    await api(`/admin/veterinary-requests/${r.id}/resolve`, jsonOpts("POST", { action, note }));
    loadRequests();
  }
  async function loadRequests() {
    const status = ($("#vet-req-status") || {}).value || "pending";
    let items;
    try { items = await api(`/admin/veterinary-requests?${new URLSearchParams({ status, limit: 100 })}`); }
    catch (e) { if (missing(e)) { $("#vet-requests-table").innerHTML = ""; return; } throw e; }
    const rows = (items || []).map((r) => {
      const [label, cls] = REQ_STATUS[r.status] || [r.status, ""];
      const who = `${escapeHtml(r.name || "-")}${r.email ? `<br><small>${escapeHtml(r.email)}</small>` : ""}<br><small>${escapeHtml(REQ_RELATION[r.relation] || r.relation)}${r.user_id ? ` · cuenta #${+r.user_id}` : " · sin cuenta"}</small>`;
      const review = r.review_id ? `<div style="max-width:260px;white-space:pre-line"><small>#${+r.review_id}: ${escapeHtml(r.review_text || "(sin texto)")}</small></div>` : "-";
      const due = `${escapeHtml(fmtDate(r.due_at))}${r.overdue ? ' <span class="badge bad">vencida</span>' : ""}`;
      const acts = [];
      if (r.status === "pending") {
        if (r.kind === "aclaracion" && r.review_id) acts.push(button("Publicar", () => run(() => resolveRequest(r, "publish")), "btn-success"));
        acts.push(button("Atendida", () => run(() => resolveRequest(r, "resolve")), "btn-secondary"));
        acts.push(button("No procede", () => run(() => resolveRequest(r, "reject")), "btn-danger"));
      } else if (r.resolution_note) acts.push(el("small", { text: r.resolution_note }));
      return [
        r.id, `${escapeHtml(REQ_KIND[r.kind] || r.kind)}${r.reason ? `<br><small>${escapeHtml(REQ_REASON[r.reason] || r.reason)}</small>` : ""}`,
        `${escapeHtml(r.veterinary_name || `#${r.veterinary_id}`)} <a href="/app/?vet=${encodeURIComponent(r.veterinary_id)}" target="_blank" rel="noopener">ver ↗</a>`,
        review, who, `<div style="max-width:360px;white-space:pre-line">${escapeHtml(r.text)}</div>`,
        `<span class="badge ${cls}">${escapeHtml(label)}</span><br><small>${escapeHtml(fmtDate(r.created_at))}</small>`, due, acts,
      ];
    });
    renderTable("vet-requests-table", ["Folio", "Tipo", "Clínica", "Reseña", "Quién", "Texto", "Estado", "Plazo", "Acciones"], rows);
  }

  loaders.veterinaries = () => Promise.all([loadVeterinaries(), loadHeldReviews(), loadRequests()]);
  const reqBtn = $("#vet-req-btn");
  if (reqBtn) reqBtn.addEventListener("click", () => run(loadRequests));
  $("#vets-filter-btn").addEventListener("click", () => {
    st.status = $("#vets-filter-status").value;
    st.q = $("#vets-filter-q").value.trim().slice(0, 100);
    st.page = 0;
    run(loadVeterinaries);
  });
  $("#vets-filter-q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#vets-filter-btn").click(); });

  window.AdminVeterinarias = { loadVeterinaries, loadHeldReviews, loadRequests, openCedula, openEvidence };
})();
