"""Bot de WhatsApp de GuauWoow.

Flujo (estado en BotInteraction; se reinicia tras 24 h sin actividad o con "hola"/"menú"):
  primer contacto (y de nuevo tras 12 meses): aviso de privacidad simplificado en un mensaje aparte
      (privacidad-simplificado.html §5.1); su versión y fecha quedan en data["notice_v"] y data["notice_at"]
  menú -> 1) Perdí a mi perro  2) Encontré un perro  3) Quiero adoptar
  perdido/encontrado: fotos (1 a 3, "listo" para seguir) -> ubicación (pin o texto) -> nombre/señas (o "no sé")
      -> aviso de que el reporte será público y respuesta PUBLICAR (privacidad-whatsapp.html §4): solo entonces se
         crea el reporte, se analiza la foto con IA y se buscan coincidencias -> pregunta de avisos por este chat
  adoptar: el bot no gestiona adopciones (terminos.html 11.3): solo envía el enlace a la app
"""
import datetime
import logging
import unicodedata

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.data import estados_mx
from app.models import BotInteraction, LostReport
from app.services import facebook_groups, images, matching, whatsapp_api
from app.services.background import dispatch

logger = logging.getLogger(__name__)

IDLE_RESET = datetime.timedelta(hours=24)
MAX_PHOTOS = 3
GREETINGS = {"hola", "menu", "inicio", "empezar", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hi", "hello", "ayuda"}
# Comandos de permisos (comunicaciones.html §5, privacidad-whatsapp.html): BAJA/ALTA/ELIMINAR/PERSONA.
# HOLA reabre la conversación pero NO reactiva los avisos; solo ALTA.
OPT_OUT_WORDS = {"baja", "stop", "alto", "cancelar", "darme de baja", "dar de baja", "dame de baja", "unsubscribe",
                 "no me escriban", "no me escribas", "no me manden mensajes", "ya no me escriban", "no quiero avisos"}
OPT_IN_WORDS = {"alta", "darme de alta", "dar de alta", "quiero avisos", "start"}
DELETE_WORDS = {"eliminar", "borrar mis datos", "eliminar mis datos", "borrar"}
HUMAN_WORDS = {"persona", "humano", "hablar con una persona", "hablar con alguien", "agente", "asesor"}
CONFIRM_WORDS = {"si", "si eliminar", "si, eliminar", "confirmo", "si confirmo", "eliminar"}
CANCEL_DELETE_WORDS = {"no", "cancelar", "menu", "no gracias"}
OPT_OUT_TEXT = ("Listo, ya no te enviaremos avisos por WhatsApp. Si quieres volver a recibirlos, escribe *ALTA*. "
                "Escribir HOLA abre el menú, pero no reactiva los avisos.")
OPT_IN_TEXT = ("Listo, volverás a recibir avisos por WhatsApp: posibles coincidencias con tus reportes y, si activaste "
               "las alertas cercanas, perritos perdidos cerca. Solo avisos útiles, nunca publicidad. Escribe *BAJA* "
               "para dejar de recibirlos.")
DELETE_CONFIRM_TEXT = (
    "¿Quieres que borremos tus datos del bot? 🗑️\n\n"
    "Borraremos al momento la conversación, las fotos y la ubicación que nos enviaste por aquí, retiraremos los "
    "reportes creados desde este número y apagaremos tus avisos por WhatsApp. Te daremos un folio para dar "
    "seguimiento.\n\nResponde *SÍ* para confirmar o *NO* para cancelar."
)
HUMAN_HANDOFF_COOLDOWN = 60 * 60  # un aviso al equipo por número y hora
SKIP_WORDS = {"no se", "nose", "no lo se", "ninguno", "nada", "no", "saltar", "omitir"}
# Pregunta de permiso al terminar un reporte (privacidad-whatsapp.html §5): sin un «sí» no hay avisos proactivos
ALERTS_QUESTION = "¿Quieres que te avisemos por este chat si alguien reporta un perro parecido?"
ALERTS_BUTTONS = [{"id": "alerts_yes", "title": "Sí, avísenme"}, {"id": "alerts_no", "title": "No, gracias"}]
ALERTS_YES_WORDS = {"si", "si avisenme", "si, avisenme", "si quiero", "claro", "por favor", "si por favor"}
ALERTS_NO_WORDS = {"no", "no gracias", "no, gracias", "no quiero"}
ALERTS_YES_TEXT = ("Listo 💛 Te escribiremos por este chat si alguien reporta un perro parecido. Solo avisos útiles, "
                   "nunca publicidad. Escribe *BAJA* cuando quieras dejar de recibirlos.\n\nEscribe *menú* para "
                   "hacer otra cosa.")
ALERTS_NO_TEXT = ("Entendido, no te escribiremos por iniciativa propia. Si cambias de opinión escribe *ALTA*. "
                  "Puedes ver tu reporte con el enlace que te enviamos.\n\nEscribe *menú* para hacer otra cosa.")
# Aceptación antes de publicar (privacidad-whatsapp.html §4; terminos.html 11.3): sin PUBLICAR no se crea el reporte
PUBLISH_BUTTONS = [{"id": "publish_yes", "title": "Publicar"}, {"id": "publish_no", "title": "No publicar"}]
PUBLISH_WORDS = {"publicar", "publicalo", "publica", "si publicar", "si, publicar", "si", "acepto", "si acepto"}
DISCARD_WORDS = {"no", "no publicar", "no gracias", "descartar", "cancelar", "no lo publiques"}
DISCARD_TEXT = ("Listo, no publicamos nada. Las fotos que enviaste no quedan en ningún reporte y se borran solas en un "
                "máximo de 2 días. Escribe *menú* para empezar de nuevo.")
ADOPT_TEXT = ("¡Qué alegría que quieras adoptar! 🐶💛 Adoptar es gratis y se hace en la app, donde ves a los perritos, "
              "te postulas y hablas con quien los cuida: {link}\n\nEscribe *menú* para volver.")
# Aviso de privacidad del bot: versión de privacidad-simplificado.html §5.1 (texto-bot); se repite a los 12 meses
NOTICE_VERSION = "2026-10-17"
NOTICE_MAX_AGE = datetime.timedelta(days=365)
# Lo que sobrevive al reinicio de la conversación (24 h sin actividad, "hola" o "menú")
KEEP_KEYS = ("name", "notice_v", "notice_at")
AGE_LIMITED_TEXT = ("Tu cuenta de GuauWoow está limitada mientras confirmas tu edad, así que por ahora no podemos "
                    "publicar reportes desde este número. Entra a la app para confirmarla y vuelve a escribirnos. 🐾")

MENU_BUTTONS = [
    {"id": "lost", "title": "Perdí a mi perro"},
    {"id": "found", "title": "Encontré un perro"},
    {"id": "adopt", "title": "Quiero adoptar"},
]

MENU_TEXT = (
    "¡Hola! 🐶 Soy el asistente de *GuauWoow*. Te ayudo a reunir perritos con sus familias.\n\n"
    "¿Qué necesitas?\n"
    "1️⃣ Perdí a mi perro\n"
    "2️⃣ Encontré un perro\n"
    "3️⃣ Quiero adoptar\n\n"
    "Responde con el número o toca un botón.\n"
    "_BAJA: no recibir avisos · ALTA: volver a recibirlos · ELIMINAR: borrar tus datos · PERSONA: pedir que te "
    "contacte el equipo_"
)


def menu_text() -> str:
    """Menú con el enlace al aviso y las reglas del bot (centro legal)."""
    return MENU_TEXT + f"\n_Aviso de privacidad y reglas: {_link('/app/legal/privacidad-whatsapp.html')}_"


def notice_text() -> str:
    """Aviso simplificado del primer contacto (privacidad-simplificado.html §5.1; LFPDPPP art. 16 fr. II)."""
    operador = ", ".join(v for v in (settings.emisor_nombre, settings.operator_address) if v)
    return (
        f"Hola, soy el asistente de GuauWoow{f' ({operador})' if operador else ''}. Usaremos tu número, tus "
        "mensajes y las fotos y la ubicación que envíes solo para registrar reportes de perritos perdidos o "
        "encontrados, buscar coincidencias y responderte. Los mensajes pasan por Meta y las fotos se comparan con IA, "
        "ambos fuera de México. No enviamos ni pedimos documentos ni datos de pago por aquí. Escribe BAJA para no "
        "recibir avisos, ELIMINAR para borrar tus datos o PERSONA para pedir que alguien del equipo te contacte. "
        f"Aviso completo y tus derechos: {_link('/app/legal/privacidad-whatsapp.html')}"
    )


def publish_prompt() -> str:
    return (
        "📋 Antes de publicar: tu reporte será *público* en GuauWoow con las fotos, la descripción y una *zona "
        "aproximada* (no el punto exacto). Tu número no se publica. Al publicarlo compararemos la foto con IA para "
        "buscar coincidencias.\n"
        f"Reglas: {_link('/app/legal/terminos.html#comunicaciones')} · Aviso: {_link('/app/legal/privacidad-whatsapp.html')}"
        "\n\nResponde *PUBLICAR* para publicarlo o *NO* para descartarlo."
    )


def _needs_notice(interaction: BotInteraction) -> bool:
    data = interaction.data or {}
    if data.get("notice_v") != NOTICE_VERSION:
        return True
    try:
        shown = datetime.datetime.fromisoformat(str(data.get("notice_at")))
    except ValueError:
        return True
    return datetime.datetime.utcnow() - shown > NOTICE_MAX_AGE


def _norm(text: str | None) -> str:
    raw = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower().strip()
    return " ".join(raw.replace("¿", "").replace("?", "").replace("!", "").replace("¡", "").split())


def _link(path: str) -> str:
    return settings.public_url(path)


def _get_interaction(db: Session, phone: str) -> BotInteraction:
    interaction = db.query(BotInteraction).filter(BotInteraction.phone == phone).first()
    if not interaction:
        interaction = BotInteraction(phone=phone, stage="welcome", data={})
        db.add(interaction)
        db.flush()
    elif interaction.updated_at and datetime.datetime.utcnow() - interaction.updated_at > IDLE_RESET:
        interaction.stage = "welcome"
        interaction.data = {k: v for k, v in (interaction.data or {}).items() if k in KEEP_KEYS}
        flag_modified(interaction, "data")
    return interaction


def _set(interaction: BotInteraction, stage: str | None = None, **data):
    if stage:
        interaction.stage = stage
    if data:
        interaction.data = {**(interaction.data or {}), **data}
    flag_modified(interaction, "data")
    interaction.updated_at = datetime.datetime.utcnow()


def _choice(event: dict) -> str | None:
    if event.get("button_id") in ("lost", "found", "adopt"):
        return event["button_id"]
    t = _norm(event.get("text"))
    if t in ("1", "1.", "uno") or "perdi" in t or "perdido" in t or "se me perdio" in t:
        return "lost"
    if t in ("2", "2.", "dos") or "encontre" in t or "encontrado" in t:
        return "found"
    if t in ("3", "3.", "tres") or "adopt" in t:
        return "adopt"
    return None


def _store_media(event: dict) -> str | None:
    if event.get("media_id"):
        data = whatsapp_api.download_media(event["media_id"])
        if data:
            try:
                return images.process_image_bytes(data)
            except images.ImageError as exc:
                logger.warning("Imagen de WhatsApp inválida: %s", exc)
        return None
    if event.get("media_url"):
        return images.download_and_store(event["media_url"])
    return None


def _reply(interaction: BotInteraction, text: str, buttons: list[dict] | None = None) -> dict:
    interaction.last_message = text
    return {"phone": interaction.phone, "stage": interaction.stage, "response": text, "buttons": buttons}


def _menu(interaction: BotInteraction) -> dict:
    _set(interaction, "menu")
    interaction.data = {k: v for k, v in (interaction.data or {}).items() if k in KEEP_KEYS}
    flag_modified(interaction, "data")
    return _reply(interaction, menu_text(), MENU_BUTTONS)


def _create_report(db: Session, interaction: BotInteraction, details: str | None) -> dict:
    data = interaction.data or {}
    linked = _linked_user(db, interaction.phone)
    if linked is not None and (linked.age_check_required or linked.age_declaration_required):
        # Misma limitación de solo lectura que en la app (L-edad): el bot no sirve para saltarla
        _set(interaction, "welcome")
        return _reply(interaction, AGE_LIMITED_TEXT)
    flow = data.get("flow", "lost")
    skip = _norm(details) in SKIP_WORDS or not details
    if flow == "lost":
        name = "Sin nombre"
        if not skip:
            name = details.split(",")[0].split(".")[0].strip()[:60] or "Sin nombre"
    else:
        name = "Perrito encontrado"
    description_parts = []
    if not skip:
        description_parts.append(details.strip())
    if data.get("location_text"):
        description_parts.append(f"Ubicación referida: {data['location_text']}")
    description_parts.append("Reporte recibido por WhatsApp.")
    report = LostReport(
        reporter_id=None,
        dog_name=name,
        report_type=flow,
        description="\n".join(description_parts),
        city=data.get("city"),
        # El bot no tiene geocodificador: el estado se deduce de lo que escribió o del pin
        state=estados_mx.derive_state(None, data.get("city") or data.get("location_text"), data.get("lat"),
                                      data.get("lon")),
        country="México",
        latitude=data.get("lat"),
        longitude=data.get("lon"),
        photos=data.get("photos") or [],
        status="active",
        source="whatsapp",
        contact_phone=interaction.phone,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    # Alerta a quienes viven cerca y a refugios/casas de paso de la zona (en segundo plano)
    dispatch("app.tasks.notifications.notify_nearby_report", report.id)
    # Busca publicaciones recientes en los grupos públicos de Facebook del estado (si hay proveedor)
    facebook_groups.trigger_zone_fetch(report.state)

    try:
        found = matching.run_report_matching(db, report.id)
    except Exception:  # noqa: BLE001
        logger.exception("Falló el matching del reporte %s", report.id)
        found = []
    db.refresh(report)
    if report.ai_analysis and report.ai_analysis.get("description_es") and skip:
        report.description = f"{report.ai_analysis['description_es']}\n{report.description}"
        db.commit()

    # El bot no gestiona adopciones (terminos.html 11.3): solo coincidencias con otros reportes
    strong = [m for m in found if m["score"] >= 40 and m["type"] != "adoption"][:3]
    header = (
        f"✅ ¡Listo! Publicamos tu reporte #{report.id}.\n{_link(f'/app/?report={report.id}')}\n\n"
    )
    if strong:
        lines = []
        for m in strong:
            label = {"found": "Encontrado", "lost": "Perdido"}.get(m["type"], m["type"])
            path = f"/app/?report={m['id']}"
            dist = f" · {m['distance_km']:.1f} km" if m.get("distance_km") is not None else ""
            lines.append(f"🐾 *{m['name']}* ({label}, {m['score']}% parecido){dist}\n{_link(path)}")
        body = header + "Encontré estas posibles coincidencias:\n\n" + "\n\n".join(lines)
    else:
        body = header + "Todavía no veo coincidencias fuertes, pero seguimos buscando y te escribimos si aparece algo. 💛"
    _set(interaction, "done", lost_report_id=report.id)
    from app.services import consent

    if not interaction.opted_out_at and consent.latest_phone_consent(db, interaction.phone) is not True:
        # Nunca dio permiso (o lo retiró en la app): se pregunta; sin un «sí» no le escribimos después
        _set(interaction, ask_alerts=report.id)
        return _reply(interaction, body + "\n\n" + ALERTS_QUESTION, ALERTS_BUTTONS)
    body += "\n\nEscribe *menú* para hacer otra cosa."
    return _reply(interaction, body)


def _alerts_answer(event: dict, t: str) -> bool | None:
    if event.get("button_id") in ("alerts_yes", "alerts_no"):
        return event["button_id"] == "alerts_yes"
    if t in ALERTS_YES_WORDS:
        return True
    if t in ALERTS_NO_WORDS:
        return False
    return None


def handle_event(db: Session, event: dict) -> dict:
    """Procesa un evento normalizado y devuelve {phone, stage, response, buttons} y, en el primer contacto (o tras
    12 meses), "notice": el aviso de privacidad simplificado, que process_event envía antes de la respuesta."""
    interaction = _get_interaction(db, event["phone"])
    show_notice = _needs_notice(interaction)
    result = _handle_event(db, event)
    if show_notice:
        result["notice"] = notice_text()
        _set(interaction, notice_v=NOTICE_VERSION, notice_at=datetime.datetime.utcnow().isoformat())
    return result


def _handle_event(db: Session, event: dict) -> dict:
    phone = event["phone"]
    interaction = _get_interaction(db, phone)
    if event.get("name"):
        _set(interaction, name=event["name"])
    text = (event.get("text") or "").strip()
    t = _norm(text)
    has_media = bool(event.get("media_id") or event.get("media_url"))
    has_location = event.get("latitude") is not None and event.get("longitude") is not None
    stage = interaction.stage

    # Confirmación de ELIMINAR (va antes de BAJA: aquí "cancelar" o "no" cancelan el borrado)
    if stage == "confirm_delete":
        if t in CONFIRM_WORDS:
            return _delete_bot_data(db, interaction)
        if t in CANCEL_DELETE_WORDS:
            _set(interaction, "welcome")
            return _reply(interaction, "Listo, no borramos nada. Escribe *menú* para ver las opciones.")
        stage = interaction.stage = "welcome"
    # Aceptación para publicar el reporte (va antes de BAJA: aquí "cancelar" o "no" descartan el reporte)
    if stage == "confirm_publish":
        if event.get("button_id") == "publish_yes" or t in PUBLISH_WORDS:
            return _create_report(db, interaction, (interaction.data or {}).get("details"))
        if event.get("button_id") == "publish_no" or t in DISCARD_WORDS:
            interaction.data = {k: v for k, v in (interaction.data or {}).items() if k in KEEP_KEYS}
            _set(interaction, "welcome")
            return _reply(interaction, DISCARD_TEXT)
        if not (t in OPT_OUT_WORDS or t in OPT_IN_WORDS or t in DELETE_WORDS or t in HUMAN_WORDS or t in GREETINGS):
            return _reply(interaction, publish_prompt(), PUBLISH_BUTTONS)
    # Comandos de permisos: BAJA (STOP, ALTO, CANCELAR...), ALTA, ELIMINAR y PERSONA
    if t in OPT_OUT_WORDS:
        _set_whatsapp_consent(db, interaction, False)
        _set(interaction, "welcome")
        return _reply(interaction, OPT_OUT_TEXT)
    if t in OPT_IN_WORDS:
        _set_whatsapp_consent(db, interaction, True)
        _set(interaction, "welcome")
        return _reply(interaction, OPT_IN_TEXT)
    if t in DELETE_WORDS:
        _set(interaction, "confirm_delete")
        return _reply(interaction, DELETE_CONFIRM_TEXT)
    if t in HUMAN_WORDS:
        return _human_handoff(db, interaction)
    # Dado de baja: puede seguir usando el bot (HOLA reabre la conversación), pero sin avisos proactivos

    # Respuesta a «¿Quieres que te avisemos por este chat...?» al terminar un reporte (constancia en consent_records)
    if stage == "done" and (interaction.data or {}).get("ask_alerts"):
        answer = _alerts_answer(event, t)
        interaction.data = {k: v for k, v in (interaction.data or {}).items() if k != "ask_alerts"}
        _set(interaction)
        if answer is not None:
            _set_whatsapp_consent(db, interaction, answer)
            return _reply(interaction, ALERTS_YES_TEXT if answer else ALERTS_NO_TEXT)

    if t in GREETINGS or t == "menu":
        return _menu(interaction)
    if stage in ("welcome", "done"):
        if not _choice(event):
            return _menu(interaction)
        stage = "menu"  # eligió directamente una opción (p. ej. "1")

    if stage == "menu":
        choice = _choice(event)
        if choice in ("lost", "found"):
            _set(interaction, "photos", flow=choice, photos=[])
            if choice == "lost":
                msg = "Lamento mucho que tu perrito se haya perdido 💔 Vamos a buscarlo juntos.\n\n"
            else:
                msg = "¡Gracias por ayudar a un perrito! 🙌\n\n"
            msg += "📸 Envíame una foto donde se vea bien su *cara* y otra de *cuerpo completo* (de 1 a 3 fotos)."
            return _reply(interaction, msg)
        if choice == "adopt":
            # El bot no gestiona adopciones ni muestra perros en adopción (terminos.html 11.3; cero-venta §10)
            _set(interaction, "welcome")
            return _reply(interaction, ADOPT_TEXT.format(link=_link("/app/")))
        return _menu(interaction)

    if stage == "photos":
        photos = list(interaction.data.get("photos") or [])
        if has_media:
            url = _store_media(event)
            if not url:
                return _reply(interaction, "😕 No pude guardar esa foto. ¿Me la puedes enviar de nuevo?")
            photos.append(url)
            _set(interaction, photos=photos)
            if len(photos) >= MAX_PHOTOS:
                _set(interaction, "location")
                return _reply(interaction, "¡Gracias por las fotos! 📍 Ahora comparte la *ubicación* donde "
                              + ("se perdió" if interaction.data.get("flow") == "lost" else "lo encontraste")
                              + " (usa 📎 > Ubicación) o escribe la colonia y ciudad.")
            return _reply(interaction, f"📸 ¡Recibí la foto {len(photos)}! Puedes enviar otra (máximo {MAX_PHOTOS}) o escribe *listo* para continuar.")
        if t in ("listo", "ya", "continuar", "siguiente", "ok") or has_location:
            if not photos:
                return _reply(interaction, "Necesito al menos *una foto* del perrito para poder buscar coincidencias 📸")
            if has_location:
                _set(interaction, "details", lat=event["latitude"], lon=event["longitude"], location_text=text or None)
                return _reply(interaction, _details_prompt(interaction))
            _set(interaction, "location")
            return _reply(interaction, "📍 Ahora comparte la *ubicación* (usa 📎 > Ubicación) o escribe la colonia y ciudad.")
        return _reply(interaction, "📸 Envíame una foto del perrito (cara y cuerpo). Cuando termines escribe *listo*.")

    if stage == "location":
        if has_location:
            _set(interaction, "details", lat=event["latitude"], lon=event["longitude"], location_text=text or None)
            return _reply(interaction, _details_prompt(interaction))
        if text:
            city = text.split(",")[-1].strip() if "," in text else text
            _set(interaction, "details", city=city[:100], location_text=text[:200])
            return _reply(interaction, _details_prompt(interaction))
        return _reply(interaction, "📍 Comparte la ubicación (📎 > Ubicación) o escribe la colonia y ciudad.")

    if stage == "details":
        if has_media:
            return _reply(interaction, "Ya tengo las fotos 👍 Ahora escríbeme el nombre o una seña particular (o *no sé*).")
        # Antes de publicar: aviso de que será público y aceptación expresa (la IA analiza la foto solo después)
        _set(interaction, "confirm_publish", details=(text or "")[:1000])
        return _reply(interaction, publish_prompt(), PUBLISH_BUTTONS)

    return _menu(interaction)


# --------------------------------------------------------------------------- permisos y datos del bot
def _linked_user(db: Session, phone: str | None):
    """Cuenta activa con ese número verificado (se compara por los últimos 10 dígitos)."""
    import re

    from app.models import User

    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 10:
        return None
    return (db.query(User).filter(User.phone.like(f"%{digits[-10:]}"), User.phone_verified.is_(True),
                                  User.is_active.is_(True)).first())


def _set_whatsapp_consent(db: Session, interaction: BotInteraction, granted: bool) -> None:
    """BAJA/ALTA: marca el número y, si es de una cuenta, cambia también «Avisos por WhatsApp» (con constancia)."""
    from app.services import consent

    interaction.opted_out_at = None if granted else (interaction.opted_out_at or datetime.datetime.utcnow())
    for other in consent.bot_interactions_for(db, interaction.phone):
        if other is not interaction:
            other.opted_out_at = None if granted else (other.opted_out_at or datetime.datetime.utcnow())
    user = _linked_user(db, interaction.phone)
    if user is not None and bool(user.whatsapp_alerts) != granted:
        consent.set_preference(db, user, "whatsapp_alerts", granted, channel="whatsapp", sync_bot=False)
    else:
        consent.record_consent(db, user, "whatsapp_alerts", granted, "whatsapp", phone=interaction.phone)


def _delete_bot_data(db: Session, interaction: BotInteraction) -> dict:
    """ELIMINAR confirmado: borra al momento la conversación y el contenido de los reportes creados desde este
    número, apaga los avisos y abre una solicitud de cancelación (K-SOLIC) con folio para lo demás."""
    import re

    from app.services import consent
    from app.services.facebook_groups import purge_report_content

    now = datetime.datetime.utcnow()
    phone = interaction.phone
    name = (interaction.data or {}).get("name")
    digits = re.sub(r"\D", "", phone or "")
    removed = 0
    if len(digits) >= 10:
        reports = db.query(LostReport).filter(LostReport.source == "whatsapp", LostReport.reporter_id.is_(None),
                                              LostReport.contact_phone.like(f"%{digits[-10:]}"),
                                              LostReport.purged_at.is_(None)).all()
        for report in reports:
            report.is_hidden = True
            report.contact_phone = None
            report.latitude = report.longitude = None
            purge_report_content(db, report, now)
            removed += 1
    # Se conserva solo la marca de baja del número (para no volver a escribirle), sin la conversación
    interaction.data = {}
    flag_modified(interaction, "data")
    interaction.last_message = None
    interaction.stage = "welcome"
    _set_whatsapp_consent(db, interaction, False)
    db.commit()

    folio = None
    try:
        from app.services import solicitudes

        req = solicitudes.create_solicitud(
            db, kind="cancelacion", name=name or "Persona usuaria del bot de WhatsApp",
            description=("Pedida desde el bot de WhatsApp con el comando ELIMINAR. Se borraron al momento la "
                         f"conversación, la ubicación y el contenido de {removed} reporte(s) creados desde este número, "
                         "y se apagaron los avisos por WhatsApp. Revisar si quedan otros datos ligados al número."),
            phone=phone, channel="whatsapp", identity_method="whatsapp",
            details={"alcance": "whatsapp", "origen": "bot", "reportes_borrados": removed},
        )
        folio = req.folio
    except Exception:  # noqa: BLE001 - el borrado inmediato ya se hizo; el equipo recibe el aviso
        db.rollback()
        logger.exception("No se pudo abrir la solicitud de cancelación del número %s", phone[-4:] if phone else "?")
        consent.notify_admins(db, "whatsapp_delete", "Solicitud ELIMINAR por WhatsApp sin folio",
                              f"El número {phone} pidió ELIMINAR desde el bot y no se pudo crear la solicitud. "
                              "Regístrala a mano en el centro de solicitudes.", data={"phone": phone})
    text = ("✅ Listo. Borramos tu conversación con el bot"
            + (f" y retiramos {removed} reporte(s) creados desde este número" if removed else "")
            + ", y apagamos tus avisos por WhatsApp.")
    if folio:
        text += (f"\n\nTu folio es *{folio}*. Revisaremos si queda algún otro dato ligado a este número y te "
                 "responderemos en un máximo de 20 días hábiles. Lo que la ley nos obliga a guardar se conserva "
                 "bloqueado y te diremos qué es y por qué.")
    text += f"\n\nMás información: {_link('/app/legal/eliminacion-datos.html')}"
    return _reply(interaction, text)


def _human_handoff(db: Session, interaction: BotInteraction) -> dict:
    """PERSONA: avisa al equipo (app y buzón de soporte) y le da a la persona los otros canales."""
    from app import cache
    from app.services import consent

    key = f"wa-human:{interaction.phone}"
    already = False
    try:
        already = bool(cache.get(key))
    except Exception:  # noqa: BLE001
        already = False
    _set(interaction, "welcome")
    if not already:
        name = (interaction.data or {}).get("name")
        consent.notify_admins(
            db, "support_handoff", "Piden hablar con una persona (WhatsApp)",
            f"{name or 'Una persona'} ({interaction.phone}) escribió PERSONA en el bot de WhatsApp. "
            "Contéstale lo antes posible en horario de atención.",
            data={"phone": interaction.phone, "canal": "whatsapp"},
        )
        try:
            cache.set(key, 1, ttl=HUMAN_HANDOFF_COOLDOWN)
        except Exception:  # noqa: BLE001
            pass
    contacts = []
    if settings.support_email:
        contacts.append(f"correo: {settings.support_email}")
    if settings.support_whatsapp:
        contacts.append(f"teléfono: {settings.support_whatsapp}")
    text = ("🙋 Listo, ya le avisamos a una persona del equipo"
            + (" (otra vez no hace falta: ya está en la fila)" if already else "")
            + ". Te contactará a este número en horario de atención.")
    if contacts:
        text += " También puedes escribirnos por " + " o ".join(contacts) + "."
    text += "\n\nMientras tanto, escribe *menú* para volver a las opciones."
    return _reply(interaction, text)


def _details_prompt(interaction: BotInteraction) -> str:
    if interaction.data.get("flow") == "lost":
        return "📝 ¿Cómo se llama tu perrito y qué seña particular tiene? (collar, manchas, cicatrices…). Si prefieres, escribe *no sé*."
    return "📝 Cuéntame algo del perrito: ¿traía collar o placa? ¿alguna seña particular? Si no sabes, escribe *no sé*."


def process_event(db: Session, event: dict, send: bool = True) -> dict:
    result = handle_event(db, event)
    db.commit()
    if send and result.get("notice"):
        whatsapp_api.send_text(event["phone"], result["notice"])
    if send and result.get("response"):
        if result.get("buttons"):
            whatsapp_api.send_buttons(event["phone"], result["response"], result["buttons"])
        else:
            whatsapp_api.send_text(event["phone"], result["response"])
    return result


def process_message(db: Session, phone: str, message: str | None, media_url: str | None,
                    latitude: float | None = None, longitude: float | None = None) -> dict:
    """Compatibilidad con el simulador del panel ({phone, message, media_url}). No envía por Meta."""
    event = {"phone": phone, "text": message, "media_url": media_url, "latitude": latitude, "longitude": longitude}
    return process_event(db, event, send=False)
