/* ============================================================
   GuauWoow Admin — Consentimiento y edad (K-ACEPT, K-PREF, L-edad)
   Verificaciones reforzadas de edad (pedir / liberar), bitácora de aceptaciones encadenada y permisos.
   Endpoints: GET /admin/cumplimiento/edad?status, POST /admin/cumplimiento/edad/{user_id}/solicitar|liberar {note},
   GET /admin/cumplimiento/aceptaciones[/verificar]?user_id, GET /admin/cumplimiento/consentimientos?user_id,
   POST /admin/cumplimiento/documentos/sincronizar.
   Se carga después de admin.js y usa sus utilidades globales (api, jsonOpts, run, escapeHtml, fmtDate, button,
   renderTable, loaders, $).
   ============================================================ */
"use strict";

(() => {
  if (!$("#consentimiento")) return;
  const AGE_STATUS = { required: ["pendiente", "warn"], review: ["revisión manual", "bad"], passed: ["aprobada", "ok"], cleared: ["liberada", "ok"], failed: ["fallida", "bad"] };
  const METHOD = { registro: "Registro", reaceptacion: "Reaceptación", checkout: "Compra", anexo: "Anexo de aliado", donativo: "Donativo" };
  const PURPOSE = { notify_nearby: "Alertas cercanas", whatsapp_alerts: "Avisos por WhatsApp", email_marketing: "Correos promocionales",
    marketing_opt_in: "Correos promocionales", analytics_cookies: "Analítica (cookies)" };
  const badge = (s) => { const [l, c] = AGE_STATUS[s] || [s, ""]; return `<span class="badge ${c}">${escapeHtml(l)}</span>`; };
  const note = (msg) => { const n = prompt(msg); return n === null ? null : n.trim(); };

  async function loadAge() {
    const status = $("#cons-age-status").value;
    const rows = await api(`/admin/cumplimiento/edad?status=${encodeURIComponent(status)}`);
    renderTable("cons-age-table", ["Cuenta", "Estado", "Motivo", "Nota", "Pedida", "Resuelta", "Acciones"], rows.map((c) => [
      `#${c.user_id} ${escapeHtml(c.full_name)}<br><small>${escapeHtml(c.email)}</small>`,
      badge(c.status),
      escapeHtml(c.reason_label || c.reason) + (c.content_report_id ? `<br><small>reporte #${c.content_report_id}</small>` : ""),
      escapeHtml(c.note || "-") + (c.attempts ? `<br><small>${c.attempts} fecha(s) que no coincidieron</small>` : ""),
      fmtDate(c.created_at),
      c.resolved_at ? `${fmtDate(c.resolved_at)}<br><small>${escapeHtml(c.method || "")}</small>` : "-",
      c.status === "required" || c.status === "review" || c.status === "failed" ? [button("Liberar", () => run(async () => {
        const n = note("¿Por qué liberas la cuenta? (queda en la bitácora)");
        if (n === null) return;
        await api(`/admin/cumplimiento/edad/${c.user_id}/liberar`, jsonOpts("POST", { note: n || null }));
        await loadAge();
      }), "btn-secondary")] : "-",
    ]));
  }

  async function requestCheck() {
    const id = parseInt($("#cons-age-user").value, 10);
    if (!id) return alert("Escribe el ID de la cuenta.");
    const n = note("Motivo de la verificación reforzada (nota interna):");
    if (n === null) return;
    await api(`/admin/cumplimiento/edad/${id}/solicitar`, jsonOpts("POST", { note: n || null }));
    $("#cons-age-status").value = "required";
    await loadAge();
  }

  async function verifyChain() {
    const r = await api("/admin/cumplimiento/aceptaciones/verificar");
    $("#cons-chain-status").textContent = r.ok
      ? `Cadena íntegra: ${r.rows} aceptaciones. Trigger de solo inserción: ${r.append_only_trigger ? "activo" : "NO instalado (falta la migración 0004)"}.`
      : `¡La cadena NO cuadra! Primera fila inválida: #${r.first_invalid_id}. Revisa la base de datos y los respaldos.`;
  }

  async function loadUserRecords() {
    const id = parseInt($("#cons-acc-user").value, 10);
    if (!id) return alert("Escribe el ID de la cuenta.");
    const [acc, cons] = await Promise.all([
      api(`/admin/cumplimiento/aceptaciones?user_id=${id}&limit=200`),
      api(`/admin/cumplimiento/consentimientos?user_id=${id}&limit=200`),
    ]);
    renderTable("cons-acc-table", ["Fecha", "Documento", "Versión", "SHA-256", "Medio", "IP", "Huella de la fila"], acc.map((a) => [
      fmtDate(a.accepted_at), escapeHtml(a.slug), escapeHtml(a.version), `<code>${escapeHtml(a.sha256.slice(0, 16))}…</code>`,
      escapeHtml(METHOD[a.method] || a.method), escapeHtml(a.ip || "-"), `<code>${escapeHtml(a.row_hash.slice(0, 16))}…</code>`,
    ]));
    renderTable("cons-consent-table", ["Fecha", "Permiso", "Decisión", "Texto", "Canal", "IP"], cons.map((c) => [
      fmtDate(c.created_at), escapeHtml(PURPOSE[c.purpose] || c.purpose), c.granted ? "Sí" : "No",
      escapeHtml(c.text_version), escapeHtml(c.channel), escapeHtml(c.ip || "-"),
    ]));
  }

  async function syncDocs() {
    const r = await api("/admin/cumplimiento/documentos/sincronizar", { method: "POST" });
    alert(`Registro de versiones: ${r.created.length} nuevas, ${r.updated.length} actualizadas, ${r.unchanged} sin cambios.`
      + (r.warnings.length ? `\n\nAvisos:\n- ${r.warnings.join("\n- ")}` : ""));
  }

  $("#cons-age-status").addEventListener("change", () => run(loadAge));
  $("#cons-age-request").addEventListener("click", () => run(requestCheck));
  $("#cons-chain-btn").addEventListener("click", () => run(verifyChain));
  $("#cons-acc-btn").addEventListener("click", () => run(loadUserRecords));
  $("#cons-sync-btn").addEventListener("click", () => run(syncDocs));
  if (typeof loaders === "object") loaders.consentimiento = () => loadAge();
})();
