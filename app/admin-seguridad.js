/* ============================================================
   GuauWoow Admin — Seguridad (L-seguridad)
   - Alta de la verificación en dos pasos (TOTP): código QR generado en el navegador con
     vendor/qrcode-generator (el secreto nunca sale a otro servicio) o el secreto en texto,
     primer código y 10 códigos de recuperación que solo se muestran una vez.
   - Sección «Seguridad»: tu MFA, MFA del personal, registro de incidentes con avisos a personas
     afectadas (plantillas del runbook §7), estado del cifrado y corridas de la purga de conservación.
   Endpoints: POST /auth/mfa/setup|enable|recovery-codes|disable, GET /auth/mfa/status,
   GET/POST/PATCH /admin/cumplimiento/incidentes[/{id}], POST /admin/cumplimiento/incidentes/{id}/avisos[/vista-previa],
   GET /admin/cumplimiento/mfa, POST /admin/cumplimiento/mfa/{id}/reset, GET /admin/cumplimiento/cifrado,
   GET /admin/cumplimiento/conservacion, POST /admin/cumplimiento/conservacion/ejecutar.
   Se carga después de admin.js y usa sus utilidades globales
   (api, jsonOpts, run, escapeHtml, fmtDate, el, button, renderTable, loaders, currentToken, TOKEN_KEY, API_BASE, $).
   ============================================================ */
"use strict";

(() => {
  const COMPONENTS = {
    web: "Sitio y app web", api: "Servidor (API)", base_de_datos: "Base de datos", cola: "Tareas en segundo plano",
    correo: "Correo", pagos: "Pagos", sms: "Código por SMS", whatsapp: "Asistente de WhatsApp", ia: "IA",
  };
  const CATEGORY = { vulneracion: "Vulneración de datos", disponibilidad: "Caída o falla", mantenimiento: "Mantenimiento programado" };
  const TYPES = {
    perdida: "Pérdida o destrucción", robo_copia: "Robo, extravío o copia", uso_no_autorizado: "Uso o acceso no autorizado",
    dano_alteracion: "Daño o alteración", caida: "Caída del servicio", credenciales: "Credenciales o tokens comprometidos",
    aviso_proveedor: "Aviso de un proveedor", otro: "Otro",
  };
  const STATUS = { abierto: ["abierto", "bad"], contenido: ["contenido", "warn"], cerrado: ["cerrado", "ok"] };
  const st = { status: "activos", incidents: [] };

  const badge = (map, key) => {
    const [label, cls] = map[key] || [key, ""];
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
  };
  const toIso = (local) => (local ? new Date(local).toISOString() : null);
  const toLocal = (iso) => {
    if (!iso) return "";
    const d = new Date(/[zZ]$/.test(iso) ? iso : iso + "Z");
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const listText = (v) => (Array.isArray(v) ? v.join(", ") : "");
  const listFrom = (text) => String(text || "").split(",").map((s) => s.trim()).filter(Boolean);

  async function postJson(path, data, token) {
    // Sin sesión todavía (alta desde el primer paso): fetch directo sin Authorization
    if (token === undefined) return api(path, jsonOpts("POST", data));
    let res;
    try { res = await fetch(`${API_BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }); }
    catch { throw new Error("Sin conexión con el servidor."); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(typeof body.detail === "string" ? body.detail : `Error ${res.status}`), { status: res.status });
    return body;
  }

  /* ------------------------------------------------------------------ alta de la MFA */
  function qrImage(uri) {
    if (typeof window.qrcode !== "function") return null;
    try {
      const qr = window.qrcode(0, "M");
      qr.addData(uri);
      qr.make();
      return el("img", { src: qr.createDataURL(5, 4), alt: "Código QR para tu app de autenticación", class: "mfa-qr", width: "220", height: "220" });
    } catch { return null; }
  }

  function showRecoveryCodes(container, codes, onDone) {
    container.innerHTML = "";
    const list = el("ol", { class: "mfa-codes" });
    codes.forEach((c) => list.append(el("li", {}, el("code", { text: c }))));
    const copy = button("Copiar códigos", () => {
      navigator.clipboard?.writeText(codes.join("\n")).then(() => { copy.textContent = "Copiados"; }, () => {});
    }, "btn-secondary");
    const done = button("Ya los guardé", () => onDone());
    done.disabled = true;
    const check = el("input", { type: "checkbox", id: "mfa-codes-ok" });
    check.addEventListener("change", () => { done.disabled = !check.checked; });
    container.append(
      el("h3", { text: "Guarda tus códigos de recuperación" }),
      el("p", { class: "hint", text: "Cada código sirve una sola vez si pierdes tu teléfono. No volverás a verlos: guárdalos en un gestor de contraseñas o impresos en un lugar seguro." }),
      list, copy,
      el("div", { class: "mfa-check" }, [check, el("label", { for: "mfa-codes-ok", text: "Guardé mis códigos en un lugar seguro" })]),
      done,
    );
  }

  /* container: dónde dibujar; mfaToken: comprobante del primer paso (o null con sesión); onSession(token); onCancel();
     rotate: {code, password} para cambiar una app que ya está activa (el backend los exige) */
  async function startEnrollment(container, mfaToken, onSession, onCancel, rotate) {
    const viaToken = !!mfaToken;
    const call = (path, data) => (viaToken ? postJson(path, { ...data, mfa_token: mfaToken }, null) : postJson(path, data));
    container.innerHTML = '<p class="hint">Preparando tu código…</p>';
    let setup;
    try { setup = await call("/auth/mfa/setup", rotate || {}); }
    catch (err) { container.innerHTML = ""; container.append(el("p", { class: "error", text: err.message })); if (onCancel) container.append(button("Volver", onCancel, "btn-secondary")); return; }
    container.innerHTML = "";
    const secretText = setup.secret.replace(/(.{4})/g, "$1 ").trim();
    const code = el("input", { type: "text", id: "mfa-enroll-code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "8", required: "" });
    const error = el("p", { class: "error" });
    const form = el("form", { class: "form-stack mfa-enroll-form" }, [
      el("label", { for: "mfa-enroll-code", text: "Código de 6 dígitos que muestra la app" }), code,
      el("button", { type: "submit", text: "Activar verificación en dos pasos" }), error,
    ]);
    const qr = qrImage(setup.otpauth_uri);
    container.append(
      el("h3", { text: "Configura la verificación en dos pasos" }),
      el("p", { class: "hint", text: "Es obligatoria para el personal administrador. Abre tu app de autenticación (Google Authenticator, Microsoft Authenticator, 1Password, Authy…) y escanea este código." }),
      qr || el("p", { class: "hint", text: "No se pudo dibujar el código QR: usa la clave de abajo." }),
      el("p", { class: "hint", text: "¿No puedes escanearlo? Agrega una cuenta con esta clave (tipo «basada en tiempo»):" }),
      el("p", {}, el("code", { class: "mfa-secret", text: secretText })),
      el("p", { class: "hint", text: `Cuenta: ${setup.account}` }),
      form,
    );
    if (onCancel) container.append(button("Cancelar", onCancel, "btn-secondary"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      error.textContent = "";
      try {
        const out = await call("/auth/mfa/enable", { code: code.value.trim() });
        showRecoveryCodes(container, out.recovery_codes || [], () => onSession(out.access_token));
      } catch (err) { error.textContent = err.message; }
    });
    code.focus();
  }

  /* ------------------------------------------------------------------ tu MFA */
  function setSession(token) {
    currentToken = token;
    localStorage.setItem(TOKEN_KEY, token);
  }

  async function loadMine() {
    const box = $("#sec-mfa-me");
    const s = await api("/auth/mfa/status");
    box.innerHTML = "";
    if (!s.enabled) {
      box.append(el("p", { text: s.required ? "Aún no tienes la verificación en dos pasos (es obligatoria)." : "No tienes la verificación en dos pasos (en este entorno es opcional)." }));
      const holder = el("div");
      box.append(button("Activar ahora", () => startEnrollment(holder, null, (token) => { setSession(token); run(load); }, () => { holder.innerHTML = ""; })), holder);
      return;
    }
    box.append(el("p", { html: `Activa desde ${escapeHtml(fmtDate(s.enabled_at))}. Códigos de recuperación disponibles: <strong>${escapeHtml(s.recovery_codes_left)}</strong>.` }));
    const holder = el("div");
    box.append(button("Cambiar de app o teléfono", () => run(async () => {
      const code = prompt("Para cambiar tu app escribe un código actual de tu app de autenticación (o uno de recuperación):");
      if (!code) return;
      const password = prompt("Tu contraseña:") || "";
      await startEnrollment(holder, null, (token) => { setSession(token); run(load); }, () => { holder.innerHTML = ""; },
        { code: code.trim(), password });
    }), "btn-secondary"));
    box.append(button("Generar códigos de recuperación nuevos", () => run(async () => {
      const code = prompt("Escribe el código actual de tu app de autenticación:");
      if (!code) return;
      const out = await api("/auth/mfa/recovery-codes", jsonOpts("POST", { code: code.trim() }));
      showRecoveryCodes(holder, out.recovery_codes, () => { holder.innerHTML = ""; run(loadMine); });
    }), "btn-secondary"));
    if (!s.required) {
      box.append(button("Desactivar", () => run(async () => {
        const code = prompt("Código actual de tu app de autenticación:");
        if (!code) return;
        const password = prompt("Tu contraseña:") || "";
        const out = await api("/auth/mfa/disable", jsonOpts("POST", { code: code.trim(), password }));
        if (out.access_token) setSession(out.access_token);
        run(load);
      }), "btn-danger"));
    }
    box.append(holder);
  }

  async function loadAdmins() {
    let data;
    try { data = await api("/admin/cumplimiento/mfa"); }
    catch (err) { $("#sec-mfa-admins").innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`; return; }
    renderTable("sec-mfa-admins", ["Persona", "Rol", "Verificación", "Códigos", "Acción"], data.admins.map((a) => [
      `${escapeHtml(a.full_name)}<br><small>${escapeHtml(a.email)}</small>`, escapeHtml(a.role),
      a.mfa_enabled ? `<span class="badge ok">activa</span> <small>${escapeHtml(fmtDate(a.mfa_enabled_at))}</small>`
        : `<span class="badge ${data.required ? "bad" : "warn"}">${data.required ? "pendiente (obligatoria)" : "sin activar"}</span>`,
      escapeHtml(a.recovery_codes_left),
      a.mfa_enabled ? button("Restablecer", () => run(async () => {
        if (!confirm(`¿Restablecer la verificación en dos pasos de ${a.email}? Se cerrarán sus sesiones y la configurará al volver a entrar.`)) return;
        await api(`/admin/cumplimiento/mfa/${encodeURIComponent(a.id)}/reset`, jsonOpts("POST", {}));
        run(loadAdmins);
      }), "btn-danger") : "-",
    ]));
  }

  /* ------------------------------------------------------------------ incidentes */
  async function loadIncidents() {
    const params = new URLSearchParams({ limit: 100 });
    if (st.status) params.set("status", st.status);
    st.incidents = await api(`/admin/cumplimiento/incidentes?${params}`);
    renderTable("sec-inc-table", ["Folio", "Incidente", "Severidad", "Estado", "Detectado", "Purgas", "Público", "Acciones"], st.incidents.map((i) => [
      escapeHtml(i.folio || i.id),
      `${escapeHtml(i.title)}<br><small>${escapeHtml(CATEGORY[i.category] || i.category)}${i.affected_count != null ? ` · ${escapeHtml(i.affected_count)} titulares` : ""}</small>`,
      escapeHtml(i.severity), badge(STATUS, i.status), escapeHtml(fmtDate(i.detected_at)),
      i.purges_frozen ? `<span class="badge warn">congeladas</span><br><small>hasta ${escapeHtml(fmtDate(i.freeze_until))}</small>`
        : i.freeze_expired ? '<span class="badge bad">congelamiento vencido</span><br><small>la purga ya corre</small>' : "-",
      i.public ? '<span class="badge ok">sí</span>' : "no",
      [button("Editar", () => openForm(i)), button("Avisar a afectados", () => openNotice(i), "btn-secondary"),
        ...((i.purges_frozen || i.freeze_expired) && i.status !== "cerrado" ? [button("Renovar congelamiento", () => run(async () => {
          if (!confirm("¿Congelar las purgas otros 30 días por este incidente? Solo un superadmin puede hacerlo y queda en la bitácora.")) return;
          await api(`/admin/cumplimiento/incidentes/${encodeURIComponent(i.id)}`, jsonOpts("PATCH", { renew_freeze: true, freeze_purges: true }));
          await loadIncidents();
          await loadRetention();
        }), "btn-secondary")] : [])],
    ]));
  }

  const field = (label, input) => el("div", {}, [el("label", { text: label, for: input.id }), input]);
  const input = (id, value, attrs = {}) => el("input", { id, value: value ?? "", ...attrs });
  const area = (id, value, rows = 3) => { const t = el("textarea", { id, rows: String(rows) }); t.value = value ?? ""; return t; };
  function selectOf(id, map, value, empty) {
    const s = el("select", { id });
    if (empty) s.append(el("option", { value: "", text: empty }));
    Object.entries(map).forEach(([k, v]) => { const o = el("option", { value: k, text: v }); if (k === value) o.selected = true; s.append(o); });
    return s;
  }

  function openForm(inc) {
    const box = $("#sec-inc-form");
    box.classList.remove("hidden");
    box.innerHTML = "";
    const i = inc || { category: "vulneracion", severity: "S3", status: "abierto", freeze_purges: true };
    const comps = el("div", { class: "sec-components" });
    Object.entries(COMPONENTS).forEach(([k, label]) => {
      const cb = el("input", { type: "checkbox", id: `sec-comp-${k}`, value: k });
      cb.checked = (i.components || []).includes(k);
      comps.append(el("span", { class: "fb-check" }, [cb, el("label", { for: `sec-comp-${k}`, text: label })]));
    });
    const freeze = el("input", { type: "checkbox", id: "sec-f-freeze" }); freeze.checked = i.freeze_purges !== false;
    const pub = el("input", { type: "checkbox", id: "sec-f-public" }); pub.checked = !!i.public;
    const impact = selectOf("sec-f-impact", { si: "Sí: hay que avisar a los titulares", no: "No (anota la razón)" },
      i.significant_impact === true ? "si" : i.significant_impact === false ? "no" : "", "Sin decidir");
    const error = el("p", { class: "error" });
    const form = el("form", { class: "form-stack" }, [
      el("h3", { text: inc ? `Incidente ${inc.folio}` : "Registrar incidente" }),
      field("Título", input("sec-f-title", i.title, { maxlength: "200", required: "" })),
      el("div", { class: "form-row" }, [
        field("Categoría", selectOf("sec-f-category", CATEGORY, i.category)),
        field("Tipo", selectOf("sec-f-type", TYPES, i.incident_type, "Sin clasificar")),
        field("Severidad", selectOf("sec-f-severity", { S1: "S1 (identificaciones, credenciales, fraude)", S2: "S2 (datos de contacto)", S3: "S3 (sin datos personales)" }, i.severity)),
        field("Estado", selectOf("sec-f-status", { abierto: "Abierto", contenido: "Contenido", cerrado: "Cerrado" }, i.status)),
      ]),
      field("Fuente de detección", input("sec-f-source", i.detection_source, { maxlength: "200" })),
      field("Qué pasó (interno)", area("sec-f-desc", i.description, 4)),
      el("div", { class: "form-row" }, [
        field("Sistemas afectados (separados por comas)", input("sec-f-systems", listText(i.systems_affected))),
        field("Categorías de datos (separadas por comas)", input("sec-f-data", listText(i.data_categories))),
        field("Titulares afectados (estimado)", input("sec-f-count", i.affected_count, { type: "number", min: "0" })),
      ]),
      el("label", { text: "Componentes del tablero afectados" }), comps,
      el("div", { class: "form-row" }, [
        field("Inicio del impacto", input("sec-f-start", toLocal(i.started_at), { type: "datetime-local" })),
        field("Fin del impacto", input("sec-f-end", toLocal(i.ended_at), { type: "datetime-local" })),
      ]),
      field("¿Afectación significativa? (LFPDPPP art. 19)", impact),
      field("Razón de la decisión", area("sec-f-impact-reason", i.significant_impact_reason)),
      field("Acciones inmediatas (contención)", area("sec-f-immediate", i.immediate_actions)),
      field("Causa raíz", area("sec-f-root", i.root_cause)),
      field("Acciones definitivas", area("sec-f-definitive", i.definitive_actions)),
      field("Evidencia preservada (ubicación y hash)", input("sec-f-evidence", i.evidence_ref, { maxlength: "500" })),
      el("span", { class: "fb-check" }, [freeze, el("label", { for: "sec-f-freeze", text: "Congelar las purgas automáticas mientras esté abierto" })]),
      el("span", { class: "fb-check" }, [pub, el("label", { for: "sec-f-public", text: "Publicar el resumen en la página de estado" })]),
      field("Resumen público (sin detalles que ayuden a un atacante)", area("sec-f-summary", i.public_summary, 2)),
      field("Nota para la línea de tiempo", input("sec-f-note", "", { maxlength: "2000" })),
      el("button", { type: "submit", text: inc ? "Guardar cambios" : "Registrar" }),
      button("Cancelar", () => { box.classList.add("hidden"); box.innerHTML = ""; }, "btn-secondary"),
      error,
    ]);
    if (inc && inc.timeline && inc.timeline.length) {
      const tl = el("ul", { class: "sec-timeline" });
      inc.timeline.slice().reverse().forEach((t) => tl.append(el("li", { text: `${fmtDate(t.at)} · ${t.text}` })));
      form.append(el("h4", { text: "Línea de tiempo" }), tl);
    }
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      error.textContent = "";
      const v = (id) => $(`#${id}`).value.trim();
      const count = v("sec-f-count");
      const data = {
        title: v("sec-f-title"), category: v("sec-f-category"), incident_type: v("sec-f-type") || null,
        severity: v("sec-f-severity"), status: v("sec-f-status"), detection_source: v("sec-f-source") || null,
        description: v("sec-f-desc") || null, systems_affected: listFrom(v("sec-f-systems")),
        data_categories: listFrom(v("sec-f-data")), affected_count: count === "" ? null : Number(count),
        components: [...comps.querySelectorAll("input:checked")].map((c) => c.value),
        started_at: toIso(v("sec-f-start")), ended_at: toIso(v("sec-f-end")),
        significant_impact: v("sec-f-impact") === "si" ? true : v("sec-f-impact") === "no" ? false : null,
        significant_impact_reason: v("sec-f-impact-reason") || null, immediate_actions: v("sec-f-immediate") || null,
        root_cause: v("sec-f-root") || null, definitive_actions: v("sec-f-definitive") || null,
        evidence_ref: v("sec-f-evidence") || null, freeze_purges: freeze.checked, public: pub.checked,
        public_summary: v("sec-f-summary") || null,
      };
      if (v("sec-f-note")) data.note = v("sec-f-note");
      run(async () => {
        try {
          if (inc) await api(`/admin/cumplimiento/incidentes/${encodeURIComponent(inc.id)}`, jsonOpts("PATCH", data));
          else await api("/admin/cumplimiento/incidentes", jsonOpts("POST", data));
        } catch (err) { error.textContent = err.message; return; }
        box.classList.add("hidden");
        box.innerHTML = "";
        loadIncidents();
      });
    });
    box.append(form);
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* Aviso a personas afectadas (runbook §7.1 correo y §7.2 app) */
  function openNotice(inc) {
    const body = $("#modal-body");
    const n = inc.notice || {};
    body.innerHTML = "";
    const all = el("input", { type: "checkbox", id: "sec-n-all" });
    const preview = el("pre", { class: "response-box" });
    const error = el("p", { class: "error" });
    const form = el("form", { class: "form-stack" }, [
      el("h3", { text: `Avisar a las personas afectadas · ${inc.folio}` }),
      el("p", { class: "hint", text: "Debe decir qué pasó, qué datos, qué hicimos, qué recomendamos y dónde informarse. Se envía por correo y en la app; cada envío queda registrado. Reenviar el mismo aviso no duplica." }),
      field("Resumen (va en el asunto)", input("sec-n-resumen", n.resumen, { maxlength: "200", required: "" })),
      field("Fecha del incidente (p. ej. «17 de octubre de 2026»)", input("sec-n-fecha", n.fecha, { maxlength: "60", required: "" })),
      field("Qué pasó", area("sec-n-que", n.que_paso)),
      field("Qué datos se vieron afectados (lista exacta)", area("sec-n-datos", n.datos, 2)),
      field("Qué datos NO se vieron afectados", area("sec-n-no", n.no_afectados, 2)),
      field("Qué hicimos", area("sec-n-acciones", n.acciones)),
      field("Qué recomendamos", area("sec-n-recom", n.recomendaciones)),
      field("Enlace con más información (opcional)", input("sec-n-mas", n.mas_info, { maxlength: "500" })),
      field("Correos o IDs de las cuentas afectadas (uno por línea)", area("sec-n-to", "", 4)),
      el("span", { class: "fb-check" }, [all, el("label", { for: "sec-n-all", text: "Avisar a todas las cuentas activas (solo superadmin)" })]),
      el("div", { class: "actions" }, [
        button("Vista previa", () => send(true), "btn-secondary"),
        el("button", { type: "submit", text: "Enviar aviso" }),
      ]),
      error, preview,
    ]);
    const notice = () => {
      const v = (id) => $(`#${id}`).value.trim();
      return { resumen: v("sec-n-resumen"), fecha: v("sec-n-fecha"), que_paso: v("sec-n-que"), datos: v("sec-n-datos"),
        no_afectados: v("sec-n-no") || null, acciones: v("sec-n-acciones"), recomendaciones: v("sec-n-recom"), mas_info: v("sec-n-mas") || null };
    };
    async function send(previewOnly) {
      error.textContent = "";
      try {
        if (previewOnly) {
          const p = await api(`/admin/cumplimiento/incidentes/${encodeURIComponent(inc.id)}/avisos/vista-previa`, jsonOpts("POST", notice()));
          preview.textContent = `ASUNTO: ${p.email_subject}\n\n${p.email_body}\n\n— En la app —\n${p.app_title}: ${p.app_body}`;
          return;
        }
        const lines = $("#sec-n-to").value.split(/\s*[\n,;]\s*/).map((s) => s.trim()).filter(Boolean);
        const ids = lines.filter((s) => /^\d+$/.test(s)).map(Number);
        const emails = lines.filter((s) => s.includes("@"));
        if (!all.checked && !ids.length && !emails.length) { error.textContent = "Indica a quién avisar."; return; }
        if (!confirm(all.checked ? "¿Enviar el aviso a TODAS las cuentas activas?" : `¿Enviar el aviso a ${ids.length + emails.length} persona(s)?`)) return;
        const out = await api(`/admin/cumplimiento/incidentes/${encodeURIComponent(inc.id)}/avisos`, jsonOpts("POST", {
          notice: notice(), user_ids: ids, emails, all_users: all.checked,
        }));
        preview.textContent = `Aviso v${out.version}: ${out.app} en la app, ${out.email} por correo, ${out.sin_correo} sin correo, ${out.omitidos} ya lo tenían.`
          + (out.pendientes ? ` Faltan ${out.pendientes} cuentas: vuelve a pulsar «Enviar» con el mismo aviso para continuar (nadie lo recibe dos veces).` : "");
        loadIncidents();
      } catch (err) { if (!err.silent) error.textContent = err.message; }
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); send(false); });
    body.append(form);
    $("#modal").classList.remove("hidden");
  }

  /* ------------------------------------------------------------------ cifrado y conservación */
  async function loadCrypto() {
    const box = $("#sec-cifrado");
    const s = await api("/admin/cumplimiento/cifrado");
    box.innerHTML = s.ok
      ? `<p>${s.own_key ? "Llave propia configurada" : '<span class="badge warn">Llave de desarrollo</span> (define PRIVATE_FILES_KEY)'} · id <code>${escapeHtml(s.key_id)}</code></p>
         <p>Archivos privados: ${escapeHtml(s.private_files)} · sin cifrar: <strong>${escapeHtml(s.plaintext_files)}</strong>${s.command ? ` → corre <code>${escapeHtml(s.command)}</code>` : ""}</p>`
      : `<p class="error">${escapeHtml(s.error)}</p>`;
  }

  async function loadRetention() {
    const data = await api("/admin/cumplimiento/conservacion");
    const fz = data.congelamiento || {};
    $("#sec-ret-status").textContent = data.congelada_por_incidente
      ? `La purga está congelada por un incidente abierto (${(fz.incidentes || []).join(", ")}) hasta el ${fmtDate(fz.hasta)} (tope de ${fz.max_dias || 30} días; lo renueva un superadmin). `
        + ((fz.siguen_corriendo || []).length ? "El borrado de identificaciones y documentos de verificación sigue corriendo." : "También está detenido el borrado de documentos de verificación (el incidente los incluye).")
      : !data.purga_activada ? "La purga está desactivada (RETENTION_PURGE_ENABLED=false)." : "La purga diaria está activa (5:05 h, Ciudad de México).";
    const summary = (r) => Object.entries(r.resultados || {}).map(([k, v]) => {
      const n = Object.entries(v || {}).filter(([, x]) => typeof x === "number" && x > 0);
      return n.length ? escapeHtml(`${k}: ${n.map(([a, b]) => `${a}=${b}`).join(", ")}`) : (v && v.error ? escapeHtml(`${k}: error`) : "");
    }).filter(Boolean).join("<br>") || "sin cambios";
    renderTable("sec-ret-runs", ["Inicio", "Estado", "Simulación", "Resultado"], data.corridas.map((r) => [
      escapeHtml(fmtDate(r.inicio)), escapeHtml(r.estado), r.simulacion ? "sí" : "no", `<small>${summary(r)}</small>`,
    ]));
  }

  async function runPurge(dry) {
    if (!dry && !confirm("¿Ejecutar la purga ahora? Borra o anonimiza lo que ya venció según la tabla de conservación.")) return;
    const out = await api("/admin/cumplimiento/conservacion/ejecutar", jsonOpts("POST", { dry_run: dry }));
    $("#sec-ret-status").textContent = `Corrida ${dry ? "simulada" : "real"}: ${out.status}.`;
    loadRetention();
  }

  async function load() {
    await Promise.all([loadMine(), loadAdmins(), loadIncidents(), loadCrypto(), loadRetention()]);
  }

  $("#sec-inc-filter")?.addEventListener("click", () => { st.status = $("#sec-inc-status").value; run(loadIncidents); });
  $("#sec-inc-new")?.addEventListener("click", () => openForm(null));
  $("#sec-ret-dry")?.addEventListener("click", () => run(() => runPurge(true)));
  $("#sec-ret-run")?.addEventListener("click", () => run(() => runPurge(false)));
  if (typeof loaders === "object") loaders.seguridad = () => load();
  if (typeof STATUS_ES === "object") Object.assign(STATUS_ES, { abierto: "abierto", contenido: "contenido", cerrado: "cerrado" });

  window.AdminSeguridad = { startEnrollment, load };
})();
