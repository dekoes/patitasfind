/* ============================================================
   GuauWoow Admin — Moderación legal (contrato K-REPORTES)
   Pestañas: cola priorizada (menores primero, con plazos), apelaciones, avisos de derechos de autor,
   requerimientos de autoridades (tres niveles), bóveda de evidencia y medidas con declaración de motivos.
   El material de abuso sexual infantil NUNCA se muestra: solo metadatos (el backend quita foto y título).
   Endpoints: GET /admin/cumplimiento/resumen | cola | medidas | apelaciones | derechos-autor | autoridades | evidencia,
   PATCH /admin/reports/{id}, PATCH /admin/cumplimiento/reportes/{id}/objetivo,
   POST /admin/cumplimiento/apelaciones/{id}/resolver, POST /admin/cumplimiento/derechos-autor/{id}/<accion>,
   POST|PATCH /admin/cumplimiento/autoridades[/{id}], POST /admin/cumplimiento/autoridades/{id}/preservar,
   GET /admin/cumplimiento/evidencia/verificar, POST /admin/cumplimiento/evidencia/{id}/retencion,
   GET /admin/cumplimiento/evidencia/{id}/exportar (superadmin), POST …/liberar-cuarentena (superadmin),
   GET /admin/cumplimiento/reportes/{id}/senales y POST …/{confirmar,descartar}-cuarentena (cuarentena preventiva).
   Se carga después de admin.js y usa sus utilidades globales (api, jsonOpts, run, escapeHtml, el, button, select,
   renderTable, fmtDate, statusBadge, loaders, REASON_ES, ACTION_ES, currentToken, API_BASE, logout, $, $$).
   ============================================================ */
"use strict";

(() => {
  const REASONS = {
    involucra_menor: "Involucra a una niña, niño o adolescente", abuso_sexual_infantil: "Material de abuso sexual infantil",
    acoso: "Acoso", abuso_sexual: "Abuso, explotación o violencia sexual", odio_violencia_masiva: "Discurso de odio o violencia masiva",
    incitacion_odio_violencia: "Incitación al odio o a la violencia", conductas_ilicitas: "Conductas ilícitas o apología del delito",
    pornografia: "Pornografía", suicidio_autolesiones: "Suicidio, autolesiones o trastornos alimenticios",
    contenido_intimo: "Contenido íntimo sin consentimiento", venta_animal: "Venta o cobro por un animal",
    mi_imagen: "Mi imagen o mis datos", difamacion: "Difamación o acusación", suplantacion: "Suplantación",
    fraude: "Estafa o solicitud de dinero", spam: "Spam", retiro_autor: "Retiro pedido por la persona autora",
  };
  if (typeof REASON_ES === "object") Object.assign(REASON_ES, REASONS);
  if (typeof ACTION_ES === "object") Object.assign(ACTION_ES, { quarantine: "En cuarentena" });

  const PRIORITY = { 0: ["Menores", "bad"], 1: ["Urgente", "warn"], 2: ["Estafas y venta", "warn"], 3: ["General", ""] };
  const NOTICE_STATUS = {
    received: ["recibido", "warn"], incomplete: ["incompleto", "warn"], removed: ["retirado", "ok"], rejected: ["no procede", ""],
    counter_notice: ["contra-aviso", "bad"], litigation: ["procedimiento", "bad"], restored: ["restaurado", ""], final: ["firme", "ok"],
  };
  const AUTH_STATUS = ["recibido", "en_revision", "incompleto", "preservado", "entregado", "entregado_parcial", "rechazado",
    "cerrado", "pendiente_denuncia", "denunciado"];
  const AUTH_KINDS = [["datos_cuenta", "Datos de cuenta (nivel 1)"], ["comunicaciones", "Contenido de comunicaciones (nivel 2)"],
    ["ubicacion", "Ubicación (nivel 3)"], ["conservacion", "Orden de conservación"], ["retiro", "Retiro o bloqueo de contenido"],
    ["orden_proteccion", "Orden de protección (violencia digital)"], ["denuncia", "Denuncia o alerta que presentamos"], ["otro", "Otro"]];
  const AUTH_TYPES = [["ministerio_publico", "Ministerio Público / Fiscalía"], ["juez", "Juez"], ["paot", "PAOT o procuraduría ambiental"],
    ["impi", "IMPI"], ["profeco", "PROFECO"], ["indautor", "INDAUTOR"], ["policia", "Policía / Guardia Nacional"], ["otra", "Otra"]];
  const TARGET_TYPES = [["dog", "Perro"], ["lost_report", "Perdido/encontrado"], ["user", "Usuario"], ["refuge", "Refugio"],
    ["product", "Producto"], ["veterinary", "Veterinaria"], ["veterinary_review", "Reseña"]];
  const st = { tab: "cola", priority: "", overdue: false, notices: "open", authorities: "open", appeals: "pending", evidenceCsam: "" };

  const badge = (label, cls = "") => `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
  const prioBadge = (p) => { const [l, c] = PRIORITY[p] || [String(p), ""]; return badge(l, c); };
  const due = (d, overdue) => `${fmtDate(d)}${overdue ? ` ${badge("vencido", "bad")}` : ""}`;
  const small = (t) => `<br><small>${escapeHtml(t)}</small>`;

  function targetCell(r) {
    const t = r.target || {};
    const flags = (t.is_hidden ? ` ${badge("oculto", "bad")}` : "") + (t.exists === false && r.target_type !== "sin_identificar" ? ` ${badge("eliminado")}` : "");
    const link = /^\/app\/\?(dog|report|vet)=\d+$/.test(t.url || "") ? ` <a href="${escapeHtml(t.url)}" target="_blank" rel="noopener">ver ↗</a>` : "";
    const where = r.target_url ? small(`Enlace o nombre: ${r.target_url}`) : "";
    const owner = t.owner_name ? small(`de ${t.owner_name}${t.owner_id ? ` (#${t.owner_id})` : ""}`) : "";
    return `<strong>${escapeHtml(t.label || r.target_type)}</strong>: ${escapeHtml(t.title || `#${r.target_id}`)}${flags}${link}${owner}${where}`;
  }

  /* ---------------------------------------------------------------- resumen y pestañas */
  async function loadSummary() {
    const s = await api("/admin/cumplimiento/resumen");
    const open = s.reportes_abiertos || {};
    $("#ml-summary").innerHTML = [
      `Menores: <strong>${escapeHtml(open.Menores ?? 0)}</strong>`, `Urgentes: <strong>${escapeHtml(open.Urgente ?? 0)}</strong>`,
      `Vencidos: <strong>${escapeHtml(s.reportes_vencidos)}</strong>`, `Apelaciones: <strong>${escapeHtml(s.apelaciones_pendientes)}</strong>`,
      `Derechos de autor: <strong>${escapeHtml(s.avisos_derechos_pendientes)}</strong>`, `Autoridades: <strong>${escapeHtml(s.autoridades_abiertas)}</strong>`,
      `Cuarentenas: <strong>${escapeHtml(s.cuarentenas)}</strong>`,
      s.cuarentenas_preventivas ? badge(`${s.cuarentenas_preventivas} cuarentena(s) preventiva(s): decide un superadmin hoy`, "bad") : "",
      s.contacto_24_7_configurado ? badge("contacto 24/7 configurado", "ok") : badge("falta AUTHORITY_CONTACT_EMAIL/PHONE", "bad"),
    ].join(" · ");
  }

  const TABS = { cola: loadQueue, apelaciones: loadAppeals, derechos: loadNotices, autoridades: loadAuthorities, evidencia: loadEvidence, medidas: loadActions };

  function showTab(tab) {
    st.tab = tab;
    $$("#moderacion-legal .ml-tab").forEach((b) => {
      b.classList.toggle("btn-success", b.dataset.tab === tab);
      b.classList.toggle("btn-secondary", b.dataset.tab !== tab);
      b.setAttribute("aria-pressed", String(b.dataset.tab === tab));
    });
    $$("#moderacion-legal .ml-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== tab));
    return TABS[tab]();
  }

  /* ---------------------------------------------------------------- cola priorizada */
  // Cuarentena preventiva (reporte de abuso sexual infantil): vista protegida sin el material; decide un superadmin
  function signalLines(s) {
    const lines = [];
    const rep = s.reportantes || {};
    lines.push(`Reportes abiertos: ${s.reportes_abiertos} (sin cuenta: ${rep.sin_cuenta}, con cuenta: ${rep.con_cuenta}, con teléfono verificado: ${rep.con_telefono_verificado}, IP distintas: ${rep.ips_distintas})`);
    const c = s.contenido || {};
    lines.push(`Contenido: ${c.tipo} #${c.id}${c.existe ? "" : " (ya no existe)"}${c.creado_en ? ` · creado ${fmtDate(c.creado_en)}` : ""}${c.texto ? ` · «${c.texto}»` : ""}`);
    if (c.analisis_ia_previo) lines.push(`Análisis de IA hecho antes del reporte: ${JSON.stringify(c.analisis_ia_previo)}`);
    (s.archivos || []).forEach((f) => lines.push(`Archivo ${f.nombre}: ${f.formato || "ilegible"} ${f.ancho || "?"}×${f.alto || "?"}, ${f.bytes} bytes, SHA-256 ${String(f.sha256).slice(0, 16)}…${f.coincide_con_material_confirmado ? " · COINCIDE con material ya confirmado" : ""}`));
    if (!(s.archivos || []).length) lines.push("Sin archivos en la bóveda.");
    const u = s.cuenta;
    if (u) lines.push(`Cuenta #${u.id} (${u.rol}) · creada ${fmtDate(u.creada_en)} · teléfono ${u.telefono_verificado ? "verificado" : "sin verificar"} · medidas previas: ${u.medidas_previas} · cuarentenas confirmadas: ${u.cuarentenas_confirmadas}`);
    if (s.reporte && s.reporte.detalles) lines.push(`Detalles del reporte: ${s.reporte.detalles}`);
    return lines;
  }

  function pendingQuarantineActions(r) {
    const box = el("div", { class: "ml-signals hidden" });
    const motivo = el("input", { type: "text", placeholder: "Motivo de la decisión (obligatorio)", maxlength: "2000" });
    const decide = (path, question) => run(async () => {
      const text = motivo.value.trim();
      if (text.length < 10) throw new Error("Escribe el motivo de la decisión (al menos 10 caracteres).");
      if (!confirm(question)) return;
      await api(`/admin/cumplimiento/reportes/${r.id}/${path}`, jsonOpts("POST", { motivo: text }));
      await Promise.all([loadQueue(), loadSummary()]);
    });
    return [
      el("span", { class: "badge bad", text: "cuarentena preventiva" }),
      button("Ver señales (sin material)", () => run(async () => {
        const s = await api(`/admin/cumplimiento/reportes/${r.id}/senales`);
        box.replaceChildren(...signalLines(s).map((t) => el("div", { text: t })));
        box.classList.remove("hidden");
      }), "btn-secondary"),
      motivo,
      button("Confirmar cuarentena", () => decide("confirmar-cuarentena",
        "¿Confirmar la cuarentena? Se bloquean los archivos por hash, se quitan de la ficha y se registra la denuncia pendiente ante el Ministerio Público. Solo un superadmin puede hacerlo."), "btn-success"),
      button("Descartar: reporte falso", () => decide("descartar-cuarentena",
        "¿Descartar la cuarentena? Los archivos vuelven a la Plataforma y el contenido se muestra de nuevo si nada más lo mantiene oculto."), "btn-secondary"),
      box,
    ];
  }

  function queueActions(r) {
    if (r.quarantine_pending) return pendingQuarantineActions(r);
    if (r.target_type === "sin_identificar") {
      const type = select(TARGET_TYPES, "dog");
      const id = el("input", { type: "number", min: "1", placeholder: "id", class: "ml-num" });
      return [type, id, button("Asignar contenido", () => run(async () => {
        if (!id.value) throw new Error("Escribe el id del contenido.");
        await api(`/admin/cumplimiento/reportes/${r.id}/objetivo`, jsonOpts("PATCH", { target_type: type.value, target_id: Number(id.value) }));
        loadQueue();
      }), "btn-secondary"), button("Descartar", () => resolveReport(r, "dismissed", null, "", null), "btn-secondary")];
    }
    const opts = [["", "Sin acción"]];
    if (r.target_type !== "user") opts.push(["hide_content", r.target_type === "refuge" ? "Suspender refugio" : "Ocultar contenido"]);
    opts.push(["suspend_user", "Suspender usuario"]);
    if (r.target_type !== "refuge") opts.push(["quarantine", "Cuarentena (abuso sexual infantil)"]);
    const action = select(opts, "");
    const rule = select([["", "Regla: el motivo del reporte"], ...Object.entries(REASON_ES).filter(([k]) => k !== "retiro_autor")], "");
    const notes = el("input", { type: "text", placeholder: "Notas internas", maxlength: "2000" });
    return [action, rule, notes,
      button("Resolver", () => resolveReport(r, "resolved", action.value || null, notes.value, rule.value || null), "btn-success"),
      button("Descartar", () => resolveReport(r, "dismissed", null, notes.value, null), "btn-secondary")];
  }

  function resolveReport(r, status, action, notes, rule) {
    return run(async () => {
      if (action === "quarantine" && !confirm("¿Poner en cuarentena? Se retiran los archivos de la Plataforma, se bloquean por hash y se registra la denuncia pendiente ante el Ministerio Público. No descargues ni reproduzcas el material.")) return;
      if (action === "suspend_user" && !confirm("¿Suspender la cuenta? La persona recibe el aviso con la regla y cómo apelar.")) return;
      if (status === "dismissed" && r.auto_hidden && !confirm("El contenido se ocultó al recibir el reporte. Al descartarlo vuelve a mostrarse. ¿Continuar?")) return;
      await api(`/admin/reports/${r.id}`, jsonOpts("PATCH", { status, action, notes: (notes || "").trim() || null, rule }));
      await Promise.all([loadQueue(), loadSummary()]);
    });
  }

  async function loadQueue() {
    const params = new URLSearchParams({ limit: 200 });
    if (st.priority !== "") params.set("prioridad", st.priority);
    if (st.overdue) params.set("vencidos", "true");
    const rows = await api(`/admin/cumplimiento/cola?${params}`);
    renderTable("ml-queue-table", ["Reporte", "Prioridad", "Contenido", "Motivo", "Detalles", "Origen", "Plazo", "Acción"], rows.map((r) => [
      `#${escapeHtml(r.id)}${r.folio ? small(r.folio) : ""}`,
      prioBadge(r.priority) + (r.auto_hidden ? `<br>${badge("oculto al recibirlo", "ok")}` : ""),
      targetCell(r) + (r.owner_prior_actions ? `<br>${badge(`medidas previas: ${r.owner_prior_actions} (${r.owner_prior_same_rule} por este motivo)`, "warn")}` : ""),
      escapeHtml(r.reason_label || REASON_ES[r.reason] || r.reason) + (r.open_reports_for_target > 1 ? ` ${badge(`${r.open_reports_for_target} abiertos`, "bad")}` : ""),
      escapeHtml(r.details || "-"),
      r.source === "publico" ? `Formulario público${r.contact_email ? small(r.contact_email) : small("sin correo")}`
        : r.reporter ? `${escapeHtml(r.reporter.full_name)}${small(r.reporter.email || "")}` : escapeHtml(r.source),
      due(r.due_at, r.overdue),
      queueActions(r),
    ]));
  }

  /* ---------------------------------------------------------------- apelaciones */
  async function loadAppeals() {
    const rows = await api(`/admin/cumplimiento/apelaciones?estado=${encodeURIComponent(st.appeals)}`);
    renderTable("ml-appeals-table", ["Apelación", "Medida", "Argumentos", "Pruebas", "Plazo", "Resolución"], rows.map((a) => {
      const m = a.action || {};
      const cell = a.status === "pending" ? (() => {
        const note = el("textarea", { rows: "3", maxlength: "4000", placeholder: "Respuesta razonada para la persona" });
        const go = (decision) => run(async () => {
          if (note.value.trim().length < 10) throw new Error("Escribe una respuesta razonada (al menos 10 caracteres).");
          await api(`/admin/cumplimiento/apelaciones/${a.id}/resolver`, jsonOpts("POST", { decision, nota: note.value.trim() }));
          await Promise.all([loadAppeals(), loadSummary()]);
        });
        return [note, button("Confirmar medida", () => go("confirmar"), "btn-secondary"), button("Revocar medida", () => go("revocar"), "btn-success")];
      })() : `${escapeHtml(a.status === "reversed" ? "Revocada" : "Confirmada")}${small(a.decision_note || "")}${small(`por #${a.decided_by_id} · ${fmtDate(a.decided_at)}`)}`;
      return [
        `${escapeHtml(a.folio)}${small(a.email || "")}${small(fmtDate(a.created_at))}`,
        `${escapeHtml(m.label || m.action || "")}${small(m.rule_text || "")}${small(`${m.folio || ""} · decidió #${m.decided_by_id ?? "automática"}`)}`,
        escapeHtml(a.arguments), escapeHtml(a.evidence_text || "-"), due(a.due_at, a.overdue), cell,
      ];
    }));
  }

  /* ---------------------------------------------------------------- derechos de autor */
  function noticeActions(n) {
    const note = el("input", { type: "text", placeholder: "Nota (se envía a quien avisó)", maxlength: "4000" });
    const post = (path, body, ask) => run(async () => {
      if (ask && !confirm(ask)) return;
      await api(`/admin/cumplimiento/derechos-autor/${n.id}/${path}`, jsonOpts("POST", body));
      await Promise.all([loadNotices(), loadSummary()]);
    });
    if (["received", "incomplete"].includes(n.status)) {
      const type = select(TARGET_TYPES.filter(([k]) => !["user", "refuge"].includes(k)), n.target_type || "dog");
      const id = el("input", { type: "number", min: "1", placeholder: "id", class: "ml-num", value: n.target_id || "" });
      return [type, id, note,
        button("Retirar", () => post("retirar", { target_type: type.value, target_id: id.value ? Number(id.value) : null, nota: note.value.trim() || null },
          "¿Retirar el contenido? Se oculta, se bloquea la imagen, se avisa a quien lo subió y cuenta para la política de reincidentes."), "btn-danger"),
        n.status === "received" ? button("Pedir completar", () => post("incompleto", { nota: note.value.trim() || null }), "btn-secondary") : null,
        button("No procede", () => post("rechazar", { nota: note.value.trim() || null }), "btn-secondary")].filter(Boolean);
    }
    if (n.status === "counter_notice") {
      return [note, button("Procedimiento acreditado", () => post("procedimiento", { nota: note.value.trim() || null },
        "¿Quien avisó acreditó un procedimiento? El contenido sigue retirado."), "btn-secondary"),
      button("Restaurar ya", () => post("restaurar", { nota: note.value.trim() || null }), "btn-success")];
    }
    if (["removed", "litigation"].includes(n.status)) {
      return [note, button("Marcar firme", () => post("cerrar", { nota: note.value.trim() || null }), "btn-secondary"),
        button("Restaurar", () => post("restaurar", { nota: note.value.trim() || null }, "¿Restaurar el contenido?"), "btn-success")];
    }
    return "-";
  }

  async function loadNotices() {
    const rows = await api(`/admin/cumplimiento/derechos-autor?estado=${encodeURIComponent(st.notices)}`);
    renderTable("ml-notices-table", ["Aviso", "Estado", "Contenido", "Obra y hechos", "Quien avisa", "Contra-aviso", "Plazos", "Acción"], rows.map((n) => {
      const [label, cls] = NOTICE_STATUS[n.status] || [n.status, ""];
      const c = n.counter_notice;
      return [
        `${escapeHtml(n.folio)}${small(n.kind === "marca" ? "Marca" : "Derechos de autor")}${small(fmtDate(n.created_at))}`,
        badge(label, cls) + (n.strikes != null ? small(`Avisos procedentes de la cuenta (12 meses): ${n.strikes}`) : ""),
        `${n.target ? targetCell({ ...n, target_url: n.content_url }) : escapeHtml(n.content_url)}`,
        `<strong>Obra:</strong> ${escapeHtml(n.work)}<br><strong>Hechos:</strong> ${escapeHtml(n.facts)}`,
        `${escapeHtml(n.claimant_name)} (${escapeHtml(n.claimant_capacity)}${n.represented_name ? ` de ${escapeHtml(n.represented_name)}` : ""})${small(n.email)}${small(n.phone)}${n.representation_document ? small(`Documento: ${n.representation_document}`) : ""}`,
        c ? `${escapeHtml(c.folio)} · ${escapeHtml(c.name)}${small(`${c.basis}: ${c.basis_details}`)}${small(c.email)}` : "-",
        `Retiro: ${due(n.due_at, n.overdue)}${n.restore_from ? small(`Restaurar: ${fmtDate(n.restore_from)} a ${fmtDate(n.restore_until)}`) : ""}`,
        noticeActions(n),
      ];
    }));
  }

  /* ---------------------------------------------------------------- autoridades */
  function parseTargets(text) {
    return (text || "").split(/[,\s]+/).filter(Boolean).map((t) => {
      const [type, id] = t.split(":");
      if (!type || !/^\d+$/.test(id || "")) throw new Error(`Objetivo inválido: ${t}. Usa tipo:id, p. ej. user:12`);
      return { type, id: Number(id) };
    });
  }

  function authorityActions(a) {
    const status = select(AUTH_STATUS.map((s) => [s, s.replace(/_/g, " ")]), a.status);
    const decision = el("textarea", { rows: "2", maxlength: "4000", placeholder: "Decisión: qué se entrega y por qué" });
    decision.value = a.decision || "";
    const response = el("textarea", { rows: "2", maxlength: "4000", placeholder: "Resumen de la respuesta / acuse" });
    response.value = a.response_summary || "";
    const folio = el("input", { type: "text", maxlength: "120", placeholder: "Acuse o folio de la denuncia", value: a.external_folio || "" });
    const flags = ["authenticity_verified", "judicial_order", "participant_consent", "legal_review", "user_notified"].map((k) => {
      const box = el("input", { type: "checkbox" });
      box.checked = Boolean(a[k]);
      box.dataset.k = k;
      return el("label", { class: "ml-flag" }, [box, ` ${{ authenticity_verified: "auténtico", judicial_order: "orden judicial",
        participant_consent: "lo aporta un participante", legal_review: "revisión legal", user_notified: "se avisó a la persona" }[k]}`]);
    });
    const withheld = el("input", { type: "text", maxlength: "300", placeholder: "Si no se avisó: por qué", value: a.notice_withheld_reason || "" });
    const save = button("Guardar", () => run(async () => {
      const body = { status: status.value, decision: decision.value.trim() || null, response_summary: response.value.trim() || null,
        external_folio: folio.value.trim() || null, notice_withheld_reason: withheld.value.trim() || null };
      flags.forEach((l) => { const b = l.querySelector("input"); body[b.dataset.k] = b.checked; });
      await api(`/admin/cumplimiento/autoridades/${a.id}`, jsonOpts("PATCH", body));
      await Promise.all([loadAuthorities(), loadSummary()]);
    }), "btn-success");
    const preserve = button("Preservar", () => run(async () => {
      if (!confirm("¿Aplicar retención legal y guardar copia cifrada de las cuentas o contenidos señalados?")) return;
      const out = await api(`/admin/cumplimiento/autoridades/${a.id}/preservar`, jsonOpts("POST", {}));
      alert(`Retención aplicada: ${out.retenidas.length} evidencia(s) existentes y ${out.copias_nuevas.length} copia(s) nuevas.`);
      loadAuthorities();
    }), "btn-secondary");
    return [status, ...flags, decision, response, folio, withheld, save, preserve];
  }

  async function loadAuthorities() {
    const rows = await api(`/admin/cumplimiento/autoridades?estado=${encodeURIComponent(st.authorities)}`);
    renderTable("ml-authorities-table", ["Folio", "Autoridad", "Tipo y nivel", "Fundamento y datos pedidos", "Plazos", "Gestión"], rows.map((a) => [
      `${escapeHtml(a.folio)}${small(a.direction === "saliente" ? "Denuncia o alerta nuestra" : "Requerimiento recibido")}${a.involves_minor ? `<br>${badge("menores", "bad")}` : ""}${a.life_risk ? ` ${badge("riesgo vital", "bad")}` : ""}`,
      `${escapeHtml(a.authority_name)}${small(a.authority_type)}${a.case_number ? small(`Exp. ${a.case_number}`) : ""}`,
      `${escapeHtml(a.kind)}${a.level ? small(`Nivel ${a.level}: ${a.level_rule}`) : ""}${a.targets ? small(a.targets.map((t) => `${t.type}:${t.id}`).join(", ")) : ""}`,
      `${escapeHtml(a.legal_basis || "-")}${small(a.requested_data || "")}`,
      `Primera respuesta: ${due(a.first_response_due_at, a.overdue)}${a.due_at ? small(`Plazo del oficio: ${fmtDate(a.due_at)}`) : ""}${a.responded_at ? small(`Respondido: ${fmtDate(a.responded_at)}`) : ""}`,
      authorityActions(a),
    ]));
  }

  function bindAuthorityForm() {
    const form = $("#ml-authority-form");
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      run(async () => {
        const f = form.elements;
        const body = {
          direction: f.direction.value, kind: f.kind.value, level: f.level.value ? Number(f.level.value) : null,
          authority_name: f.authority_name.value.trim(),
          authority_type: f.authority_type.value, case_number: f.case_number.value.trim() || null,
          legal_basis: f.legal_basis.value.trim() || null, requested_data: f.requested_data.value.trim() || null,
          targets: parseTargets(f.targets.value), involves_minor: f.involves_minor.checked, life_risk: f.life_risk.checked,
          judicial_order: f.judicial_order.checked, participant_consent: f.participant_consent.checked,
          authenticity_verified: f.authenticity_verified.checked, authenticity_method: f.authenticity_method.value.trim() || null,
          legal_review: f.legal_review.checked,
          received_at: f.received_at.value ? new Date(f.received_at.value).toISOString() : null,
          due_at: f.due_at.value ? new Date(f.due_at.value).toISOString() : null,
        };
        if (body.authority_name.length < 3) throw new Error("Escribe el nombre de la autoridad.");
        await api("/admin/cumplimiento/autoridades", jsonOpts("POST", body));
        form.reset();
        await Promise.all([loadAuthorities(), loadSummary()]);
      });
    });
    form.elements.kind.replaceChildren(...AUTH_KINDS.map(([v, l]) => el("option", { value: v, text: l })));
    form.elements.authority_type.replaceChildren(...AUTH_TYPES.map(([v, l]) => el("option", { value: v, text: l })));
  }

  /* ---------------------------------------------------------------- evidencia */
  async function download(id) {
    const folio = prompt("Folio del requerimiento o denuncia (AUT-…) al que se entrega. Obligatorio para material en cuarentena:") || "";
    const res = await fetch(`${API_BASE}/admin/cumplimiento/evidencia/${encodeURIComponent(id)}/exportar${folio ? `?requerimiento=${encodeURIComponent(folio.trim())}` : ""}`,
      { headers: { Authorization: `Bearer ${currentToken}` } });
    if (res.status === 401) { logout("Tu sesión expiró. Inicia sesión de nuevo."); return; }
    if (!res.ok) {
      let body = null;
      try { body = await res.json(); } catch { body = null; }
      throw new Error((body && body.detail) || `No se pudo exportar (error ${res.status}).`);
    }
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: `evidencia-${id}.json` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  async function loadEvidence() {
    const params = new URLSearchParams({ limit: 200 });
    if (st.evidenceCsam !== "") params.set("csam", st.evidenceCsam);
    const rows = await api(`/admin/cumplimiento/evidencia?${params}`);
    renderTable("ml-evidence-table", ["Id", "Tipo", "Contenido", "Huella", "Conservar hasta", "Retención legal", "Acciones"], rows.map((e) => {
      const hold = button(e.legal_hold ? "Liberar retención" : "Retener", () => run(async () => {
        const motivo = prompt(e.legal_hold ? "Motivo o instrucciones de la autoridad para liberar:" : "Motivo de la retención legal (p. ej. folio del requerimiento):");
        if (motivo === null) return;
        await api(`/admin/cumplimiento/evidencia/${e.id}/retencion`, jsonOpts("POST", { legal_hold: !e.legal_hold, motivo: motivo.trim() || null }));
        loadEvidence();
      }), "btn-secondary");
      const actions = e.purged_at ? "Eliminada al vencer" : [hold, button("Exportar", () => run(() => download(e.id)), "btn-secondary")];
      if (e.is_csam && !e.purged_at) {
        actions.push(button("Liberar cuarentena", () => run(async () => {
          const motivo = prompt("Solo si el reporte fue falso. Motivo (queda en la bitácora):");
          if (!motivo || motivo.trim().length < 10) return;
          await api(`/admin/cumplimiento/evidencia/${e.id}/liberar-cuarentena`, jsonOpts("POST", { motivo: motivo.trim() }));
          loadEvidence();
        }), "btn-danger"));
      }
      return [
        `#${escapeHtml(e.id)}${small(fmtDate(e.created_at))}`,
        `${escapeHtml(e.kind)}${e.is_csam ? `<br>${badge("cuarentena", "bad")}` : ""}${e.reason ? small(REASON_ES[e.reason] || e.reason) : ""}`,
        `${escapeHtml(e.target_type)} #${escapeHtml(e.target_id ?? "-")}${e.owner_user_id ? small(`cuenta #${e.owner_user_id}`) : ""}${small(`${(e.files || []).length} archivo(s) · ${e.size_bytes} bytes`)}`,
        `<code>${escapeHtml((e.content_sha256 || "").slice(0, 16))}…</code>${small(`cadena ${String(e.row_hash || "").slice(0, 10)}…`)}`,
        fmtDate(e.retained_until),
        e.legal_hold ? `${badge("sí", "warn")}${small(e.legal_hold_reason || "")}` : "no",
        actions,
      ];
    }));
  }

  /* ---------------------------------------------------------------- medidas */
  async function loadActions() {
    const rows = await api("/admin/cumplimiento/medidas?limit=200");
    renderTable("ml-actions-table", ["Folio", "Medida", "Regla", "Detección", "Persona", "Aviso", "Apelar hasta", "Estado"], rows.map((m) => [
      `${escapeHtml(m.folio)}${small(fmtDate(m.created_at))}`,
      `${escapeHtml(m.action_label)}${m.duration_days ? small(`${m.duration_days} días, hasta ${fmtDate(m.ends_at)}`) : ""}`,
      escapeHtml(m.rule_text), escapeHtml(m.detection),
      m.user_id ? `#${escapeHtml(m.user_id)}` : "-",
      m.notice_sent_at ? fmtDate(m.notice_sent_at) : escapeHtml(m.notice_withheld_reason || "sin aviso"),
      fmtDate(m.appeal_until), statusBadge(m.status),
    ]));
  }

  /* ---------------------------------------------------------------- arranque */
  function bind() {
    const root = $("#moderacion-legal");
    if (!root) return;
    $$("#moderacion-legal .ml-tab").forEach((b) => b.addEventListener("click", () => run(() => showTab(b.dataset.tab))));
    $("#ml-queue-filter").addEventListener("click", () => {
      st.priority = $("#ml-queue-priority").value;
      st.overdue = $("#ml-queue-overdue").checked;
      run(loadQueue);
    });
    $("#ml-appeals-filter").addEventListener("change", (e) => { st.appeals = e.target.value; run(loadAppeals); });
    $("#ml-notices-filter").addEventListener("change", (e) => { st.notices = e.target.value; run(loadNotices); });
    $("#ml-authorities-filter").addEventListener("change", (e) => { st.authorities = e.target.value; run(loadAuthorities); });
    $("#ml-evidence-filter").addEventListener("change", (e) => { st.evidenceCsam = e.target.value; run(loadEvidence); });
    $("#ml-verify-chain").addEventListener("click", () => run(async () => {
      const out = await api("/admin/cumplimiento/evidencia/verificar");
      alert(out.ok ? `Cadena íntegra: ${out.rows} registro(s).` : `La cadena se rompe en el registro #${out.broken_at}. Avisa a seguridad.`);
    }));
    bindAuthorityForm();
  }

  bind();
  loaders["moderacion-legal"] = () => Promise.all([loadSummary(), showTab(st.tab)]);
  window.AdminCumplimiento = { loadQueue, loadAppeals, loadNotices, loadAuthorities, loadEvidence, loadActions, loadSummary };
})();
