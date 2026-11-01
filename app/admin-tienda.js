/* ============================================================
   GuauWoow Admin — Tienda (S3, S5, S6)
   - Pedidos: filtros (estado, refugio, cliente/ID), detalle con línea de tiempo,
     revisión de pagos (monto distinto / reembolso pendiente) y reembolso en Mercado Pago.
   - CFDI de la plataforma (comisión e impuestos retenidos): lista por periodo y estado,
     reintento con el PAC y descarga de XML/PDF (con el token en la cabecera, nunca en la URL).
   - Estados de cuenta: totales de la plataforma y de cada refugio por mes, con la comisión vigente.
   Endpoints: GET /admin/orders?status&refuge_id&skip&limit, POST /admin/orders/{id}/refund {amount?, item_ids?},
   POST /admin/orders/{id}/resolve, GET /admin/cfdi?period&status, POST /admin/cfdi/{id}/retry,
   GET /admin/cfdi/{id}/{xml|pdf}, GET /admin/statements?period.
   Se carga después de admin.js y usa sus utilidades globales
   (api, jsonOpts, run, escapeHtml, fmtDate, fmtMoney, el, button, renderTable, renderPagination,
   openModal, resolveButtons, STATUS_ES, loaders, currentToken, API_BASE, logout, $).
   ============================================================ */
"use strict";

(() => {
  const PAGE = 50;
  /* Estados de un pedido (S3): [etiqueta, clase del badge] */
  const ORDER_STATUS = {
    pending_payment: ["pago pendiente", "warn"], paid: ["pagado", "ok"], preparing: ["preparando", "warn"], shipped: ["enviado", "ok"],
    delivered: ["entregado", "ok"], completed: ["completado", "ok"], cancelled: ["cancelado", "bad"], expired: ["expirado", ""],
    return_requested: ["devolución solicitada", "warn"], return_approved: ["devolución aprobada", "warn"],
    return_rejected: ["devolución rechazada", "bad"], refunded: ["reembolsado", "bad"], refund_pending: ["reembolso pendiente", "bad"],
    amount_mismatch: ["monto distinto", "bad"], created: ["creado", ""], partial_refund: ["reembolso parcial", "warn"],
  };
  Object.entries(ORDER_STATUS).forEach(([k, [label]]) => { if (!(k in STATUS_ES)) STATUS_ES[k] = label; });
  const CFDI_STATUS = { pending_pac: ["pendiente de PAC", "warn"], issued: ["emitido", "ok"], error: ["error", "bad"] };
  const CFDI_KIND = { comision: "Comisión (ingreso)", retencion: "Retenciones" };
  // Se puede reembolsar (total o en parciales) un pedido cobrado que no se haya reembolsado completo; también una
  // devolución rechazada (p. ej. si PROFECO da la razón al comprador). Mismo criterio que order_flow.ADMIN_REFUNDABLE.
  const REFUNDABLE = ["paid", "preparing", "shipped", "delivered", "completed", "return_requested", "return_approved", "return_rejected", "refund_pending", "amount_mismatch"];
  // Cancelación por el equipo antes del envío, solo con causa objetiva registrada (consumidor-ecommerce-14)
  const CANCELLABLE = ["pending_payment", "paid", "preparing"];
  const CANCEL_REASONS = { sin_inventario: "Se agotó el producto", no_puedo_enviar: "No es posible enviarlo", direccion_invalida: "Dirección inválida o sin cobertura", sospecha_fraude: "Posible fraude en el pago", otro: "Otro motivo" };
  const CANCEL_REASON_ES = { buyer: "el comprador", payment_expired: "pago no completado a tiempo", checkout_failed: "no se pudo crear el pago", dispatch_timeout: "el refugio no lo envió a tiempo", refuge: "el refugio", admin: "el equipo" };
  const RETURN_REASON_ES = { defectuoso: "llegó dañado o defectuoso", no_corresponde: "no corresponde a lo que se pidió", no_llego: "no llegó", arrepentimiento: "cambio de opinión (revocación)", otro: "otro motivo" };
  const GENERATE_ES = { period: "Periodo", created: "CFDI creados o actualizados", issued: "Timbrados", pending_pac: "Pendientes de PAC", errors: "Con error", credit_notes_needed: "Requieren CFDI de egreso" };
  const st = { status: "", refuge: "", q: "", page: 0, cfdiPeriod: "", cfdiStatus: "", stmtPeriod: "" };

  const badge = (map, s) => {
    const [label, cls] = map[s] || [s, ""];
    return `<span class="badge ${cls}" title="${escapeHtml(s)}">${escapeHtml(label)}</span>`;
  };
  const isNotReady = (e) => e && e.status === 404 && e.message === "Not Found";
  const money = (n) => (n == null || n === "" ? "-" : fmtMoney(n));

  function periods(n = 24) {
    const out = []; const d = new Date(); d.setDate(1);
    for (let i = 0; i < n; i++) {
      out.push([`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`, d.toLocaleDateString("es-MX", { month: "long", year: "numeric" })]);
      d.setMonth(d.getMonth() - 1);
    }
    return out;
  }
  function fillPeriods(sel, withAll) {
    const s = $(sel);
    if (!s || s.options.length) return;
    if (withAll) s.append(el("option", { value: "", text: "Todos los periodos" }));
    periods().forEach(([v, label]) => s.append(el("option", { value: v, text: label })));
  }
  /* Muestra un aviso en la tabla cuando el backend aún no tiene el endpoint */
  function pending(containerId, text) {
    const c = $(`#${containerId}`);
    if (c) c.innerHTML = `<p class="empty">${escapeHtml(text)}</p>`;
  }

  /* Descarga privada con Authorization (XML/PDF de CFDI) */
  async function download(path, filename) {
    const res = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${currentToken}` } });
    if (res.status === 401) { logout("Tu sesión expiró. Inicia sesión de nuevo."); throw Object.assign(new Error(""), { silent: true }); }
    if (!res.ok) throw new Error(res.status === 404 ? "El archivo todavía no está disponible." : `No se pudo descargar (error ${res.status}).`);
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: filename });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  /* ------------------------------------------------------------------ pedidos */
  function addressOf(o) {
    if (o.shipping_street) {
      return [`${o.shipping_street} ${o.shipping_ext_number || ""}${o.shipping_int_number ? ` int. ${o.shipping_int_number}` : ""}`.trim(),
        o.shipping_neighborhood, [o.shipping_postal_code, o.shipping_city].filter(Boolean).join(" "), o.shipping_state].filter(Boolean).join(", ");
    }
    return o.shipping_address || "-";
  }
  function timelineHtml(o) {
    const tl = Array.isArray(o.timeline) ? o.timeline : [];
    if (!tl.length) return "<p class='hint'>El backend todavía no envía la línea de tiempo de este pedido.</p>";
    return `<ol class="timeline">${tl.map((t) => `<li><strong>${escapeHtml(STATUS_ES[t.status] || t.status)}</strong> · ${fmtDate(t.at || t.created_at)}${t.note ? `<br><small>${escapeHtml(t.note)}</small>` : ""}</li>`).join("")}</ol>`;
  }
  function openOrderDetail(o) {
    const items = (o.items || []).map((i) => `<li>${i.quantity} × ${escapeHtml(i.product_name || i.product?.name || i.product_id)} — ${fmtMoney(i.unit_price)}</li>`).join("");
    openModal(`<h3>Pedido #${o.id} ${badge(ORDER_STATUS, o.status)}</h3>
      <p><strong>Cliente:</strong> ${escapeHtml(o.user?.full_name || o.user_id)} · <strong>Refugio:</strong> ${escapeHtml(o.refuge_name || o.refuge_id || "-")}</p>
      <ul>${items}</ul>
      <p>Subtotal ${money(o.subtotal)} · Envío ${money(o.shipping_total)} · <strong>Total ${fmtMoney(o.total)}</strong><br>
      Comisión plataforma ${money(o.fee_amount)} · Neto refugio ${money(o.net_amount)}</p>
      <p><strong>Envío a:</strong> ${escapeHtml(o.shipping_name || "")} ${escapeHtml(o.shipping_phone || "")}<br>${escapeHtml(addressOf(o))}${o.shipping_references ? `<br><small>${escapeHtml(o.shipping_references)}</small>` : ""}</p>
      ${o.tracking_number ? `<p><strong>Guía:</strong> ${escapeHtml(o.carrier || "")} ${escapeHtml(o.tracking_number)}</p>` : ""}
      ${o.return_reason ? `<p><strong>Devolución:</strong> ${escapeHtml(RETURN_REASON_ES[o.return_reason] || o.return_reason)}${o.return_details ? ` — ${escapeHtml(o.return_details)}` : ""}${o.return_decision_note ? `<br><small>Respuesta del refugio: ${escapeHtml(o.return_decision_note)}</small>` : ""}</p>` : ""}
      ${o.refund_id || o.refund_amount != null ? `<p><strong>Reembolsado:</strong> ${money(o.refund_amount)} de ${fmtMoney(o.paid_amount || o.total)} · ${escapeHtml(o.refund_status || "-")} · MP ${escapeHtml(o.refund_id || "-")}</p>` : ""}
      ${o.status === "cancelled" && o.cancel_reason ? `<p><strong>Cancelado por:</strong> ${escapeHtml(CANCEL_REASON_ES[o.cancel_reason] || o.cancel_reason)}${o.cancel_note ? ` — ${escapeHtml(o.cancel_note)}` : ""}</p>` : ""}
      ${o.terms_accepted_at ? `<p><small>Aceptó las condiciones v${escapeHtml(o.terms_version || "-")} el ${fmtDate(o.terms_accepted_at)} desde ${escapeHtml(o.terms_ip || "-")} · hash ${escapeHtml((o.terms_hash || "").slice(0, 12))}…</small></p>` : ""}
      ${o.review_note ? `<p class="hint">${escapeHtml(o.review_note)}</p>` : ""}
      <h4>Línea de tiempo</h4>${timelineHtml(o)}`);
  }
  function refundButton(o) {
    if (!REFUNDABLE.includes(o.status) || o.status === "refunded") return null;
    const charged = Number(o.paid_amount || o.total);
    const remaining = Math.round((charged - Number(o.refund_amount || 0)) * 100) / 100;
    if (!(remaining > 0)) return null;
    return button("Reembolsar", () => run(async () => {
      const already = Number(o.refund_amount || 0) > 0 ? `\nYa se reembolsaron ${fmtMoney(o.refund_amount)}.` : "";
      const raw = prompt(`Reembolso del pedido #${o.id} (cobrado ${fmtMoney(charged)}).${already}\nQuedan ${fmtMoney(remaining)} por reembolsar.\nMonto en MXN (vacío = todo lo que queda; un monto menor es un reembolso parcial y el pedido sigue su curso):`, "");
      if (raw === null) return;
      const body = {};
      if (raw.trim()) {
        const amount = Number(raw.replace(/[$,\s]/g, ""));
        if (!(amount > 0) || amount > remaining) { alert(`Escribe un monto mayor a 0 y no mayor a ${fmtMoney(remaining)}.`); return; }
        body.amount = Math.round(amount * 100) / 100;
      }
      // Reclamación por defecto o porque no corresponde: la bonificación de 20 % se calcula sobre las partidas
      // reclamadas (nunca sobre el envío). Con un reembolso parcial se pregunta cuáles son.
      const items = o.items || [];
      if (body.amount && ["defectuoso", "no_corresponde"].includes(o.return_reason) && items.length > 1) {
        const list = items.map((i, n) => `${n + 1}) ${i.quantity} × ${i.product_name || i.product?.name || i.product_id} — ${fmtMoney(i.unit_price)}`).join("\n");
        const picked = prompt(`¿Qué partidas se reembolsan por la reclamación? (números separados por coma; vacío = no especificar)\n${list}`, "");
        if (picked === null) return;
        const ids = picked.split(/[,\s]+/).filter(Boolean).map((x) => items[Number(x) - 1]).filter(Boolean).map((i) => i.id);
        if (ids.length) body.item_ids = ids;
      }
      if (!confirm(`¿Reembolsar ${body.amount ? fmtMoney(body.amount) : fmtMoney(remaining)} en Mercado Pago? No se puede deshacer.`)) return;
      try {
        const r = await api(`/admin/orders/${o.id}/refund`, jsonOpts("POST", body));
        alert(`Reembolso registrado${r && r.refund_status ? ` (${r.refund_status})` : ""}.`);
      } catch (err) {
        if (isNotReady(err)) throw new Error("El reembolso desde el panel estará disponible cuando el backend lo publique.");
        throw err;
      }
      loadOrders();
    }), "btn-danger");
  }
  function cancelButton(o) {
    if (!CANCELLABLE.includes(o.status)) return null;
    return button("Cancelar", () => run(async () => {
      const keys = Object.keys(CANCEL_REASONS);
      const pick = prompt(`Cancelar el pedido #${o.id}${["paid", "preparing"].includes(o.status) ? " (se reembolsa el total al comprador)" : ""}.\nMotivo (número):\n${keys.map((k, i) => `${i + 1}. ${CANCEL_REASONS[k]}`).join("\n")}`, "");
      if (pick === null) return;
      const reason = keys[Number(pick) - 1];
      if (!reason) { alert("Elige un número de la lista."); return; }
      const note = (prompt("Explica la causa (mínimo 10 caracteres; la verá el comprador y queda registrada):", "") || "").trim();
      if (note.length < 10) { alert("La explicación debe tener al menos 10 caracteres."); return; }
      await api(`/admin/orders/${o.id}/cancel`, jsonOpts("POST", { reason, note }));
      alert("Pedido cancelado.");
      loadOrders();
    }), "btn-secondary");
  }
  async function loadOrders() {
    const params = new URLSearchParams({ limit: PAGE, skip: st.page * PAGE });
    if (st.status) params.set("status", st.status);
    if (st.refuge) params.set("refuge_id", st.refuge);
    let orders = await api(`/admin/orders?${params}`);
    const q = st.q.toLowerCase();
    if (q) orders = orders.filter((o) => String(o.id) === q || (o.user?.full_name || "").toLowerCase().includes(q) || (o.user?.email || "").toLowerCase().includes(q) || (o.provider_payment_id || "").includes(q));
    const rows = orders.map((o) => {
      const actions = [button("Ver", () => openOrderDetail(o), "btn-secondary")];
      const review = resolveButtons("orders", o, () => run(loadOrders));
      if (Array.isArray(review)) actions.push(...review);
      else { const r = refundButton(o); if (r) actions.push(r); }
      const c = cancelButton(o); if (c) actions.push(c);
      return [
        o.id, escapeHtml(o.user?.full_name || o.user_id), escapeHtml(o.refuge_name || o.refuge_id || "-"),
        (o.items || []).map((i) => `${i.quantity} × ${escapeHtml(i.product_name || i.product?.name || i.product_id)}`).join("<br>"),
        `${fmtMoney(o.total)}${o.shipping_total != null ? `<br><small>envío ${money(o.shipping_total)}</small>` : ""}`,
        o.fee_amount != null ? `${money(o.fee_amount)}<br><small>neto ${money(o.net_amount)}</small>` : "-",
        badge(ORDER_STATUS, o.status) + (o.review_note ? `<br><small>${escapeHtml(o.review_note)}</small>` : ""),
        escapeHtml(o.provider_payment_id || "-"),
        escapeHtml(addressOf(o)) + (o.tracking_number ? `<br><small>${escapeHtml(o.carrier || "")} · guía ${escapeHtml(o.tracking_number)}</small>` : ""),
        fmtDate(o.paid_at), fmtDate(o.created_at), actions,
      ];
    });
    renderTable("orders-table", ["ID", "Cliente", "Refugio", "Productos", "Total", "Comisión", "Estado", "ID de pago", "Envío", "Pagado", "Creado", "Acciones"], rows);
    renderPagination("orders-pagination", st.page, orders.length === PAGE && !q, (p) => { st.page = Math.max(0, p); run(loadOrders); });
  }

  /* ------------------------------------------------------------------ CFDI de la plataforma */
  async function loadCfdi() {
    fillPeriods("#cfdi-filter-period", true);
    const params = new URLSearchParams();
    if (st.cfdiPeriod) params.set("period", st.cfdiPeriod);
    if (st.cfdiStatus) params.set("status", st.cfdiStatus);
    let rows;
    try { rows = await api(`/admin/cfdi?${params}`); }
    catch (err) {
      if (isNotReady(err)) return pending("cfdi-table", "La facturación (CFDI) estará disponible cuando el backend la publique.");
      throw err;
    }
    rows = Array.isArray(rows) ? rows : rows?.items || [];
    const pendingPac = rows.filter((c) => c.status === "pending_pac").length;
    $("#cfdi-summary").innerHTML = `
      <div class="mini-stat"><span>CFDI en la lista</span><strong>${rows.length}</strong></div>
      <div class="mini-stat"><span>Pendientes de PAC</span><strong>${pendingPac}</strong></div>
      <div class="mini-stat"><span>Con error</span><strong>${rows.filter((c) => c.status === "error").length}</strong></div>`;
    renderTable("cfdi-table", ["ID", "Periodo", "Refugio", "Tipo", "Estado", "Subtotal", "IVA", "ISR ret.", "IVA ret.", "Total", "UUID", "Creado", "Acciones"], rows.map((c) => {
      const actions = [];
      if (c.status !== "issued") {
        actions.push(button("Reintentar", () => run(async () => {
          const r = await api(`/admin/cfdi/${c.id}/retry`, { method: "POST" });
          if (r && r.status !== "issued" && r.error) alert(r.error);
          loadCfdi();
        }), "btn-secondary"));
      }
      const name = `cfdi-${c.kind || "comision"}-${c.period}-${c.refuge_id || c.id}`;
      if (c.has_xml ?? c.status === "issued") actions.push(button("XML", () => run(() => download(`/admin/cfdi/${c.id}/xml`, `${name}.xml`))));
      if (c.has_pdf ?? c.status === "issued") actions.push(button("PDF", () => run(() => download(`/admin/cfdi/${c.id}/pdf`, `${name}.pdf`))));
      return [
        c.id, escapeHtml(c.period || "-"), escapeHtml(c.refuge_name || c.refuge_id || "-"), escapeHtml(CFDI_KIND[c.kind] || c.kind || "-"),
        badge(CFDI_STATUS, c.status) + (c.attempts ? `<br><small>${c.attempts} intento(s)</small>` : "") + (c.error ? `<br><small>${escapeHtml(c.error)}</small>` : ""),
        money(c.subtotal), money(c.iva), money(c.isr_retenido), money(c.iva_retenido), money(c.total),
        c.uuid ? `<small>${escapeHtml(c.uuid)}</small>` : "-", fmtDate(c.created_at), actions,
      ];
    }));
  }

  /* ------------------------------------------------------------------ estados de cuenta */
  async function loadStatements() {
    fillPeriods("#statements-filter-period", false);
    if (!st.stmtPeriod) st.stmtPeriod = $("#statements-filter-period").value;
    $("#statements-filter-period").value = st.stmtPeriod;
    let data;
    try { data = await api(`/admin/statements?period=${encodeURIComponent(st.stmtPeriod)}`); }
    catch (err) {
      if (isNotReady(err)) {
        $("#statements-summary").innerHTML = "";
        return pending("statements-table", "Los estados de cuenta estarán disponibles cuando el backend los publique.");
      }
      throw err;
    }
    const refuges = Array.isArray(data) ? data : data.refuges || data.rows || data.items || [];
    const sum = (k) => refuges.reduce((s, r) => s + Number(r[k] || 0), 0);
    const t = (!Array.isArray(data) && (data.totals || data.platform)) || {
      orders_count: sum("orders_count"), gross: sum("gross"), shipping: sum("shipping"), platform_fee: sum("platform_fee"), fee_iva: sum("fee_iva"),
      isr_retenido: sum("isr_retenido"), iva_retenido: sum("iva_retenido"), net_received: sum("net_received"), donations_gross: sum("donations_gross"), donations_fee: sum("donations_fee"),
    };
    const fee = !Array.isArray(data) ? data.fee_percent : null;
    const dfee = !Array.isArray(data) ? data.donation_fee_percent : null;
    const effective = Number(t.gross) > 0 ? ((Number(t.platform_fee) / Number(t.gross)) * 100).toFixed(1) : null;
    $("#statements-summary").innerHTML = `
      <div class="mini-stat"><span>Pedidos pagados</span><strong>${Number(t.orders_count || 0)}</strong></div>
      <div class="mini-stat"><span>Ventas brutas</span><strong>${fmtMoney(t.gross)}</strong></div>
      <div class="mini-stat"><span>Comisión plataforma${fee != null ? ` (${escapeHtml(String(fee))} %)` : effective ? ` (efectiva ${effective} %)` : ""}</span><strong>${fmtMoney(t.platform_fee)}</strong></div>
      <div class="mini-stat"><span>IVA de comisiones</span><strong>${fmtMoney(t.fee_iva)}</strong></div>
      <div class="mini-stat"><span>ISR / IVA retenidos</span><strong>${fmtMoney(t.isr_retenido)} / ${fmtMoney(t.iva_retenido)}</strong></div>
      <div class="mini-stat"><span>Neto a refugios</span><strong>${fmtMoney(t.net_received)}</strong></div>
      ${t.platform_income != null ? `<div class="mini-stat"><span>Ingreso de la plataforma (comisiones)</span><strong>${fmtMoney(t.platform_income)}</strong></div>` : ""}
      ${t.retentions_to_pay != null ? `<div class="mini-stat"><span>Retenciones por enterar al SAT (día 17)</span><strong>${fmtMoney(t.retentions_to_pay)}</strong></div>` : ""}
      ${Number(t.refunds_count) ? `<div class="mini-stat"><span>Reembolsos del mes (${Number(t.refunds_count)})</span><strong>${fmtMoney(t.refunds_total)}</strong></div>` : ""}
      <div class="mini-stat"><span>Donativos${dfee != null ? ` (comisión ${escapeHtml(String(dfee))} %)` : ""}</span><strong>${fmtMoney(t.donations_gross)}</strong></div>`;
    // Ventas = cobradas en el mes (envío incluido); reembolsos = los hechos en el mes (restan comisión y retenciones en proporción)
    renderTable("statements-table", ["Refugio", "Pedidos", "Ventas (incl. envío)", "Envíos", "Comisión (IVA incl.)", "IVA comisión", "ISR ret.", "IVA ret.", "Neto recibido", "Reembolsos del mes", "Donativos", "Comisión donativos"], refuges.map((r) => [
      `${escapeHtml(r.refuge_name || r.name || `#${r.refuge_id}`)}<br><small>ID ${escapeHtml(r.refuge_id)}</small>`, Number(r.orders_count || 0), fmtMoney(r.gross), fmtMoney(r.shipping), fmtMoney(r.platform_fee),
      fmtMoney(r.fee_iva), fmtMoney(r.isr_retenido), fmtMoney(r.iva_retenido), fmtMoney(r.net_received),
      Number(r.refunds_count) ? `${fmtMoney(r.refunds_total)}<br><small>${Number(r.refunds_count)} pedido(s)</small>` : "-",
      fmtMoney(r.donations_gross) + (Number(r.donations_via_platform) ? `<br><small>${fmtMoney(r.donations_via_platform)} por la cuenta de la plataforma</small>` : ""), fmtMoney(r.donations_fee),
    ]));
  }

  /* ------------------------------------------------------------------ eventos */
  loaders.orders = () => loadOrders();
  loaders.cfdi = () => loadCfdi();
  loaders.statements = () => loadStatements();
  const on = (sel, ev, fn) => { const n = $(sel); if (n) n.addEventListener(ev, fn); };
  on("#orders-filter-btn", "click", () => {
    st.status = $("#orders-filter-status").value;
    st.refuge = ($("#orders-filter-refuge").value || "").replace(/\D/g, "");
    st.q = ($("#orders-filter-q").value || "").trim().slice(0, 100);
    st.page = 0;
    run(loadOrders);
  });
  on("#orders-filter-q", "keydown", (e) => { if (e.key === "Enter") $("#orders-filter-btn").click(); });
  on("#cfdi-filter-btn", "click", () => { st.cfdiPeriod = $("#cfdi-filter-period").value; st.cfdiStatus = $("#cfdi-filter-status").value; run(loadCfdi); });
  // Genera ya los CFDI de un periodo (por defecto el mes anterior); la tarea del día 3 hace lo mismo
  on("#cfdi-generate-btn", "click", () => run(async () => {
    const period = $("#cfdi-filter-period").value || periods(2)[1][0];
    if (!confirm(`¿Generar los CFDI de comisión y retenciones de ${period}? Los que ya existan no se duplican.`)) return;
    let r;
    try { r = await api(`/admin/cfdi/generate?period=${encodeURIComponent(period)}`, { method: "POST" }); }
    catch (err) { if (isNotReady(err)) throw new Error("La generación de CFDI estará disponible cuando el backend la publique."); throw err; }
    const summary = Object.entries(r || {}).map(([k, v]) => `${GENERATE_ES[k] || k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("\n");
    alert(`Listo.\n${summary || "Sin cambios"}`);
    st.cfdiPeriod = period; $("#cfdi-filter-period").value = period;
    loadCfdi();
  }));
  on("#statements-filter-period", "change", (e) => { st.stmtPeriod = e.target.value; run(loadStatements); });

  window.AdminTienda = { loadOrders, loadCfdi, loadStatements };
})();
