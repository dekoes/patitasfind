/* ============================================================
   GuauWoow Admin — Centro de solicitudes (contrato K-SOLIC)
   Cola de derechos ARCO, revocaciones, limitaciones, quejas, aclaraciones y retiros de publicaciones
   importadas, con semáforo de plazos (rojo vencida, amarillo vence en 2 días hábiles o 24 h, verde, azul esperando
   a la persona, gris sin plazo). Detalle con historial, plantillas de respuesta y acciones; todo queda en la
   bitácora (record_admin_action).
   Endpoints: GET /admin/cumplimiento/solicitudes?estado&tipo&q&skip&limit, GET .../resumen,
   GET .../{folio}, POST .../{folio}/acciones {accion, mensaje, nota_interna, resultado, motivo_negativa,
   pedir_identificacion, metodo, eliminar_cuenta, eliminar_whatsapp}, GET .../{folio}/identificacion,
   POST /admin/cumplimiento/solicitudes (registrar una que llegó por correo, escrito, teléfono o WhatsApp).
   Se carga después de admin.js y usa sus utilidades globales
   (api, jsonOpts, run, escapeHtml, fmtDate, el, button, renderTable, renderPagination, loaders, modal,
   currentToken, API_BASE, logout, $).
   ============================================================ */
"use strict";

(() => {
  const BASE = "/admin/cumplimiento/solicitudes";
  const LIMIT = 50;
  const st = { estado: "abiertas", tipo: "", q: "", page: 0 };
  const SLA = { rojo: ["Vencida", "bad"], amarillo: ["Por vencer", "warn"], verde: ["En plazo", "ok"], azul: ["Esperando a la persona", "info"], gris: ["Sin plazo", ""] };
  const ESTADOS = { recibida: "warn", en_revision: "info", respondida: "info", efectiva: "ok", cerrada: "" };
  const ACCIONES = {
    en_revision: "Tomarla (en revisión)", primera_respuesta: "Primera respuesta", requerir_info: "Pedir información (una vez)",
    verificar_identidad: "Identidad comprobada", ampliar: "Ampliar el plazo (una vez)", responder: "Responder",
    hacer_efectiva: "Hacerla efectiva", cerrar: "Cerrar", nota: "Nota interna",
  };
  const RESULTADOS = { procede: "Procede", procede_parcial: "Procede en parte", no_procede: "No procede", sin_datos: "No encontramos datos" };
  const NEGATIVAS = {
    identidad_no_acreditada: "No se acreditó la identidad o la representación", sin_datos: "No tenemos los datos",
    derechos_de_terceros: "Se afectarían derechos de otra persona", impedimento_legal: "Una ley o autoridad lo impide",
    ya_realizada: "Ya se había hecho", obligacion_legal: "Obligación legal de conservar (art. 25)",
    informacion_incompleta: "No entregó la información pedida", otro: "Otro motivo",
  };
  const TIPOS = {
    arco: "Derechos ARCO (todos)", acceso: "Acceso", rectificacion: "Rectificación", cancelacion: "Cancelación",
    oposicion: "Oposición", revocacion: "Revocación del consentimiento", limitacion: "Limitación del uso o divulgación",
    queja: "Queja", aclaracion: "Duda o aclaración", retiro_importado: "Retiro de una publicación importada",
  };
  const opt = (map, sel = "") => Object.entries(map).map(([k, v]) => `<option value="${escapeHtml(k)}"${k === sel ? " selected" : ""}>${escapeHtml(v)}</option>`).join("");
  const badge = (label, cls) => `<span class="badge ${cls}">${escapeHtml(label)}</span>`;

  function slaBadge(s) {
    const [label, cls] = SLA[s.color] || [s.color, ""];
    const when = s.vence ? `<div class="hint">${escapeHtml(s.etapa || "")}: ${escapeHtml(fmtDate(s.vence))}${s.vencida ? " (vencida)" : s.dias_habiles_restantes != null && s.color !== "azul" ? ` (${s.dias_habiles_restantes} días hábiles)` : ""}</div>` : "";
    return badge(label, cls) + when;
  }

  async function loadSummary() {
    const box = $("#sol-summary");
    if (!box) return;
    try {
      const s = await api(`${BASE}/resumen`);
      box.innerHTML = `<div class="mini-stat"><span>Abiertas</span><strong>${s.abiertas}</strong></div>
        <div class="mini-stat"><span>Vencidas</span><strong>${s.vencidas}</strong></div>
        <div class="mini-stat"><span>Vencen en 2 días hábiles</span><strong>${s.por_vencer}</strong></div>
        <div class="mini-stat"><span>Esperando a la persona</span><strong>${s.semaforo.azul}</strong></div>`;
      const nav = document.querySelector('.nav-btn[data-section="solicitudes"]');
      if (nav) nav.textContent = s.vencidas ? `Solicitudes (${s.vencidas} vencidas)` : "Solicitudes";
    } catch { box.innerHTML = ""; }
  }

  async function loadList() {
    const q = new URLSearchParams({ estado: st.estado, skip: String(st.page * LIMIT), limit: String(LIMIT) });
    if (st.tipo) q.set("tipo", st.tipo);
    if (st.q) q.set("q", st.q);
    const data = await api(`${BASE}?${q}`);
    renderTable("sol-table", ["Folio", "Tipo", "Estado", "Plazo", "Persona", "Identidad", ""], data.items.map((r) => [
      `<strong>${escapeHtml(r.folio)}</strong><div class="hint">${escapeHtml(fmtDate(r.recibida_en))} · ${escapeHtml(r.canal)}</div>`,
      escapeHtml(r.tipo_texto),
      badge(r.estado_texto, ESTADOS[r.estado] || "") + (r.resultado ? `<div class="hint">${escapeHtml(RESULTADOS[r.resultado] || r.resultado)}</div>` : ""),
      slaBadge(r.sla),
      `${escapeHtml(r.nombre)}<div class="hint">${escapeHtml(r.email || r.telefono || "-")}${r.con_cuenta ? " · con cuenta" : ""}</div>`,
      r.identidad_confirmada ? badge("Comprobada", "ok") : badge("Sin comprobar", "warn"),
      [button("Abrir", () => run(() => openDetail(r.folio)))],
    ]));
    renderPagination("sol-pagination", st.page, data.has_more, (p) => { st.page = p; run(loadList); });
  }

  /* ---------------------------------------------------------------- detalle */
  async function openDetail(folio) {
    const d = await api(`${BASE}/${encodeURIComponent(folio)}`);
    renderDetail(d);
  }

  function kv(rows) {
    return `<dl style="display:grid;grid-template-columns:minmax(120px,30%) 1fr;gap:4px 12px">${rows.filter(([, v]) => v != null && v !== "").map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
  }

  function renderDetail(d) {
    const body = $("#modal-body");
    const det = d.detalles || {};
    const extra = [];
    if (det.permisos) extra.push(["Permisos", escapeHtml(det.permisos.join(", "))]);
    if (det.alcance) extra.push(["Qué borrar", escapeHtml(det.alcance)]);
    if (det.publicidad) extra.push(["Acceso", "Incluye la información usada para publicidad (LFPC art. 16: el plazo menor)"]);
    if (det.motivo) extra.push(["Tema", escapeHtml(det.motivo)]);
    if (det.relacion) extra.push(["Relación con la publicación", escapeHtml(det.relacion)]);
    if (det.enlace) extra.push(["Enlace", link(det.enlace, det.enlace)]);
    if (det.pedido) extra.push(["Pedido (sin verificar)", escapeHtml(det.pedido)]);
    const idDoc = d.identificacion || {};
    const history = d.historial.map((h) => `<li><strong>${escapeHtml(h.texto)}</strong> · ${escapeHtml(fmtDate(h.fecha))}${h.por ? ` · ${escapeHtml(h.por)}` : ""}
        ${h.nota_publica ? `<div class="hint" style="white-space:pre-line">${escapeHtml(h.nota_publica)}</div>` : ""}${h.nota_interna ? `<div class="hint" style="white-space:pre-line;font-style:italic">Interna: ${escapeHtml(h.nota_interna)}</div>` : ""}</li>`).join("");
    body.innerHTML = `
      <h3>Solicitud ${escapeHtml(d.folio)} · ${escapeHtml(d.tipo_texto)}</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">${badge(d.estado_texto, ESTADOS[d.estado] || "")} ${slaBadge(d.sla)}</div>
      ${kv([
        ["Persona", `${escapeHtml(d.nombre)}${d.actua_como === "representante" ? ` (representa a ${escapeHtml(d.nombre_titular || "-")})` : ""}`],
        ["Correo", escapeHtml(d.email || "-")], ["Teléfono", d.telefono ? `${escapeHtml(d.telefono)}${d.telefono_comprobado ? " · comprobado" : " · sin comprobar: para borrar o dar de baja WhatsApp pídele ELIMINAR o BAJA al bot desde ese número"}` : ""], ["Canal", escapeHtml(d.canal)],
        ["Cuenta", d.cuenta ? `#${d.cuenta.id} ${escapeHtml(d.cuenta.nombre)} (${escapeHtml(d.cuenta.email)})${d.cuenta.activa ? "" : " · inactiva"}${d.cuenta.correo_verificado ? " · correo verificado" : ""}` : "Sin cuenta ligada"],
        ["Identidad", d.identidad_confirmada ? `Comprobada (${escapeHtml(d.metodo_identidad || "")}) el ${escapeHtml(fmtDate(d.identidad_en))}` : "Sin comprobar"],
        ["Identificación", idDoc.disponible ? `Subida el ${escapeHtml(fmtDate(idDoc.subida_en))}` : idDoc.borrada_en ? `Borrada el ${escapeHtml(fmtDate(idDoc.borrada_en))} (huella ${escapeHtml((idDoc.sha256 || "").slice(0, 12))}…)` : idDoc.pedida_en ? "Pedida; aún no la sube" : ""],
        ["Recibida", escapeHtml(fmtDate(d.recibida_en))], ["Responder antes de", escapeHtml(fmtDate(d.responde_antes_de))],
        ["Primera respuesta antes de", d.primera_respuesta_antes_de ? escapeHtml(fmtDate(d.primera_respuesta_antes_de)) : ""],
        ["Hacerla efectiva antes de", d.efectiva_antes_de ? escapeHtml(fmtDate(d.efectiva_antes_de)) : ""],
        ["Requerimiento", d.requerimiento.pedido_en ? `Pedido el ${escapeHtml(fmtDate(d.requerimiento.pedido_en))}; vence ${escapeHtml(fmtDate(d.requerimiento.vence))}${d.requerimiento.recibido_en ? `; contestado el ${escapeHtml(fmtDate(d.requerimiento.recibido_en))}` : ""}` : ""],
        ["Ampliación", d.ampliacion.respuesta || d.ampliacion.efectiva ? escapeHtml(d.ampliacion.motivo || "") : ""],
        ["Publicación", d.reporte ? `#${d.reporte.id} ${escapeHtml(d.reporte.nombre)} (${escapeHtml(d.reporte.fuente)})${d.reporte.oculto ? " · oculta" : " · visible"}${d.reporte.borrado_en ? " · texto y fotos borrados" : ""}` : ""],
        ...extra,
      ])}
      <h4>Lo que pide</h4><p style="white-space:pre-line">${escapeHtml(d.descripcion)}</p>
      ${d.respuesta ? `<h4>Respuesta enviada</h4><p style="white-space:pre-line">${escapeHtml(d.respuesta)}</p>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0" id="sol-id-actions"></div>
      <h4>Acción</h4>
      <form id="sol-action-form" class="form-stack" novalidate>
        <label for="sa-accion">Acción</label>
        <select id="sa-accion">${opt(Object.fromEntries(d.acciones.map((a) => [a, ACCIONES[a] || a])))}</select>
        <div data-show="responder cerrar"><label for="sa-resultado">Resultado</label><select id="sa-resultado"><option value="">-</option>${opt(RESULTADOS)}</select></div>
        <div data-show="responder cerrar"><label for="sa-motivo">Causa de la negativa (si no procede)</label><select id="sa-motivo"><option value="">-</option>${opt(NEGATIVAS)}</select></div>
        <div data-show="verificar_identidad"><label for="sa-metodo">¿Cómo se comprobó?</label><select id="sa-metodo">${opt({ identificacion: "Identificación revisada", correo: "Correo confirmado", whatsapp: "Desde su número de WhatsApp", cuenta: "Su cuenta", otro: "Otro medio" })}</select></div>
        <label data-show="requerir_info" style="display:flex;gap:8px;align-items:flex-start"><input type="checkbox" id="sa-pedir-id"> Pedir también una identificación oficial (solo si hace falta)</label>
        <label data-show="hacer_efectiva" data-kind="cancelacion" style="display:flex;gap:8px;align-items:flex-start"><input type="checkbox" id="sa-del-cuenta"> Eliminar la cuenta ligada (misma anonimización que «Eliminar mi cuenta»; no se puede deshacer)</label>
        <label data-show="hacer_efectiva" data-kind="cancelacion" style="display:flex;gap:8px;align-items:flex-start"><input type="checkbox" id="sa-del-wa"> Borrar la conversación del bot de WhatsApp y los reportes de ese número</label>
        <div data-show="en_revision primera_respuesta requerir_info ampliar responder hacer_efectiva cerrar">
          <label for="sa-plantilla">Plantilla</label>
          <select id="sa-plantilla"><option value="">Sin plantilla</option>${d.plantillas.map((t, i) => `<option value="${i}">${escapeHtml(t.titulo)}</option>`).join("")}</select>
          <label for="sa-mensaje">Mensaje para la persona (le llega por correo)</label>
          <textarea id="sa-mensaje" rows="6" maxlength="8000"></textarea>
        </div>
        <label for="sa-nota">Nota interna (no se le envía)</label>
        <textarea id="sa-nota" rows="2" maxlength="4000"></textarea>
        <p class="hint" id="sa-help"></p>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button type="submit" class="btn-success" id="sa-send">Aplicar</button>
          <button type="button" class="btn-secondary" id="sa-cancel">Cerrar</button></div>
      </form>
      <h4>Historial</h4><ol style="padding-left:18px">${history}</ol>`;
    modal.classList.remove("hidden");
    $("#sa-cancel").addEventListener("click", () => modal.classList.add("hidden"));
    if (idDoc.disponible) $("#sol-id-actions").append(button("Ver identificación (privada)", () => run(() => openIdentification(d.folio)), "btn-secondary"));
    const form = $("#sol-action-form");
    const help = {
      en_revision: "Avisa a la persona que ya la revisas.",
      primera_respuesta: "Para quejas y dudas: la primera respuesta dentro del plazo publicado.",
      requerir_info: "Solo una vez y dentro de los 5 días hábiles siguientes a la recepción. La persona tiene 10 días hábiles; el plazo de respuesta vuelve a contar desde que conteste.",
      verificar_identidad: "Al marcarla, la copia de la identificación se borra y queda solo la constancia.",
      ampliar: "Solo una vez por plazo y antes de que venza. El motivo se le comunica a la persona.",
      responder: "Si procede, el plazo para hacerla efectiva son 15 días hábiles. Una negativa cierra la solicitud y le explica cómo acudir a la SABG.",
      hacer_efectiva: d.tipo === "acceso" ? "Le enviamos un enlace para descargar el archivo de «Mis datos» (15 días)." :
        d.tipo === "retiro_importado" ? "Borra el texto y las fotos de la publicación (se conserva el registro y el enlace)." :
        d.tipo === "revocacion" || d.tipo === "limitacion" ? "Apaga los permisos elegidos en la cuenta y en el bot. Con «publicidad» entra al listado de exclusión." :
        "Marca que se hizo lo que procedía.",
      cerrar: d.tipo === "retiro_importado" ? "Si no procede, la publicación vuelve a mostrarse." : "Cierra la solicitud y avisa a la persona.",
      nota: "Solo la ve el equipo.",
    };
    const sync = () => {
      const a = $("#sa-accion").value;
      form.querySelectorAll("[data-show]").forEach((elx) => {
        const kinds = elx.dataset.kind ? elx.dataset.kind.split(" ") : null;
        const off = !elx.dataset.show.split(" ").includes(a) || (kinds && !kinds.includes(d.tipo));
        elx.style.display = off ? "none" : "";  // [hidden] no gana a los display de admin.css
      });
      $("#sa-help").textContent = help[a] || "";
    };
    $("#sa-accion").addEventListener("change", sync);
    $("#sa-plantilla").addEventListener("change", () => {
      const t = d.plantillas[Number($("#sa-plantilla").value)];
      if (!t) return;
      $("#sa-mensaje").value = t.texto;
      if (t.accion && d.acciones.includes(t.accion)) $("#sa-accion").value = t.accion;
      if (t.resultado) $("#sa-resultado").value = t.resultado;
      if (t.identificacion) $("#sa-pedir-id").checked = true;
      sync();
    });
    sync();
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      run(async () => {
        const accion = $("#sa-accion").value;
        const payload = {
          accion, mensaje: $("#sa-mensaje").value.trim() || null, nota_interna: $("#sa-nota").value.trim() || null,
          resultado: $("#sa-resultado").value || null, motivo_negativa: $("#sa-motivo").value || null,
          pedir_identificacion: $("#sa-pedir-id").checked, metodo: $("#sa-metodo").value || null,
          eliminar_cuenta: $("#sa-del-cuenta").checked, eliminar_whatsapp: $("#sa-del-wa").checked,
        };
        if (payload.eliminar_cuenta && !confirm(`Se eliminará (anonimizará) la cuenta ligada a ${d.folio}. ¿Continuar?`)) return;
        const send = $("#sa-send");
        send.disabled = true;
        try {
          const updated = await api(`${BASE}/${encodeURIComponent(d.folio)}/acciones`, jsonOpts("POST", payload));
          renderDetail(updated);
          loadSummary();
          run(loadList);
        } finally { send.disabled = false; }
      });
    });
  }

  async function openIdentification(folio) {
    const win = window.open("", "_blank");  // antes del await para que el navegador no la bloquee
    try {
      const res = await fetch(`${API_BASE}${BASE}/${encodeURIComponent(folio)}/identificacion`, { headers: { Authorization: `Bearer ${currentToken}` } });
      if (res.status === 401) { logout("Tu sesión expiró. Inicia sesión de nuevo."); throw Object.assign(new Error(""), { silent: true }); }
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error((data && typeof data.detail === "string" && data.detail) || `No se pudo abrir la identificación (error ${res.status}).`);
      }
      const url = URL.createObjectURL(await res.blob());
      if (win) win.location.href = url; else window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      if (win) win.close();
      throw err;
    }
  }

  /* ---------------------------------------------------------------- alta manual */
  function openCreate() {
    const body = $("#modal-body");
    body.innerHTML = `<h3>Registrar una solicitud recibida por otro medio</h3>
      <p class="hint">Para solicitudes que llegaron por correo, por escrito, por teléfono o por WhatsApp. Se le da folio y se envía el acuse
        (y el enlace de confirmación si no se comprobó la identidad).</p>
      <form id="sol-new-form" class="form-stack" novalidate>
        <div class="form-row">
          <div><label for="sn-tipo">Tipo</label><select id="sn-tipo">${opt(Object.fromEntries(Object.entries(TIPOS).filter(([k]) => k !== "arco")))}</select></div>
          <div><label for="sn-canal">Canal</label><select id="sn-canal">${opt({ correo: "Correo", escrito: "Escrito", telefono: "Teléfono", whatsapp: "WhatsApp" })}</select></div>
        </div>
        <div class="form-row">
          <div><label for="sn-nombre">Nombre</label><input id="sn-nombre" maxlength="120" required></div>
          <div><label for="sn-email">Correo</label><input id="sn-email" type="email" maxlength="255"></div>
          <div><label for="sn-tel">Teléfono</label><input id="sn-tel" maxlength="30"></div>
        </div>
        <label for="sn-desc">Qué pide</label><textarea id="sn-desc" rows="4" maxlength="4000" required></textarea>
        <label for="sn-enlace">Enlace a la publicación (retiro de importados)</label><input id="sn-enlace" type="url" maxlength="1000">
        <label for="sn-ident">Identidad</label>
        <select id="sn-ident"><option value="">Sin comprobar (se le envía el enlace de confirmación)</option>${opt({ identificacion: "Ya la comprobamos con una identificación", whatsapp: "Escribió desde su número de WhatsApp", otro: "Comprobada por otro medio" })}</select>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button type="submit" class="btn-success">Registrar</button>
          <button type="button" class="btn-secondary" id="sn-cancel">Cancelar</button></div>
      </form>`;
    modal.classList.remove("hidden");
    $("#sn-cancel").addEventListener("click", () => modal.classList.add("hidden"));
    $("#sol-new-form").addEventListener("submit", (e) => {
      e.preventDefault();
      run(async () => {
        const tipo = $("#sn-tipo").value;
        const payload = {
          tipo, canal: $("#sn-canal").value, nombre: $("#sn-nombre").value.trim(), email: $("#sn-email").value.trim() || null,
          telefono: $("#sn-tel").value.trim() || null, descripcion: $("#sn-desc").value.trim(), enlace: $("#sn-enlace").value.trim() || null,
          identidad: $("#sn-ident").value || null, acepta_privacidad: true,
        };
        if (tipo === "revocacion" || tipo === "limitacion") payload.permisos = ["otro"];
        if (tipo === "queja") payload.motivo = "otro";
        if (tipo === "retiro_importado") payload.relacion = "autor";
        const d = await api(BASE, jsonOpts("POST", payload));
        renderDetail(d);
        loadSummary();
        run(loadList);
      });
    });
  }

  /* ---------------------------------------------------------------- registro en el panel */
  loaders.solicitudes = () => Promise.all([loadSummary(), loadList()]);
  const filterBtn = $("#sol-filter-btn");
  if (filterBtn) filterBtn.addEventListener("click", () => {
    st.estado = $("#sol-filter-estado").value;
    st.tipo = $("#sol-filter-tipo").value;
    st.q = $("#sol-filter-q").value.trim();
    st.page = 0;
    run(loadList);
  });
  const typeSel = $("#sol-filter-tipo");
  if (typeSel && typeSel.options.length <= 1) typeSel.insertAdjacentHTML("beforeend", opt(TIPOS));
  const newBtn = $("#sol-new-btn");
  if (newBtn) newBtn.addEventListener("click", openCreate);
  // Los avisos llevan a /admin/#solicitudes: se abre la sección cuando el panel ya está listo
  if (location.hash === "#solicitudes") {
    let tries = 0;
    const timer = setInterval(() => {
      const app = $("#app-view");
      if (app && !app.classList.contains("hidden")) { clearInterval(timer); showSection("solicitudes"); }
      else if (++tries > 50) clearInterval(timer);
    }, 200);
  }
})();
