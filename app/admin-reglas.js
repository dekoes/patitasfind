/* ============================================================
   GuauWoow Admin — Reglas de negocio (services/reglas.py)
   - Retenciones: fichas de adopción con cobros, venta o rifas y productos de la lista de prohibidos.
     Liberar publica tal cual (sus palabras quedan aprobadas); rechazar exige un motivo que ve quien publicó.
   - Bonificaciones de 20 % (LFPC art. 92 Ter): seguimiento de lo que el refugio debe pagar al comprador.
   - Alertas de la ley antilavado: acumulado de 6 meses por donante y refugio.
   - Facturas pedidas hace más de 24 h (meta de terminos-tienda 8.2).
   Endpoints: GET/POST /admin/reglas/retenciones, GET/POST /admin/reglas/bonificaciones,
   GET /admin/reglas/alertas-donativos, POST /admin/reglas/alertas-donativos/{id}/revisar,
   GET /admin/reglas/facturas-atrasadas.
   Usa las utilidades globales de admin.js (api, jsonOpts, run, escapeHtml, fmtDate, fmtMoney, el, button,
   renderTable, loaders, $).
   ============================================================ */
"use strict";

(() => {
  const TYPE_ES = { dog: "Perro en adopción", product: "Producto" };
  const HOLD_ES = { liberado: ["liberada", "ok"], rechazado: ["rechazada", "bad"] };
  const BONUS_ES = { pendiente: ["pendiente", "warn"], pagada: ["pagada", "ok"], improcedente: ["no procede", ""] };
  const LEVEL_ES = { aproximacion: ["50 % del umbral", "warn"], identificacion: ["umbral de identificación", "bad"], aviso: ["umbral de aviso", "bad"] };
  const badge = (map, s, fallback) => {
    const [label, cls] = map[s] || [fallback || s, "warn"];
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
  };

  async function loadHolds() {
    const status = $("#reglas-holds-status").value;
    const rows = await api(`/admin/reglas/retenciones?status=${encodeURIComponent(status)}`);
    renderTable("reglas-holds-table", ["Publicación", "Motivo", "Palabras", "Desde", "Quién publicó", "Acciones"], rows.map((r) => {
      const actions = [];
      if (!["liberado", "rechazado"].includes(r.review_hold)) {
        actions.push(button("Liberar", () => run(() => decide(r, "liberar")), "btn-success"));
        actions.push(button("Rechazar", () => run(() => decide(r, "rechazar")), "btn-danger"));
      }
      const link = r.target_type === "dog" ? ` <a href="/app/?dog=${+r.target_id}" target="_blank" rel="noopener">ver</a>` : "";
      return [
        `<b>${escapeHtml(r.title || `#${r.target_id}`)}</b><br><small>${escapeHtml(TYPE_ES[r.target_type] || r.target_type)} #${+r.target_id}${link}</small><br><small>${escapeHtml(r.description || "")}</small>`,
        HOLD_ES[r.review_hold] ? badge(HOLD_ES, r.review_hold) : escapeHtml(r.label || r.review_hold || ""),
        escapeHtml((r.review_terms || []).join(", ")),
        fmtDate(r.since),
        escapeHtml(r.owner ? r.owner.full_name : "-"),
        actions.length ? actions : "-",
      ];
    }));
  }
  async function decide(r, decision) {
    let notas = null;
    if (decision === "rechazar") {
      notas = (prompt("Motivo del rechazo (lo verá quien publicó, mínimo 10 caracteres):") || "").trim();
      if (notas.length < 10) return alert("Escribe un motivo de al menos 10 caracteres.");
    } else if (!confirm(`¿Publicar «${r.title || r.target_id}» tal cual? Sus palabras quedan aprobadas.`)) return;
    await api(`/admin/reglas/retenciones/${r.target_type}/${r.target_id}`, jsonOpts("POST", { decision, notas }));
    await loadHolds();
  }

  async function loadBonuses() {
    const status = $("#reglas-bonus-status").value;
    const rows = await api(`/admin/reglas/bonificaciones?status=${encodeURIComponent(status)}`);
    renderTable("reglas-bonus-table", ["Pedido", "Refugio", "Monto", "Vence", "Estado", "Referencia / nota", "Acciones"], rows.map((b) => {
      const actions = [];
      if (b.status === "pendiente") {
        actions.push(button("Marcar pagada", () => run(() => resolveBonus(b, "marcar_pagada")), "btn-success"));
        actions.push(button("No procede", () => run(() => resolveBonus(b, "improcedente")), "btn-secondary"));
      } else {
        actions.push(button("Reabrir", () => run(() => resolveBonus(b, "reabrir")), "btn-secondary"));
      }
      return [
        `#${+b.order_id}`, escapeHtml(b.refuge_name || `#${b.refuge_id}`),
        `${fmtMoney(b.amount)}<br><small>${escapeHtml(String(b.percent))} % de ${fmtMoney(b.base_amount)}</small>`,
        `${fmtDate(b.due_at)}${b.overdue ? ' <span class="badge bad">vencida</span>' : ""}`,
        badge(BONUS_ES, b.status), escapeHtml([b.payment_reference, b.note].filter(Boolean).join(" · ") || "-"), actions,
      ];
    }));
  }
  async function resolveBonus(b, accion) {
    const body = { accion, referencia: null, nota: null };
    if (accion === "marcar_pagada") {
      body.referencia = (prompt("Referencia del pago (transferencia o reembolso en Mercado Pago):") || "").trim();
      if (body.referencia.length < 4) return alert("Escribe la referencia del pago.");
    } else if (accion === "improcedente") {
      body.nota = (prompt("¿Por qué no procede? (evidencia; la verá el comprador, mínimo 10 caracteres)") || "").trim();
      if (body.nota.length < 10) return alert("Escribe la evidencia (mínimo 10 caracteres).");
    } else if (!confirm("¿Reabrir esta bonificación como pendiente?")) return;
    await api(`/admin/reglas/bonificaciones/${b.id}`, jsonOpts("POST", body));
    await loadBonuses();
  }

  async function loadAml() {
    const rows = await api("/admin/reglas/alertas-donativos?pendientes=true");
    renderTable("reglas-aml-table", ["Fecha", "Donante", "Refugio", "Acumulado 6 meses", "Nivel", "Donativos", "Acciones"], rows.map((f) => [
      fmtDate(f.created_at),
      escapeHtml(f.user ? `${f.user.full_name} (${f.user.email})` : `#${f.user_id}`),
      escapeHtml(f.refuge ? f.refuge.name : "-"),
      `${fmtMoney(f.total)}<br><small>umbral ${fmtMoney(f.threshold)}</small>`,
      badge(LEVEL_ES, f.level),
      escapeHtml((f.donation_ids || []).map((i) => `#${i}`).join(", ")),
      [button("Marcar revisada", () => run(async () => {
        const nota = (prompt("Nota de la revisión (opcional):") || "").trim() || null;
        await api(`/admin/reglas/alertas-donativos/${f.id}/revisar`, jsonOpts("POST", { nota }));
        await loadAml();
      }), "btn-secondary")],
    ]));
  }

  async function loadInvoices() {
    const rows = await api("/admin/reglas/facturas-atrasadas");
    renderTable("reglas-invoices-table", ["Pedido", "Refugio", "Pedida", "Horas", "Recordatorio", "Aviso al equipo"], rows.map((i) => [
      `#${+i.order_id}`, escapeHtml(i.refuge_name || "-"), fmtDate(i.requested_at), escapeHtml(String(i.hours)),
      fmtDate(i.reminded_at), fmtDate(i.escalated_at),
    ]));
  }

  async function loadAll() {
    await Promise.all([loadHolds(), loadBonuses(), loadAml(), loadInvoices()]);
  }

  $("#reglas-holds-btn").addEventListener("click", () => run(loadHolds));
  $("#reglas-bonus-btn").addEventListener("click", () => run(loadBonuses));
  loaders.reglas = () => loadAll();
  window.AdminReglas = { loadAll, loadHolds, loadBonuses, loadAml, loadInvoices };
})();
