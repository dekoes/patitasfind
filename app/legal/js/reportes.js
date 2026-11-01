/* ============================================================
   GuauWoow · Reportes públicos, derechos de autor y apelaciones (contrato K-REPORTES)
   Puntos de montaje en las páginas legales:
     #form-reporte-publico   moderacion.html §1 y proteccion-nna.html §7 (sin cuenta)
     #form-aviso-autor       derechos-de-autor.html §5 (Reglamento LFDA art. 37 Quáter)
     #form-contra-aviso      derechos-de-autor.html §5 (Reglamento LFDA art. 37 Septies)
     #form-apelacion         moderacion.html §7 (si la página no lo trae, se agrega al final de section#apelacion)
   Enlaces que llegan por correo o desde la app:
     ?enlace=…&motivo=…      prellena el reporte
     ?apelacion=MOD-…        prellena la apelación (aviso de una medida de moderación)
     ?contraaviso=DA-…       prellena el contra-aviso (aviso de retiro por derechos de autor)
   Funciona sin cuenta; si hay sesión de la app (localStorage «patitas_token») el reporte se liga a la cuenta.
   API: /cumplimiento/reportes-publicos, /cumplimiento/derechos-autor/…, /cumplimiento/apelaciones
   (backend/app/routers/cumplimiento_reportes.py). Sin manejadores en línea (CSP); el texto siempre va escapado.
   ============================================================ */
"use strict";

(() => {
  if (window.__pfReportes) return; // la página puede incluir el script más de una vez
  window.__pfReportes = true;

  const TOKEN_KEY = "patitas_token";
  const TZ = "America/Mexico_City";
  // Respaldo si no responde /cumplimiento/reportes-publicos/motivos (mismo orden y textos que el servidor)
  const FALLBACK_REASONS = [
    ["involucra_menor", "Involucra a una niña, niño o adolescente", "menores"],
    ["abuso_sexual_infantil", "Material de abuso sexual infantil", "menores"],
    ["acoso", "Acoso", "decreto"],
    ["abuso_sexual", "Abuso, explotación o violencia sexual", "decreto"],
    ["odio_violencia_masiva", "Discurso de odio o violencia masiva", "decreto"],
    ["incitacion_odio_violencia", "Incitación al odio o a la violencia", "decreto"],
    ["conductas_ilicitas", "Conductas ilícitas o apología del delito", "decreto"],
    ["pornografia", "Pornografía", "decreto"],
    ["suicidio_autolesiones", "Suicidio, autolesiones o trastornos alimenticios", "decreto"],
    ["contenido_intimo", "Contenido íntimo sin consentimiento", "otros"],
    ["maltrato", "Maltrato animal", "otros"],
    ["venta_animal", "Venta o cobro por un animal", "otros"],
    ["fraude", "Estafa o solicitud de dinero", "otros"],
    ["mi_imagen", "Mi imagen o mis datos", "otros"],
    ["difamacion", "Difamación o acusación contra una persona", "otros"],
    ["suplantacion", "Suplantación", "otros"],
    ["resena_falsa", "Reseña falsa o pagada", "otros"],
    ["honor_reputacion", "Afecta mi honor o reputación", "otros"],
    ["datos_personales", "Datos personales", "otros"],
    ["cedula_falsa", "Cédula o veterinario falso", "otros"],
    ["condiciones_sanitarias", "Condiciones sanitarias", "otros"],
    ["publicidad_enganosa", "Publicidad engañosa", "otros"],
    ["spam", "Spam", "otros"],
    ["contenido_inapropiado", "Contenido inapropiado", "otros"],
    ["datos_falsos", "Datos falsos", "otros"],
    ["otro", "Otro", "otros"],
  ].map(([value, label, grupo]) => ({ value, label, grupo, oculta_al_reportar: grupo === "menores" }));
  const GROUPS = [
    ["menores", "Niñas, niños y adolescentes (se oculta de inmediato)"],
    ["decreto", "Contenido prohibido por el Decreto de entornos digitales seguros"],
    ["otros", "Otros motivos"],
  ];

  /* ---------------------------------------------------------------- utilidades */
  let uid = 0;
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nid = (p) => `rep-${p}-${++uid}`;
  const params = new URLSearchParams(location.search);
  const token = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
  const toDate = (v) => { if (!v) return null; const s = String(v); return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`); };
  const fmtDay = (v) => { const d = toDate(v); return d ? d.toLocaleDateString("es-MX", { timeZone: TZ, day: "numeric", month: "long", year: "numeric" }) : ""; };
  const EMAIL_RE = /^[^@\s<>"']+@[^@\s<>"']+\.[^@\s<>"']+$/;

  async function api(path, { method = "GET", body, auth = true } = {}) {
    const headers = {};
    const tk = auth ? token() : "";
    if (tk) headers.Authorization = `Bearer ${tk}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res;
    try { res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" }); }
    catch { throw new Error("No hay conexión. Revisa tu internet e inténtalo de nuevo."); }
    // Sesión vencida: se reintenta sin cuenta (los formularios funcionan igual)
    if (res.status === 401 && tk) return api(path, { method, body, auth: false });
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      let detail = data && data.detail;
      if (Array.isArray(detail)) detail = "Revisa los datos del formulario.";
      if (typeof detail !== "string" || !detail) {
        detail = res.status === 429 ? "Enviaste varias solicitudes seguidas. Espera un rato e inténtalo de nuevo."
          : res.status >= 500 ? "Tuvimos un problema al recibirlo. Inténtalo de nuevo en unos minutos." : "No pudimos enviarlo. Revisa los datos.";
      }
      throw new Error(detail);
    }
    return data;
  }

  let reasonsPromise = null;
  function loadReasons() {
    if (!reasonsPromise) {
      reasonsPromise = api("/cumplimiento/reportes-publicos/motivos", { auth: false })
        .then((list) => (Array.isArray(list) && list.length ? list : FALLBACK_REASONS))
        .catch(() => FALLBACK_REASONS);
    }
    return reasonsPromise;
  }

  function field(label, control, hint = "", hintId = "") {
    return `<div class="rep-field">${label}${control}${hint ? `<p class="rep-hint"${hintId ? ` id="${hintId}"` : ""}>${hint}</p>` : ""}</div>`;
  }
  const honeypot = () => `<div class="rep-hp" aria-hidden="true"><label>Deja este campo vacío<input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>`;
  const statusLine = () => `<p class="rep-status" role="alert" tabindex="-1" hidden></p>`;
  const checkbox = (name, text) => { const c = nid(name); return `<div class="rep-check"><input type="checkbox" id="${c}" name="${name}"><label for="${c}">${text}</label></div>`; };
  function radios(name, options, checked, legend) {
    const items = options.map(([value, label]) => {
      const r = nid(name);
      return `<div class="rep-check"><input type="radio" id="${r}" name="${name}" value="${esc(value)}"${value === checked ? " checked" : ""}><label for="${r}">${esc(label)}</label></div>`;
    }).join("");
    return `<fieldset class="rep-fieldset"><legend>${legend}</legend>${items}</fieldset>`;
  }

  function showError(form, message) {
    const st = $(".rep-status", form);
    st.textContent = message;
    st.hidden = false;
    st.classList.add("is-error");
    st.focus();
  }

  function clearError(form) {
    const st = $(".rep-status", form);
    if (st) { st.hidden = true; st.textContent = ""; st.classList.remove("is-error"); }
  }

  async function withButton(form, fn) {
    const btn = $("button[type=submit]", form);
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Enviando…";
    clearError(form);
    try { await fn(); }
    catch (err) { showError(form, err.message || "No pudimos enviarlo. Inténtalo de nuevo."); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  function ack(mount, title, folio, lines) {
    const box = document.createElement("div");
    box.className = "rep-ack";
    box.setAttribute("role", "status");
    box.tabIndex = -1;
    box.innerHTML = `<p class="rep-ack-title">${esc(title)}</p>
      <p class="rep-folio">Folio: <strong>${esc(folio)}</strong></p>
      ${lines.filter(Boolean).map((l) => `<p>${esc(l)}</p>`).join("")}
      <p class="rep-hint">Guarda tu folio: con él y tu correo puedes dar seguimiento.</p>`;
    mount.replaceChildren(box);
    box.focus();
  }

  const val = (form, name) => ((form.elements[name] && form.elements[name].value) || "").trim();
  const isChecked = (form, name) => Boolean(form.elements[name] && form.elements[name].checked);
  const radioVal = (form, name) => { const r = form.querySelector(`input[name="${name}"]:checked`); return r ? r.value : ""; };

  function requireFields(form, fields) {
    for (const [name, message, min = 1] of fields) {
      const v = val(form, name);
      if (v.length < min) {
        const el = form.elements[name];
        if (el && el.focus) el.focus();
        throw new Error(message);
      }
    }
  }

  function checkEmail(value, optional = true) {
    if (!value && optional) return null;
    if (!EMAIL_RE.test(value)) throw new Error("Escribe un correo válido.");
    return value;
  }

  /* ---------------------------------------------------------------- reporte público */
  async function renderReport(mount) {
    mount.classList.add("rep-mount");
    const reasons = await loadReasons();
    const isNna = /proteccion-nna/.test(location.pathname);
    const preset = params.get("motivo") || (isNna ? "involucra_menor" : "");
    const options = GROUPS.map(([g, label]) => {
      const opts = reasons.filter((r) => r.grupo === g)
        .map((r) => `<option value="${esc(r.value)}"${r.value === preset ? " selected" : ""}>${esc(r.label)}</option>`).join("");
      return opts ? `<optgroup label="${esc(label)}">${opts}</optgroup>` : "";
    }).join("");
    const ids = { motivo: nid("motivo"), enlace: nid("enlace"), detalles: nid("detalles"), correo: nid("correo"),
      menor: nid("menor"), csam: nid("csam") };
    mount.innerHTML = `
      <form class="rep-form" novalidate>
        ${field(`<label for="${ids.motivo}">Motivo</label>`,
          `<select id="${ids.motivo}" name="reason" required aria-describedby="${ids.menor} ${ids.csam}"><option value="">Elige un motivo</option>${options}</select>`)}
        <p class="rep-hint rep-note" id="${ids.menor}" data-minor hidden>Lo ocultamos en cuanto lo recibimos y lo revisamos con prioridad.</p>
        <p class="rep-hint rep-note danger" id="${ids.csam}" data-csam hidden>No descargues, copies ni reenvíes el material: solo pega el enlace. Lo aislamos, nunca se muestra ni se envía a sistemas de inteligencia artificial y lo denunciamos ante el Ministerio Público.</p>
        ${field(`<label for="${ids.enlace}">¿Dónde está? <span class="rep-opt">(opcional)</span></label>`,
          `<input id="${ids.enlace}" name="target_url" type="text" inputmode="url" maxlength="1000" autocomplete="off" placeholder="Enlace, o nombre del perro, del Refugio o de la Clínica" value="${esc(params.get("enlace") || "")}">`,
          "Copia el enlace de la publicación, del perfil o de la foto. Si no lo tienes, escribe el nombre.")}
        ${field(`<label for="${ids.detalles}">¿Qué pasa?</label>`,
          `<textarea id="${ids.detalles}" name="details" rows="4" minlength="5" maxlength="2000" required></textarea>`)}
        ${field(`<label for="${ids.correo}">Tu correo <span class="rep-opt">(opcional)</span></label>`,
          `<input id="${ids.correo}" name="email" type="email" maxlength="255" autocomplete="email">`,
          "Si lo dejas, podremos pedirte más datos, avisarte el resultado y podrás consultar el estado con tu folio.")}
        ${honeypot()}
        <p class="rep-hint">No necesitas cuenta. Si alguien está en riesgo inmediato, llama al 911.</p>
        <div class="rep-actions"><button type="submit" class="rep-btn">Enviar reporte</button></div>
        ${statusLine()}
      </form>
      ${trackForm("reporte")}`;
    const form = $(".rep-form", mount);
    const select = form.elements.reason;
    const toggle = () => {
      const r = reasons.find((x) => x.value === select.value);
      $("[data-minor]", form).hidden = !(r && r.oculta_al_reportar);
      $("[data-csam]", form).hidden = select.value !== "abuso_sexual_infantil";
    };
    select.addEventListener("change", toggle);
    toggle();
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      withButton(form, async () => {
        if (!select.value) { select.focus(); throw new Error("Elige un motivo."); }
        requireFields(form, [["details", "Cuéntanos qué pasa (al menos unas palabras).", 5]]);
        const body = { reason: select.value, details: val(form, "details"), target_url: val(form, "target_url") || null,
          email: checkEmail(val(form, "email")), website: val(form, "website") || null };
        const out = await api("/cumplimiento/reportes-publicos", { method: "POST", body });
        ack(mount, "Recibimos tu reporte", out.folio, [out.mensaje]);
      });
    });
    bindTrack(mount, "reporte");
  }

  /* ---------------------------------------------------------------- seguimiento (reporte o apelación) */
  function trackForm(kind) {
    const f = nid("folio"), c = nid("correo");
    const title = kind === "reporte" ? "Consultar el estado de un reporte" : "Consultar el estado de una apelación";
    return `<details class="rep-track" data-track="${kind}"><summary>${title}</summary>
      <form class="rep-form" novalidate>
        <div class="rep-grid">
          ${field(`<label for="${f}">Folio</label>`, `<input id="${f}" name="folio" maxlength="24" autocomplete="off" placeholder="${kind === "reporte" ? "REP-…" : "APE-…"}">`)}
          ${field(`<label for="${c}">Correo que dejaste</label>`, `<input id="${c}" name="email" type="email" maxlength="255" autocomplete="email">`)}
        </div>
        <div class="rep-actions"><button type="submit" class="rep-btn secondary">Consultar</button></div>
        ${statusLine()}
        <div class="rep-result" aria-live="polite"></div>
      </form></details>`;
  }

  function bindTrack(mount, kind) {
    const box = $(`[data-track="${kind}"]`, mount);
    if (!box) return;
    const form = $("form", box);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      withButton(form, async () => {
        requireFields(form, [["folio", "Escribe tu folio.", 4], ["email", "Escribe el correo que dejaste."]]);
        checkEmail(val(form, "email"), false);
        const path = kind === "reporte" ? "/cumplimiento/reportes-publicos/" : "/cumplimiento/apelaciones/";
        const out = await api(`${path}${encodeURIComponent(val(form, "folio").toUpperCase())}?email=${encodeURIComponent(val(form, "email"))}`, { auth: false });
        const lines = [`<p><span class="badge info">${esc(out.estado)}</span></p>`];
        if (out.revision_antes_de) lines.push(`<p>Plazo objetivo de revisión: ${esc(fmtDay(out.revision_antes_de))}.</p>`);
        if (out.responde_antes_de) lines.push(`<p>Te respondemos a más tardar el ${esc(fmtDay(out.responde_antes_de))}.</p>`);
        if (out.respuesta) lines.push(`<p><strong>Respuesta:</strong> ${esc(out.respuesta)}</p>`);
        $(".rep-result", form).innerHTML = lines.join("");
      });
    });
  }

  /* ---------------------------------------------------------------- aviso de derechos de autor */
  function renderNotice(mount) {
    mount.classList.add("rep-mount");
    const ids = { ubicacion: nid("ubicacion"), obra: nid("obra"), hechos: nid("hechos"), nombre: nid("nombre"),
      representado: nid("representado"), documento: nid("documento"), email: nid("email"), alt: nid("alt"),
      tel: nid("tel"), domicilio: nid("domicilio") };
    mount.innerHTML = `
      <h3 class="rep-title">Formulario de aviso</h3>
      <p class="rep-hint">Para quien tiene los derechos. No necesitas cuenta ni certificados de registro del Instituto Nacional del Derecho de Autor ni de ningún otro organismo.</p>
      <form class="rep-form" novalidate>
        ${radios("tipo", [["derechos_autor", "Derechos de autor (foto, texto, ilustración, video u otra obra)"], ["marca", "Marca, logotipo o personaje"]], "derechos_autor", "¿Qué se infringe?")}
        ${field(`<label for="${ids.ubicacion}">Ubicación electrónica del contenido</label>`,
          `<input id="${ids.ubicacion}" name="ubicacion" type="text" inputmode="url" maxlength="1000" required placeholder="Enlace de la publicación, del producto o de la foto">`)}
        ${field(`<label for="${ids.obra}">Obra o derecho que se infringe</label>`, `<textarea id="${ids.obra}" name="obra" rows="2" maxlength="2000" required></textarea>`)}
        ${field(`<label for="${ids.hechos}">Breve descripción de los hechos</label>`, `<textarea id="${ids.hechos}" name="hechos" rows="3" maxlength="4000" required></textarea>`)}
        ${field(`<label for="${ids.nombre}">Tu nombre completo</label>`, `<input id="${ids.nombre}" name="nombre" maxlength="255" autocomplete="name" required>`)}
        ${radios("caracter", [["titular", "Soy titular del derecho"], ["representante", "Actúo como representante"]], "titular", "¿Cómo actúas?")}
        <div class="rep-extra" data-rep hidden>
          ${field(`<label for="${ids.representado}">¿A quién representas?</label>`, `<input id="${ids.representado}" name="representado" maxlength="255">`)}
          ${field(`<label for="${ids.documento}">Documento que te autoriza</label>`, `<textarea id="${ids.documento}" name="documento_representacion" rows="2" maxlength="2000"></textarea>`,
            "Describe o enlaza el poder o la autorización. Si no puedes adjuntarlo aquí, envíalo al correo legal citando tu folio; mientras falte, no retiramos el contenido.")}
        </div>
        <div class="rep-grid">
          ${field(`<label for="${ids.email}">Correo</label>`, `<input id="${ids.email}" name="email" type="email" maxlength="255" autocomplete="email" required>`)}
          ${field(`<label for="${ids.alt}">Correo alterno <span class="rep-opt">(si tienes)</span></label>`, `<input id="${ids.alt}" name="email_alterno" type="email" maxlength="255">`)}
          ${field(`<label for="${ids.tel}">Teléfono</label>`, `<input id="${ids.tel}" name="telefono" type="tel" maxlength="30" autocomplete="tel" required>`)}
        </div>
        ${field(`<label for="${ids.domicilio}">Domicilio</label>`, `<textarea id="${ids.domicilio}" name="domicilio" rows="2" maxlength="1000" autocomplete="street-address" required></textarea>`)}
        <div class="rep-warning"><strong>Declarar en falso tiene multa.</strong> Hacer una declaración falsa en un aviso o contra-aviso se sanciona con multa de 1,000 a 20,000 veces la Unidad de Medida y Actualización (Ley Federal del Derecho de Autor, art. 232 Quinquies, fr. I).</div>
        ${checkbox("bajo_protesta", "Declaro, bajo protesta de decir verdad y de buena fe, que la información es cierta y que soy titular del derecho o estoy autorizado(a) para actuar en su nombre.")}
        ${checkbox("conoce_sancion", "Conozco la sanción por declarar en falso en este aviso (Ley Federal del Derecho de Autor, art. 232 Quinquies).")}
        ${honeypot()}
        <p class="rep-hint">Somos neutrales: si hay una disputa sobre quién tiene los derechos, decide la autoridad.</p>
        <div class="rep-actions"><button type="submit" class="rep-btn">Enviar aviso</button></div>
        ${statusLine()}
      </form>`;
    const form = $(".rep-form", mount);
    const repBox = $("[data-rep]", form);
    form.addEventListener("change", (e) => { if (e.target.name === "caracter") repBox.hidden = radioVal(form, "caracter") !== "representante"; });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      withButton(form, async () => {
        requireFields(form, [["ubicacion", "Pega la ubicación del contenido.", 3], ["obra", "Describe la obra o el derecho.", 3],
          ["hechos", "Describe brevemente los hechos.", 10], ["nombre", "Escribe tu nombre completo.", 3],
          ["email", "Escribe tu correo."], ["telefono", "Escribe tu teléfono.", 8], ["domicilio", "Escribe tu domicilio.", 10]]);
        const caracter = radioVal(form, "caracter");
        if (caracter === "representante" && !val(form, "representado")) throw new Error("Indica a quién representas.");
        if (!isChecked(form, "bajo_protesta") || !isChecked(form, "conoce_sancion")) {
          throw new Error("Marca las dos declaraciones para presentar el aviso.");
        }
        const body = {
          tipo: radioVal(form, "tipo") || "derechos_autor", ubicacion: val(form, "ubicacion"), obra: val(form, "obra"),
          hechos: val(form, "hechos"), nombre: val(form, "nombre"), caracter,
          representado: val(form, "representado") || null, documento_representacion: val(form, "documento_representacion") || null,
          email: checkEmail(val(form, "email"), false), email_alterno: checkEmail(val(form, "email_alterno")),
          telefono: val(form, "telefono"), domicilio: val(form, "domicilio"), bajo_protesta: true, conoce_sancion: true,
          website: val(form, "website") || null,
        };
        const out = await api("/cumplimiento/derechos-autor/avisos", { method: "POST", body, auth: false });
        ack(mount, "Recibimos tu aviso", out.folio, [out.mensaje, out.sha256 ? `Huella SHA-256 de tu aviso: ${out.sha256}` : ""]);
      });
    });
  }

  /* ---------------------------------------------------------------- contra-aviso */
  function renderCounter(mount) {
    mount.classList.add("rep-mount");
    const ids = { folio: nid("folio"), cuenta: nid("cuenta"), nombre: nid("nombre"), representado: nid("representado"),
      email: nid("email"), tel: nid("tel"), domicilio: nid("domicilio"), detalle: nid("detalle") };
    mount.innerHTML = `
      <h3 class="rep-title">Formulario de contra-aviso</h3>
      <p class="rep-hint">Para quien subió el contenido retirado. Usa el folio del aviso de retiro que te enviamos.</p>
      <form class="rep-form" novalidate>
        <div class="rep-grid">
          ${field(`<label for="${ids.folio}">Folio del retiro</label>`, `<input id="${ids.folio}" name="folio" maxlength="24" autocomplete="off" placeholder="DA-… o MOD-…" value="${esc(params.get("contraaviso") || "")}" required>`)}
          ${field(`<label for="${ids.cuenta}">Correo de tu cuenta de GuauWoow</label>`, `<input id="${ids.cuenta}" name="email_cuenta" type="email" maxlength="255" autocomplete="email" required>`)}
        </div>
        ${field(`<label for="${ids.nombre}">Tu nombre</label>`, `<input id="${ids.nombre}" name="nombre" maxlength="255" autocomplete="name" required>`)}
        ${radios("caracter_ca", [["propio", "Actúo por mi cuenta"], ["representante", "Actúo como representante"]], "propio", "¿Cómo actúas?")}
        <div class="rep-extra" data-rep hidden>${field(`<label for="${ids.representado}">¿A quién representas?</label>`, `<input id="${ids.representado}" name="representado" maxlength="255">`)}</div>
        <div class="rep-grid">
          ${field(`<label for="${ids.email}">Correo de contacto <span class="rep-opt">(si es otro)</span></label>`, `<input id="${ids.email}" name="email" type="email" maxlength="255">`)}
          ${field(`<label for="${ids.tel}">Teléfono <span class="rep-opt">(opcional)</span></label>`, `<input id="${ids.tel}" name="telefono" type="tel" maxlength="30" autocomplete="tel">`)}
        </div>
        ${field(`<label for="${ids.domicilio}">Domicilio</label>`, `<textarea id="${ids.domicilio}" name="domicilio" rows="2" maxlength="1000" autocomplete="street-address" required></textarea>`)}
        ${radios("fundamento", [["licencia", "Tengo un contrato o una licencia que me autoriza"], ["excepcion", "El uso está permitido por una excepción de la ley"], ["dominio_publico", "La obra es de dominio público"]], "licencia", "¿Por qué tenías derecho a publicarlo?")}
        ${field(`<label for="${ids.detalle}">Contrato o licencia, o la excepción que ampara el uso</label>`, `<textarea id="${ids.detalle}" name="detalle" rows="3" maxlength="4000" required></textarea>`,
          "Describe o enlaza el documento. Si no puedes adjuntarlo aquí, envíalo al correo legal indicando tu folio.")}
        <div class="rep-warning"><strong>Declarar en falso tiene multa</strong> de 1,000 a 20,000 veces la Unidad de Medida y Actualización (Ley Federal del Derecho de Autor, art. 232 Quinquies, fr. I).</div>
        ${checkbox("bajo_protesta", "Declaro, bajo protesta de decir verdad, que tengo derecho a publicar este contenido por la razón que indiqué.")}
        ${checkbox("conoce_sancion", "Conozco la sanción por declarar en falso en este contra-aviso.")}
        ${honeypot()}
        <p class="rep-hint">Enviamos una copia a quien presentó el aviso. Si no acredita haber iniciado un procedimiento, restauramos el contenido entre 10 y 15 días hábiles después de tu contra-aviso.</p>
        <div class="rep-actions"><button type="submit" class="rep-btn">Enviar contra-aviso</button></div>
        ${statusLine()}
      </form>`;
    const form = $(".rep-form", mount);
    const repBox = $("[data-rep]", form);
    form.addEventListener("change", (e) => { if (e.target.name === "caracter_ca") repBox.hidden = radioVal(form, "caracter_ca") !== "representante"; });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      withButton(form, async () => {
        requireFields(form, [["folio", "Escribe el folio del retiro.", 4], ["email_cuenta", "Escribe el correo de tu cuenta."],
          ["nombre", "Escribe tu nombre.", 3], ["domicilio", "Escribe tu domicilio.", 10],
          ["detalle", "Describe el contrato, la licencia o la excepción.", 10]]);
        const caracter = radioVal(form, "caracter_ca");
        if (caracter === "representante" && !val(form, "representado")) throw new Error("Indica a quién representas.");
        if (!isChecked(form, "bajo_protesta") || !isChecked(form, "conoce_sancion")) {
          throw new Error("Marca las dos declaraciones para presentar el contra-aviso.");
        }
        const body = {
          folio: val(form, "folio").toUpperCase(), email_cuenta: checkEmail(val(form, "email_cuenta"), false),
          nombre: val(form, "nombre"), caracter, representado: val(form, "representado") || null,
          email: checkEmail(val(form, "email")), telefono: val(form, "telefono") || null, domicilio: val(form, "domicilio"),
          fundamento: radioVal(form, "fundamento") || "licencia", detalle: val(form, "detalle"), bajo_protesta: true,
          conoce_sancion: true, website: val(form, "website") || null,
        };
        const out = await api("/cumplimiento/derechos-autor/contra-avisos", { method: "POST", body, auth: false });
        ack(mount, "Recibimos tu contra-aviso", out.folio, [out.mensaje]);
      });
    });
  }

  /* ---------------------------------------------------------------- apelación */
  function renderAppeal(mount) {
    mount.classList.add("rep-mount");
    const ids = { folio: nid("folio"), email: nid("email"), args: nid("args"), pruebas: nid("pruebas") };
    mount.innerHTML = `
      <h3 class="rep-title">Formulario de apelación</h3>
      <p class="rep-hint">Usa el folio del aviso de la medida (empieza con MOD-) y el correo de tu cuenta. Funciona aunque tu cuenta esté suspendida.</p>
      <form class="rep-form" novalidate>
        <div class="rep-grid">
          ${field(`<label for="${ids.folio}">Folio de la medida</label>`, `<input id="${ids.folio}" name="folio" maxlength="24" autocomplete="off" placeholder="MOD-…" value="${esc(params.get("apelacion") || "")}" required>`)}
          ${field(`<label for="${ids.email}">Correo de tu cuenta</label>`, `<input id="${ids.email}" name="email" type="email" maxlength="255" autocomplete="email" required>`)}
        </div>
        ${field(`<label for="${ids.args}">¿Por qué no estás de acuerdo?</label>`, `<textarea id="${ids.args}" name="argumentos" rows="4" minlength="20" maxlength="4000" required></textarea>`)}
        ${field(`<label for="${ids.pruebas}">Pruebas <span class="rep-opt">(opcional)</span></label>`, `<textarea id="${ids.pruebas}" name="pruebas" rows="2" maxlength="2000"></textarea>`,
          "Enlaces o descripción de lo que acredita tu postura.")}
        ${honeypot()}
        <p class="rep-hint">La revisa una persona distinta de quien decidió. Este procedimiento es opcional: no sustituye tu derecho de acudir a la PROFECO o a los tribunales.</p>
        <div class="rep-actions"><button type="submit" class="rep-btn">Enviar apelación</button></div>
        ${statusLine()}
      </form>
      ${trackForm("apelacion")}`;
    const form = $(".rep-form", mount);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      withButton(form, async () => {
        requireFields(form, [["folio", "Escribe el folio de la medida.", 4], ["email", "Escribe el correo de tu cuenta."],
          ["argumentos", "Explica tus argumentos (al menos 20 caracteres).", 20]]);
        const body = { folio: val(form, "folio").toUpperCase(), email: checkEmail(val(form, "email"), false),
          argumentos: val(form, "argumentos"), pruebas: val(form, "pruebas") || null, website: val(form, "website") || null };
        const out = await api("/cumplimiento/apelaciones", { method: "POST", body });
        ack(mount, "Recibimos tu apelación", out.folio, [out.mensaje]);
      });
    });
    bindTrack(mount, "apelacion");
    if (params.get("apelacion")) setTimeout(() => mount.scrollIntoView({ block: "start" }), 0);
  }

  /* ---------------------------------------------------------------- montaje */
  function appealMount() {
    let mount = document.getElementById("form-apelacion");
    if (!mount) {
      const section = document.querySelector("section#apelacion");
      if (!section) return null;
      mount = document.createElement("div");
      mount.id = "form-apelacion";
      section.appendChild(mount);
    }
    return mount;
  }

  function init() {
    const report = document.getElementById("form-reporte-publico");
    if (report) renderReport(report).catch(() => { report.innerHTML = '<p class="rep-status is-error">No pudimos cargar el formulario. Inténtalo de nuevo más tarde.</p>'; });
    const notice = document.getElementById("form-aviso-autor");
    if (notice) renderNotice(notice);
    const counter = document.getElementById("form-contra-aviso");
    if (counter) renderCounter(counter);
    const appeal = appealMount();
    if (appeal) renderAppeal(appeal);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
