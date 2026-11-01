/* ============================================================
   GuauWoow · Centro de solicitudes (contrato K-SOLIC)
   Puntos de montaje en las páginas legales:
     #form-solicitud[data-tipo="arco"]             derechos-arco.html y eliminacion-datos.html
     #form-solicitud[data-tipo="queja"]            atencion-y-quejas.html
     #form-solicitud[data-tipo="retiro_importado"] contenido-importado.html
     #seguimiento-folio                            seguimiento con folio y correo (+ «Mis solicitudes»); si falta,
                                                   se agrega después de #form-solicitud
   Enlaces de los correos:
     ?confirmar=TOKEN        confirma la solicitud (comprueba que la persona controla ese correo)
     ?folio=PF-…&clave=…     contestar lo que pedimos, subir la identificación o descargar «Mis datos»
     ?report=ID              (contenido importado) llega desde «Soy el autor: retirar o reclamar»
   Funciona sin cuenta; si hay sesión de la app (localStorage «patitas_token») se liga a la cuenta.
   API: /cumplimiento/solicitudes… (ver backend/app/routers/cumplimiento_solicitudes.py).
   Sin manejadores en línea (CSP): todo con addEventListener. El texto del usuario siempre va escapado.
   ============================================================ */
"use strict";

(() => {
  const API = "/cumplimiento/solicitudes";
  const TOKEN_KEY = "patitas_token";
  const TZ = "America/Mexico_City";
  const MAX_FILE_MB = 10;
  // Las mismas etiquetas que usan las páginas (derechos-arco.html §3, §10 y §11); el servidor manda las suyas
  const FALLBACK = {
    tipos: {
      acceso: "Acceso", rectificacion: "Rectificación", cancelacion: "Cancelación", oposicion: "Oposición",
      revocacion: "Revocación del consentimiento", limitacion: "Limitación del uso o divulgación",
      queja: "Queja", aclaracion: "Duda o aclaración", retiro_importado: "Retiro de una publicación importada",
    },
    permisos: {
      alertas: "Alertas de perritos perdidos cerca", correos: "Correos promocionales y de novedades",
      whatsapp: "Avisos por WhatsApp", analitica: "Analítica (cookies)", publicidad: "Publicidad por cualquier medio",
      otro: "Otro permiso",
    },
    alcances: { cuenta: "Toda mi cuenta", datos: "Datos específicos", whatsapp: "Mis datos del bot de WhatsApp",
      importado: "Una publicación importada" },
    motivos: { servicio: "El servicio de GuauWoow", compra: "Una compra en la tienda",
      producto_defectuoso: "Un producto que llegó con defecto o no corresponde", donativo: "Un donativo",
      refugio: "Un Refugio o una Casa de paso", otro: "Otro tema" },
    relaciones: { autor: "Soy la persona autora", aparezco: "Aparezco en la publicación", otro: "Otro" },
    plazos: { arco_respuesta_dias_habiles: 20, arco_efectiva_dias_habiles: 15, queja_primera_respuesta_dias_habiles: 2,
      queja_respuesta_dias_habiles: 10, retiro_importado_horas: 72, confirmacion_dias_habiles: 10 },
  };
  const ARCO = ["acceso", "rectificacion", "cancelacion", "oposicion", "revocacion", "limitacion"];
  const ARCO_HELP = {
    acceso: "Saber qué datos tuyos tenemos, para qué los usamos y con quién los compartimos.",
    rectificacion: "Corregir datos inexactos, incompletos o desactualizados. Dinos qué hay que cambiar.",
    cancelacion: "Que borremos tus datos, después del periodo de bloqueo que fija la ley.",
    oposicion: "Que dejemos de usar tus datos para un fin concreto (por ejemplo, el puntaje de compatibilidad).",
    revocacion: "Retirar un permiso que nos diste. No afecta lo que hicimos antes con tu permiso.",
    limitacion: "Pedir que no usemos tus datos para ciertos fines. Con «publicidad» entras al listado de exclusión.",
  };
  let opts = FALLBACK;
  let me = null; // cuenta con sesión iniciada (o null)
  let uid = 0;

  /* ---------------------------------------------------------------- utilidades */
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const id = (p) => `${p}-${++uid}`;
  const token = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
  const params = new URLSearchParams(location.search);
  // El backend guarda UTC sin zona: se agrega la «Z» para que el navegador no lo lea como hora local
  const toDate = (v) => { if (!v) return null; const s = String(v); return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`); };
  const fmtDay = (v) => { const d = toDate(v); return d ? d.toLocaleDateString("es-MX", { timeZone: TZ, day: "numeric", month: "long", year: "numeric" }) : ""; };
  const fmtDateTime = (v) => { const d = toDate(v); return d ? d.toLocaleString("es-MX", { timeZone: TZ, day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " h" : ""; };

  async function api(path, { method = "GET", body, form, auth = true } = {}) {
    const headers = {};
    const tk = auth ? token() : "";
    if (tk) headers.Authorization = `Bearer ${tk}`;
    let payload;
    if (form) payload = form;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    let res;
    try { res = await fetch(path, { method, headers, body: payload, credentials: "same-origin" }); }
    catch { throw new Error("No hay conexión. Revisa tu internet e inténtalo de nuevo."); }
    // Sesión vencida: se reintenta sin cuenta (el formulario funciona igual)
    if (res.status === 401 && tk) { me = null; return api(path, { method, body, form, auth: false }); }
    const type = res.headers.get("content-type") || "";
    const data = type.includes("application/json") ? await res.json().catch(() => null) : null;
    if (!res.ok) {
      let detail = data && data.detail;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join(", ");
      if (typeof detail !== "string" || !detail) {
        detail = res.status === 429 ? "Hiciste muchas solicitudes seguidas. Espera un momento e inténtalo de nuevo."
          : res.status >= 500 ? "No pudimos procesar tu solicitud. Inténtalo de nuevo en unos minutos." : `Error ${res.status}`;
      }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function status(box, text, kind = "info") {
    box.className = `sol-status ${kind}`;
    box.textContent = text;
    box.hidden = !text;
    if (text && kind === "error") box.focus();
  }

  function options(map, selected) {
    return Object.entries(map).map(([k, v]) => `<option value="${esc(k)}"${k === selected ? " selected" : ""}>${esc(v)}</option>`).join("");
  }

  function field(label, control, hint = "") {
    return `<div class="sol-field">${label}${control}${hint ? `<p class="sol-hint">${hint}</p>` : ""}</div>`;
  }

  /* ---------------------------------------------------------------- formulario */
  function contactFields(kind) {
    const n = id("sol-nombre"), e = id("sol-email"), t = id("sol-tel");
    const account = me ? `<p class="sol-account">Enviarás la solicitud con tu cuenta (<strong>${esc(me.email)}</strong>). Te responderemos a ese correo y la verás en «Mis solicitudes».</p>` : "";
    const phoneHint = kind === "queja" ? "Opcional. Para llamarte si hace falta."
      : "Opcional. Si solo usaste el bot de WhatsApp, escribe ese número.";
    return `${account}
      <div class="sol-grid">
        ${field(`<label for="${n}">Nombre completo</label>`, `<input id="${n}" name="nombre" autocomplete="name" required minlength="3" maxlength="120" value="${esc(me ? me.full_name : "")}">`)}
        ${field(`<label for="${e}">Correo para responderte</label>`, `<input id="${e}" name="email" type="email" autocomplete="email" required maxlength="255" value="${esc(me ? me.email : "")}"${me ? " readonly" : ""}>`)}
      </div>
      ${kind === "retiro_importado" ? "" : field(`<label for="${t}">Teléfono o WhatsApp</label>`, `<input id="${t}" name="telefono" type="tel" autocomplete="tel" maxlength="30" inputmode="tel">`, phoneHint)}`;
  }

  function privacyFields() {
    const p = id("sol-priv");
    return `${me ? "" : `<div class="sol-check"><input type="checkbox" id="${p}" name="acepta_privacidad"><label for="${p}">Leí el <a href="privacidad.html">Aviso de Privacidad</a> y acepto que GuauWoow use estos datos para atender y dar seguimiento a mi solicitud.</label></div>`}
      <div class="sol-hp" aria-hidden="true"><label>Deja este campo vacío<input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>`;
  }

  function arcoForm(root) {
    const t = id("sol-tipo"), d = id("sol-desc"), rep = id("sol-rep"), titular = id("sol-titular");
    const preset = params.get("tipo") || (/eliminacion-datos/.test(location.pathname) ? "cancelacion" : "acceso");
    const permisos = Object.entries(opts.permisos).map(([k, v]) => {
      const cid = id("sol-perm");
      return `<div class="sol-check"><input type="checkbox" id="${cid}" name="permisos" value="${esc(k)}"><label for="${cid}">${esc(v)}${k === "publicidad" ? " (listado de exclusión)" : ""}</label></div>`;
    }).join("");
    const alcances = Object.entries(opts.alcances).map(([k, v]) => {
      const rid = id("sol-alc");
      return `<div class="sol-check"><input type="radio" id="${rid}" name="alcance" value="${esc(k)}"${k === (/eliminacion-datos/.test(location.pathname) ? "whatsapp" : "datos") ? " checked" : ""}><label for="${rid}">${esc(v)}</label></div>`;
    }).join("");
    const pub = id("sol-pub");
    root.innerHTML = `
      <form class="sol-form" novalidate>
        ${field(`<label for="${t}">¿Qué derecho quieres ejercer?</label>`, `<select id="${t}" name="tipo">${options(Object.fromEntries(ARCO.map((k) => [k, opts.tipos[k] || k])), ARCO.includes(preset) ? preset : "acceso")}</select>`, `<span data-help></span>`)}
        <fieldset class="sol-extra" data-for="revocacion limitacion"><legend>¿Qué permiso retiras o qué uso quieres limitar?</legend>${permisos}
          <p class="sol-hint">La analítica también la apagas tú mismo en «Preferencias de cookies», al pie de cada página.</p></fieldset>
        <fieldset class="sol-extra" data-for="cancelacion"><legend>¿Qué quieres que borremos?</legend>${alcances}
          <p class="sol-hint" data-importado hidden>Para una publicación importada de Facebook usa mejor el formulario de <a href="contenido-importado.html">Contenido importado</a>: la retiramos en menos de 72 horas.</p></fieldset>
        <div class="sol-extra" data-for="acceso"><div class="sol-check"><input type="checkbox" id="${pub}" name="publicidad"><label for="${pub}">Quiero saber también si usaron mi información para publicidad y con quién la compartieron (LFPC, art. 16).</label></div></div>
        ${contactFields("arco")}
        ${field(`<label for="${d}">Describe tu solicitud</label>`, `<textarea id="${d}" name="descripcion" rows="5" required minlength="10" maxlength="4000"></textarea>`,
          "Di sobre qué datos pides algo y agrega lo que nos ayude a encontrarlos: el correo de tu cuenta, el enlace a una publicación o el número de un pedido. Si pides una corrección, dinos qué hay que cambiar.")}
        <div class="sol-check"><input type="checkbox" id="${rep}" name="representante"><label for="${rep}">Presento la solicitud en representación de otra persona.</label></div>
        <div class="sol-extra" data-rep hidden>${field(`<label for="${titular}">Nombre de la persona titular de los datos</label>`, `<input id="${titular}" name="nombre_titular" maxlength="120">`,
          "Te pediremos su identificación, la tuya y el documento que acredite la representación (poder ante notario o carta poder firmada ante dos testigos).")}</div>
        ${privacyFields()}
        <p class="sol-hint">Es gratis. Te enviamos un acuse con tu folio. Respondemos en un máximo de ${esc(opts.plazos.arco_respuesta_dias_habiles)} días hábiles y, si procede, lo hacemos efectivo en los ${esc(opts.plazos.arco_efectiva_dias_habiles)} días hábiles siguientes.${me ? "" : " Para comprobar que eres tú, te pediremos confirmar la solicitud desde tu correo."}</p>
        <div class="sol-actions"><button type="submit" class="sol-btn">Enviar solicitud</button></div>
        <p class="sol-status" role="status" aria-live="polite" tabindex="-1" hidden></p>
      </form>`;
    const form = $("form", root);
    const sync = () => {
      const kind = form.tipo.value;
      form.querySelectorAll(".sol-extra[data-for]").forEach((el) => { el.hidden = !el.dataset.for.split(" ").includes(kind); });
      $("[data-help]", form).textContent = ARCO_HELP[kind] || "";
      const alc = form.querySelector("input[name=alcance]:checked");
      $("[data-importado]", form).hidden = !(alc && alc.value === "importado");
      $("[data-rep]", form).hidden = !form.representante.checked;
      // Limitación: «publicidad» marcada de entrada (es el caso del listado de exclusión)
    };
    form.addEventListener("change", sync);
    sync();
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const kind = form.tipo.value;
      const body = common(form, kind);
      if (!body) return;
      if (kind === "revocacion" || kind === "limitacion") {
        body.permisos = [...form.querySelectorAll("input[name=permisos]:checked")].map((i) => i.value);
        if (!body.permisos.length) return fail(form, "Elige qué permiso retiras o qué uso quieres limitar.");
      }
      if (kind === "cancelacion") { const a = form.querySelector("input[name=alcance]:checked"); body.alcance = a ? a.value : "datos"; }
      if (kind === "acceso") body.publicidad = form.publicidad.checked;
      if (form.representante.checked) {
        body.actua_como = "representante";
        body.nombre_titular = form.nombre_titular.value.trim();
        if (body.nombre_titular.length < 3) return fail(form, "Escribe el nombre de la persona titular a la que representas.");
      }
      send(form, root, body);
    });
  }

  function quejaForm(root) {
    const t = id("sol-tipo"), m = id("sol-motivo"), p = id("sol-pedido"), d = id("sol-desc");
    root.innerHTML = `
      <form class="sol-form" novalidate>
        <div class="sol-grid">
          ${field(`<label for="${t}">Tipo</label>`, `<select id="${t}" name="tipo">${options({ queja: opts.tipos.queja, aclaracion: opts.tipos.aclaracion }, "queja")}</select>`)}
          ${field(`<label for="${m}">¿Sobre qué es?</label>`, `<select id="${m}" name="motivo">${options(opts.motivos, "servicio")}</select>`)}
        </div>
        ${field(`<label for="${p}">Número de pedido o de folio anterior</label>`, `<input id="${p}" name="pedido" inputmode="numeric" maxlength="20">`, "Opcional.")}
        ${contactFields("queja")}
        ${field(`<label for="${d}">Cuéntanos qué pasó</label>`, `<textarea id="${d}" name="descripcion" rows="5" required minlength="10" maxlength="4000"></textarea>`,
          "Incluye la fecha y lo que esperas que hagamos. Si tienes capturas o fotos, te las pediremos por correo con tu folio.")}
        ${privacyFields()}
        <p class="sol-hint" data-plazo></p>
        <div class="sol-actions"><button type="submit" class="sol-btn">Enviar</button></div>
        <p class="sol-status" role="status" aria-live="polite" tabindex="-1" hidden></p>
      </form>`;
    const form = $("form", root);
    const sync = () => {
      const pz = opts.plazos;
      $("[data-plazo]", form).textContent = `Es gratis. Recibirás un folio. Primera respuesta en ${pz.queja_primera_respuesta_dias_habiles} días hábiles y respuesta en un máximo de ${pz.queja_respuesta_dias_habiles} días hábiles`
        + (form.motivo.value === "producto_defectuoso" ? "; si el producto llegó con defecto, la reclamación se resuelve en un máximo de 15 días naturales." : ".");
    };
    form.addEventListener("change", sync);
    sync();
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const body = common(form, form.tipo.value);
      if (!body) return;
      body.motivo = form.motivo.value;
      const pedido = form.pedido.value.trim();
      if (/^\d{1,9}$/.test(pedido)) body.pedido_id = Number(pedido);
      else if (pedido) body.descripcion = `${body.descripcion}\n\nPedido o folio: ${pedido}`;
      send(form, root, body);
    });
  }

  function retiroForm(root) {
    const u = id("sol-enlace"), d = id("sol-desc");
    const report = params.get("report") || params.get("report_id");  // compartir.js enlaza con ?report_id=
    const rel = Object.entries(opts.relaciones).map(([k, v], i) => {
      const rid = id("sol-rel");
      return `<div class="sol-check"><input type="radio" id="${rid}" name="relacion" value="${esc(k)}"${i === 0 ? " checked" : ""}><label for="${rid}">${esc(v)}</label></div>`;
    }).join("");
    const prefill = /^\d{1,10}$/.test(report || "") ? `${location.origin}/app/?report=${report}` : "";
    root.innerHTML = `
      <form class="sol-form" novalidate>
        ${field(`<label for="${u}">Enlace a la publicación original o al reporte en GuauWoow</label>`, `<input id="${u}" name="enlace" type="url" inputmode="url" required maxlength="1000" value="${esc(prefill)}" placeholder="https://www.facebook.com/groups/…">`)}
        <fieldset><legend>Tu relación con la publicación</legend>${rel}</fieldset>
        ${contactFields("retiro_importado")}
        ${field(`<label for="${d}">Comentario</label>`, `<textarea id="${d}" name="descripcion" rows="3" maxlength="4000"></textarea>`, "Opcional. Por ejemplo, si quieres que corrijamos algo en lugar de retirarla.")}
        ${privacyFields()}
        <p class="sol-hint">Sin cuenta. La ocultamos en cuanto la recibimos. Si eres la persona autora, borramos su texto y sus fotos en menos de ${esc(opts.plazos.retiro_importado_horas)} horas. Si solo apareces en ella, te respondemos en un máximo de ${esc(opts.plazos.arco_respuesta_dias_habiles)} días hábiles.</p>
        <div class="sol-actions"><button type="submit" class="sol-btn">Pedir el retiro</button></div>
        <p class="sol-status" role="status" aria-live="polite" tabindex="-1" hidden></p>
      </form>`;
    const form = $("form", root);
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const comment = form.descripcion.value.trim();
      const relation = (form.querySelector("input[name=relacion]:checked") || {}).value || "autor";
      form.descripcion.value = comment;
      const body = common(form, "retiro_importado", true);
      if (!body) return;
      const link = form.enlace.value.trim();
      if (!/^https?:\/\/\S+$/i.test(link)) return fail(form, "Pega el enlace completo a la publicación (empieza con https://).");
      body.enlace = link;
      body.relacion = relation;
      const m = link.match(/[?&#]report=(\d{1,10})\b/);
      if (m) body.report_id = Number(m[1]);
      body.descripcion = `Pido el retiro de una publicación importada. ${opts.relaciones[relation] || ""}.${comment ? ` ${comment}` : ""}`;
      send(form, root, body);
    });
  }

  function fail(form, msg) {
    status($(".sol-status", form), msg, "error");
    return null;
  }

  function common(form, kind, optionalDescription = false) {
    const body = {
      tipo: kind, nombre: form.nombre.value.trim(), email: form.email.value.trim(),
      descripcion: form.descripcion.value.trim(), website: form.website.value,
    };
    if (form.telefono && form.telefono.value.trim()) body.telefono = form.telefono.value.trim();
    if (body.nombre.length < 3) return fail(form, "Escribe tu nombre completo.");
    if (!/^[^@\s<>"']+@[^@\s<>"']+\.[^@\s<>"']{2,}$/.test(body.email)) return fail(form, "Escribe un correo válido para enviarte el acuse.");
    if (!optionalDescription && body.descripcion.length < 10) return fail(form, "Cuéntanos con un poco más de detalle (mínimo 10 caracteres).");
    if (!me) {
      if (!form.acepta_privacidad.checked) return fail(form, "Acepta el Aviso de Privacidad para enviar tu solicitud.");
      body.acepta_privacidad = true;
    }
    return body;
  }

  async function send(form, root, body) {
    const btn = $("button[type=submit]", form);
    const box = $(".sol-status", form);
    btn.disabled = true;
    status(box, "Enviando…");
    try {
      const ack = await api(API, { method: "POST", body });
      renderAck(root, ack, body.email);
    } catch (err) {
      status(box, err.message, "error");
    } finally { btn.disabled = false; }
  }

  function renderAck(root, ack, email) {
    const first = ack.primera_respuesta_antes_de ? `<li>Primera respuesta a más tardar el <strong>${esc(fmtDay(ack.primera_respuesta_antes_de))}</strong>.</li>` : "";
    const deadline = ack.tipo === "retiro_importado" && ack.publicacion_oculta
      ? "" : `<li>Fecha límite de respuesta: <strong>${esc(fmtDay(ack.responde_antes_de))}</strong>.</li>`;
    root.innerHTML = `
      <div class="sol-ack" role="status" tabindex="-1">
        <p class="sol-ack-title">Recibimos tu solicitud</p>
        <p class="sol-folio">Folio <strong>${esc(ack.folio)}</strong></p>
        <ul>
          <li>Tipo: ${esc(opts.tipos[ack.tipo] || ack.tipo)}.</li>
          <li>Recibida el ${esc(fmtDateTime(ack.recibida_en))}.</li>
          ${first}${deadline}
        </ul>
        <p>${esc(ack.mensaje)}</p>
        ${ack.requiere_confirmacion ? `<p class="sol-warn">Revisa tu correo (también la carpeta de no deseados) y abre el enlace para confirmar. Si no la confirmas en ${esc(opts.plazos.confirmacion_dias_habiles)} días hábiles, tendremos que cerrarla.</p>` : ""}
        <p class="sol-hint">Guarda tu folio: con él y tu correo puedes ver el estado de tu solicitud.</p>
        <div class="sol-actions"><button type="button" class="sol-btn ghost" data-new>Enviar otra solicitud</button></div>
      </div>`;
    const ackBox = $(".sol-ack", root);
    ackBox.focus();
    $("[data-new]", root).addEventListener("click", () => mountForm(root));
    const tracker = $("#seguimiento-folio");
    if (tracker) {
      const f = $("form.sol-track", tracker);
      if (f) { f.folio.value = ack.folio; f.email.value = email || ""; }
    }
  }

  function mountForm(root) {
    const kind = root.dataset.tipo;
    if (kind === "queja") quejaForm(root);
    else if (kind === "retiro_importado") retiroForm(root);
    else arcoForm(root);
  }

  /* ---------------------------------------------------------------- seguimiento */
  function timeline(view) {
    const items = (view.historial || []).map((h) => `<li><span class="sol-tl-date">${esc(fmtDateTime(h.fecha))}</span> ${esc(h.texto)}${h.nota ? `<span class="sol-tl-note">${esc(h.nota)}</span>` : ""}</li>`).join("");
    const rows = [
      ["Tipo", view.tipo_texto],
      ["Estado", view.estado_texto + (view.resultado_texto ? ` · ${view.resultado_texto}` : "")],
      ["Recibida", fmtDateTime(view.recibida_en)],
    ];
    if (view.primera_respuesta_antes_de && !["efectiva", "cerrada"].includes(view.estado)) rows.push(["Primera respuesta a más tardar", fmtDay(view.primera_respuesta_antes_de)]);
    if (!["efectiva", "cerrada"].includes(view.estado) && view.estado !== "respondida") rows.push(["Fecha límite de respuesta", fmtDay(view.responde_antes_de) + (view.plazo_ampliado ? " (ampliado una vez)" : "")]);
    if (view.efectiva_antes_de && view.estado === "respondida") rows.push(["Se hará efectiva a más tardar", fmtDay(view.efectiva_antes_de)]);
    if (view.esperando_tu_respuesta) rows.push(["Esperamos tu información antes del", fmtDay(view.informacion_antes_de)]);
    if (view.cerrada_en) rows.push(["Cerrada", fmtDateTime(view.cerrada_en)]);
    if (!view.identidad_confirmada && !["efectiva", "cerrada"].includes(view.estado)) rows.push(["Identidad", "Falta confirmar desde tu correo"]);
    return `
      <dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${view.respuesta ? `<div class="sol-answer"><p class="sol-ack-title">Nuestra respuesta</p><p>${esc(view.respuesta)}</p></div>` : ""}
      <h4 class="sol-h">Historial</h4><ol class="sol-tl">${items}</ol>
      ${view.respuesta ? "" : `<p class="sol-hint">El detalle de cada respuesta te llega por correo.</p>`}`;
  }

  function trackerForm(root) {
    const f = id("sol-tf"), e = id("sol-te");
    root.innerHTML = `
      <form class="sol-track" novalidate>
        <div class="sol-grid">
          ${field(`<label for="${f}">Folio</label>`, `<input id="${f}" name="folio" required maxlength="20" placeholder="PF-2026-00001" autocapitalize="characters" value="${esc(params.get("folio") || "")}">`)}
          ${field(`<label for="${e}">Correo de la solicitud</label>`, `<input id="${e}" name="email" type="email" autocomplete="email" required maxlength="255" value="${esc(me ? me.email : "")}">`)}
        </div>
        <div class="sol-actions"><button type="submit" class="sol-btn">Consultar</button></div>
        <p class="sol-status" role="status" aria-live="polite" tabindex="-1" hidden></p>
      </form>
      <div class="sol-result" aria-live="polite"></div>
      <div class="sol-mine"></div>`;
    const form = $("form", root);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const folio = form.folio.value.trim().toUpperCase().replace(/\s+/g, "");
      const email = form.email.value.trim();
      const box = $(".sol-status", form);
      if (!/^PF-\d{4}-\d{5,}$/.test(folio)) return status(box, "El folio tiene la forma PF-2026-00001.", "error");
      if (!email) return status(box, "Escribe el correo con el que enviaste la solicitud.", "error");
      status(box, "Buscando…");
      try {
        const view = await api(`${API}/${encodeURIComponent(folio)}?email=${encodeURIComponent(email)}`);
        status(box, "");
        $(".sol-result", root).innerHTML = `<h4 class="sol-h">Folio ${esc(view.folio)}</h4>${timeline(view)}`;
      } catch (err) {
        $(".sol-result", root).innerHTML = "";
        status(box, err.message, "error");
      }
    });
    if (me) loadMine(root);
  }

  async function loadMine(root) {
    const box = $(".sol-mine", root);
    try {
      const list = await api(`${API}/mias`);
      if (!list.length) {
        box.innerHTML = location.hash === "#mis-solicitudes"
          ? `<h4 class="sol-h" id="mis-solicitudes">Mis solicitudes</h4><p class="sol-hint">Aún no tienes solicitudes con esta cuenta. Usa el formulario de esta página para enviar una.</p>` : "";
        if (location.hash === "#mis-solicitudes") box.scrollIntoView({ block: "start" });
        return;
      }
      box.innerHTML = `<h4 class="sol-h" id="mis-solicitudes">Mis solicitudes</h4>` + list.map((v) => `
        <details class="sol-item">
          <summary><strong>${esc(v.folio)}</strong> · ${esc(v.tipo_texto)} · <span class="badge ${v.estado === "efectiva" || v.estado === "cerrada" ? "ok" : v.esperando_tu_respuesta ? "warn" : "pend"}">${esc(v.estado_texto)}</span></summary>
          ${v.descripcion ? `<p class="sol-desc">${esc(v.descripcion)}</p>` : ""}
          ${timeline(v)}
          ${v.pendiente && (v.pendiente.informacion || v.pendiente.identificacion || v.pendiente.descarga) ? `<div data-panel="${esc(v.folio)}"></div>` : ""}
        </details>`).join("");
      list.forEach((v) => { const p = box.querySelector(`[data-panel="${CSS.escape(v.folio)}"]`); if (p) actionPanel(p, v, null); });
      if (location.hash === "#mis-solicitudes") {
        const first = box.querySelector("details");
        if (first) first.open = true;
        box.scrollIntoView({ block: "start" });
      }
    } catch { box.innerHTML = ""; }
  }

  /* ---------------------------------------------------------------- enlaces del correo */
  async function handleConfirm(target) {
    const tk = params.get("confirmar");
    if (!tk) return;
    stripParams(["confirmar"]);
    const note = document.createElement("div");
    note.className = "sol-ack";
    note.setAttribute("role", "status");
    note.tabIndex = -1;
    target.prepend(note);
    note.textContent = "Confirmando tu solicitud…";
    try {
      const view = await api(`${API}/confirmar`, { method: "POST", body: { token: tk }, auth: false });
      note.innerHTML = `<p class="sol-ack-title">¡Listo! Confirmaste tu solicitud ${esc(view.folio)}</p>
        <p>Ya comprobamos que este correo es tuyo. Te responderemos a más tardar el <strong>${esc(fmtDay(view.responde_antes_de))}</strong>.</p>`;
    } catch (err) {
      note.className = "sol-ack error";
      note.textContent = err.message;
    }
    note.focus();
  }

  async function handleAccessLink(target) {
    const folio = params.get("folio"), clave = params.get("clave");
    if (!folio || !clave) return;
    stripParams(["clave"]);
    const panel = document.createElement("div");
    panel.className = "sol-ack";
    target.prepend(panel);
    try {
      const view = await api(`${API}/${encodeURIComponent(folio)}/acceso?clave=${encodeURIComponent(clave)}`, { auth: false });
      actionPanel(panel, view, clave);
    } catch (err) {
      panel.className = "sol-ack error";
      panel.textContent = err.message;
    }
  }

  function actionPanel(panel, view, clave) {
    const p = view.pendiente || {};
    const fileId = id("sol-file"), msgId = id("sol-msg");
    panel.innerHTML = `
      <p class="sol-ack-title">Solicitud ${esc(view.folio)} · ${esc(view.tipo_texto)}</p>
      ${view.lo_que_pedimos && p.informacion ? `<div class="sol-answer"><p class="sol-ack-title">Lo que te pedimos</p><p>${esc(view.lo_que_pedimos)}</p></div>` : ""}
      ${p.descarga ? `<p>Tu solicitud de acceso procede. Descarga tus datos en formato JSON (el mismo archivo de «Perfil → Descargar mis datos»).</p>
        <div class="sol-actions"><button type="button" class="sol-btn" data-download>Descargar mis datos</button></div>` : ""}
      ${p.responder && (p.informacion || p.identificacion || clave) ? `
      <form class="sol-form" novalidate>
        ${field(`<label for="${msgId}">${p.informacion ? "Tu respuesta" : "Escríbenos"}</label>`, `<textarea id="${msgId}" name="mensaje" rows="4" maxlength="4000"></textarea>`)}
        ${p.identificacion ? field(`<label for="${fileId}">Identificación oficial (PDF, JPG, PNG o WebP; máximo ${MAX_FILE_MB} MB)</label>`, `<input id="${fileId}" name="archivo" type="file" accept="application/pdf,image/jpeg,image/png,image/webp">`,
          "Puedes tapar la CURP, la clave de elector y lo que no haga falta. La usamos solo para comprobar quién eres y la borramos al terminar; queda solo una constancia.") : ""}
        <div class="sol-actions"><button type="submit" class="sol-btn">Enviar</button></div>
        <p class="sol-status" role="status" aria-live="polite" tabindex="-1" hidden></p>
      </form>` : ""}
      ${!p.descarga && !p.responder ? `<p>Esta solicitud ya está cerrada.</p>` : ""}`;
    const dl = $("[data-download]", panel);
    if (dl) dl.addEventListener("click", () => download(view.folio, clave, dl));
    const form = $("form", panel);
    if (!form) return;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const box = $(".sol-status", form);
      const fd = new FormData();
      if (clave) fd.append("clave", clave);
      fd.append("mensaje", form.mensaje.value.trim());
      const file = form.archivo && form.archivo.files[0];
      if (file) {
        if (file.size > MAX_FILE_MB * 1024 * 1024) return status(box, `El archivo debe pesar menos de ${MAX_FILE_MB} MB.`, "error");
        fd.append("archivo", file);
      }
      if (!form.mensaje.value.trim() && !file) return status(box, "Escribe tu respuesta o adjunta el documento.", "error");
      const btn = $("button[type=submit]", form);
      btn.disabled = true;
      status(box, "Enviando…");
      try {
        const updated = await api(`${API}/${encodeURIComponent(view.folio)}/respuesta`, { method: "POST", form: fd, auth: !clave });
        form.reset();
        status(box, `Recibimos tu respuesta. Te responderemos a más tardar el ${fmtDay(updated.responde_antes_de)}.`, "ok");
      } catch (err) { status(box, err.message, "error"); }
      finally { btn.disabled = false; }
    });
  }

  async function download(folio, clave, btn) {
    btn.disabled = true;
    try {
      const headers = {};
      const tk = clave ? "" : token();
      if (tk) headers.Authorization = `Bearer ${tk}`;
      const q = clave ? `?clave=${encodeURIComponent(clave)}` : "";
      const res = await fetch(`${API}/${encodeURIComponent(folio)}/descarga${q}`, { headers, credentials: "same-origin" });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error((data && typeof data.detail === "string" && data.detail) || "No pudimos generar tu archivo.");
      }
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `guauwoow-mis-datos-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    } catch (err) { alert(err.message); }
    finally { btn.disabled = false; }
  }

  // Los tokens de los correos no se quedan en la barra de direcciones ni en el historial
  function stripParams(keys) {
    try {
      const url = new URL(location.href);
      keys.forEach((k) => url.searchParams.delete(k));
      history.replaceState(null, "", url.pathname + (url.search ? url.search : "") + url.hash);
    } catch { /* sin History API: no pasa nada */ }
  }

  /* ---------------------------------------------------------------- arranque */
  // Si la página trae el formulario pero no el seguimiento (contenido-importado, eliminacion-datos), se agrega
  // después del formulario: todas las páginas prometen dar seguimiento con el folio
  function trackerMount(formRoot) {
    let tracker = document.getElementById("seguimiento-folio");
    if (!tracker && formRoot) {
      tracker = document.createElement("div");
      tracker.id = "seguimiento-folio";
      formRoot.insertAdjacentElement("afterend", tracker);
    }
    return tracker;
  }

  async function init() {
    const formRoot = document.getElementById("form-solicitud");
    const tracker = trackerMount(formRoot);
    if (!formRoot && !tracker) return;
    if (formRoot && formRoot.dataset.solMounted) return; // el script puede venir dos veces en la misma página
    if (formRoot) formRoot.dataset.solMounted = "1";
    const loads = [api(`${API}/opciones`, { auth: false }).then((o) => { opts = { ...FALLBACK, ...o, plazos: { ...FALLBACK.plazos, ...(o.plazos || {}) } }; }).catch(() => {})];
    if (token()) loads.push(api("/users/me").then((u) => { me = u && u.email && !/\.invalid$/.test(u.email) ? u : null; }).catch(() => { me = null; }));
    await Promise.all(loads);
    if (formRoot) mountForm(formRoot);
    if (tracker) trackerForm(tracker);
    const target = tracker || formRoot;
    await handleConfirm(target);
    await handleAccessLink(target);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
