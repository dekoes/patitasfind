"""Bot de WhatsApp de PatitasFind.

Flujo (estado en BotInteraction; se reinicia tras 24 h sin actividad o con "hola"/"menú"):
  menú -> 1) Perdí a mi perro  2) Encontré un perro  3) Quiero adoptar
  perdido/encontrado: fotos (1 a 3, "listo" para seguir) -> ubicación (pin o texto)
                      -> nombre/señas (o "no sé") -> se crea el reporte y se buscan coincidencias
  adoptar: se muestran 3 perros disponibles (los más cercanos si manda su ubicación)
"""
import datetime
import logging
import unicodedata

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models import BotInteraction, Dog, LostReport
from app.services import images, matching, whatsapp_api
from app.services.geo import haversine_km

logger = logging.getLogger(__name__)

IDLE_RESET = datetime.timedelta(hours=24)
MAX_PHOTOS = 3
GREETINGS = {"hola", "menu", "inicio", "empezar", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hi", "hello", "ayuda"}
OPT_OUT_WORDS = {"baja", "stop", "darme de baja", "dar de baja", "unsubscribe"}
OPT_OUT_TEXT = "Listo, ya no te enviaremos mensajes. Escribe HOLA si quieres volver."
SKIP_WORDS = {"no se", "nose", "no lo se", "ninguno", "nada", "no", "saltar", "omitir"}

MENU_BUTTONS = [
    {"id": "lost", "title": "Perdí a mi perro"},
    {"id": "found", "title": "Encontré un perro"},
    {"id": "adopt", "title": "Quiero adoptar"},
]

MENU_TEXT = (
    "¡Hola! 🐶 Soy el asistente de *PatitasFind*. Te ayudo a reunir perritos con sus familias.\n\n"
    "¿Qué necesitas?\n"
    "1️⃣ Perdí a mi perro\n"
    "2️⃣ Encontré un perro\n"
    "3️⃣ Quiero adoptar\n\n"
    "Responde con el número o toca un botón."
)


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
        interaction.data = {}
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


def _dogs_text(db: Session, lat=None, lon=None) -> str:
    q = db.query(Dog).filter(Dog.status == "available")
    dogs = q.order_by(Dog.created_at.desc()).limit(200).all()
    if lat is not None and lon is not None:
        with_geo = [d for d in dogs if d.latitude is not None and d.longitude is not None]
        with_geo.sort(key=lambda d: haversine_km(lat, lon, d.latitude, d.longitude))
        dogs = with_geo or dogs
    dogs = dogs[:3]
    if not dogs:
        return "Por ahora no hay perritos disponibles, pero pronto habrá más. 🐾"
    lines = []
    for d in dogs:
        extra = ""
        if lat is not None and d.latitude is not None:
            extra = f" · a {haversine_km(lat, lon, d.latitude, d.longitude):.1f} km"
        lines.append(f"🐶 *{d.name}* ({d.breed or 'Mestizo'}, {d.size or 'tamaño por confirmar'}) en {d.city or 'México'}{extra}\n{_link(f'/app/?dog={d.id}')}")
    return "\n\n".join(lines)


def _reply(interaction: BotInteraction, text: str, buttons: list[dict] | None = None) -> dict:
    interaction.last_message = text
    return {"phone": interaction.phone, "stage": interaction.stage, "response": text, "buttons": buttons}


def _menu(interaction: BotInteraction) -> dict:
    _set(interaction, "menu")
    interaction.data = {k: v for k, v in (interaction.data or {}).items() if k in ("name", "last_lat", "last_lon")}
    return _reply(interaction, MENU_TEXT, MENU_BUTTONS)


def _create_report(db: Session, interaction: BotInteraction, details: str | None) -> dict:
    data = interaction.data or {}
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

    try:
        found = matching.run_report_matching(db, report.id)
    except Exception:  # noqa: BLE001
        logger.exception("Falló el matching del reporte %s", report.id)
        found = []
    db.refresh(report)
    if report.ai_analysis and report.ai_analysis.get("description_es") and skip:
        report.description = f"{report.ai_analysis['description_es']}\n{report.description}"
        db.commit()

    strong = [m for m in found if m["score"] >= 40][:3]
    header = (
        f"✅ ¡Listo! Publicamos tu reporte #{report.id}.\n{_link(f'/app/?report={report.id}')}\n\n"
    )
    if strong:
        lines = []
        for m in strong:
            label = {"adoption": "En adopción", "found": "Encontrado", "lost": "Perdido"}.get(m["type"], m["type"])
            path = f"/app/?dog={m['id']}" if m["type"] == "adoption" else f"/app/?report={m['id']}"
            dist = f" · {m['distance_km']:.1f} km" if m.get("distance_km") is not None else ""
            lines.append(f"🐾 *{m['name']}* ({label}, {m['score']}% parecido){dist}\n{_link(path)}")
        body = header + "Encontré estas posibles coincidencias:\n\n" + "\n\n".join(lines)
    else:
        body = header + "Todavía no veo coincidencias fuertes, pero seguimos buscando y te escribimos si aparece algo. 💛"
    body += "\n\nEscribe *menú* para hacer otra cosa."
    _set(interaction, "done", lost_report_id=report.id)
    return _reply(interaction, body)


def handle_event(db: Session, event: dict) -> dict:
    """Procesa un evento normalizado y devuelve {phone, stage, response, buttons}."""
    phone = event["phone"]
    interaction = _get_interaction(db, phone)
    if event.get("name"):
        _set(interaction, name=event["name"])
    text = (event.get("text") or "").strip()
    t = _norm(text)
    has_media = bool(event.get("media_id") or event.get("media_url"))
    has_location = event.get("latitude") is not None and event.get("longitude") is not None
    stage = interaction.stage

    # Baja de mensajes (BAJA/STOP) y re-suscripción con HOLA
    if t in OPT_OUT_WORDS:
        interaction.opted_out_at = datetime.datetime.utcnow()
        _set(interaction, "welcome")
        return _reply(interaction, OPT_OUT_TEXT)
    if interaction.opted_out_at is not None:
        if t in GREETINGS:
            interaction.opted_out_at = None
            return _menu(interaction)
        return _reply(interaction, "")  # dado de baja: no respondemos hasta que escriba HOLA

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
            _set(interaction, "adopt")
            lat, lon = interaction.data.get("last_lat"), interaction.data.get("last_lon")
            msg = "¡Qué alegría que quieras adoptar! 🐶💛 Estos perritos buscan hogar:\n\n" + _dogs_text(db, lat, lon)
            msg += "\n\n📍 Comparte tu ubicación y te muestro los más cercanos, o escribe *menú* para volver."
            return _reply(interaction, msg)
        return _menu(interaction)

    if stage == "adopt":
        if has_location:
            _set(interaction, last_lat=event["latitude"], last_lon=event["longitude"])
            msg = "Estos son los perritos más cercanos a ti 🐾\n\n" + _dogs_text(db, event["latitude"], event["longitude"])
            msg += "\n\nEscribe *menú* para volver al inicio."
            return _reply(interaction, msg)
        choice = _choice(event)
        if choice:
            _set(interaction, "menu")
            return handle_event(db, event)
        return _reply(interaction, "📍 Compárteme tu ubicación para mostrarte perritos cercanos, o escribe *menú*.")

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
                _set(interaction, "details", lat=event["latitude"], lon=event["longitude"], last_lat=event["latitude"],
                     last_lon=event["longitude"], location_text=text or None)
                return _reply(interaction, _details_prompt(interaction))
            _set(interaction, "location")
            return _reply(interaction, "📍 Ahora comparte la *ubicación* (usa 📎 > Ubicación) o escribe la colonia y ciudad.")
        return _reply(interaction, "📸 Envíame una foto del perrito (cara y cuerpo). Cuando termines escribe *listo*.")

    if stage == "location":
        if has_location:
            _set(interaction, "details", lat=event["latitude"], lon=event["longitude"], last_lat=event["latitude"],
                 last_lon=event["longitude"], location_text=text or None)
            return _reply(interaction, _details_prompt(interaction))
        if text:
            city = text.split(",")[-1].strip() if "," in text else text
            _set(interaction, "details", city=city[:100], location_text=text[:200])
            return _reply(interaction, _details_prompt(interaction))
        return _reply(interaction, "📍 Comparte la ubicación (📎 > Ubicación) o escribe la colonia y ciudad.")

    if stage == "details":
        if has_media:
            return _reply(interaction, "Ya tengo las fotos 👍 Ahora escríbeme el nombre o una seña particular (o *no sé*).")
        return _create_report(db, interaction, text)

    return _menu(interaction)


def _details_prompt(interaction: BotInteraction) -> str:
    if interaction.data.get("flow") == "lost":
        return "📝 ¿Cómo se llama tu perrito y qué seña particular tiene? (collar, manchas, cicatrices…). Si prefieres, escribe *no sé*."
    return "📝 Cuéntame algo del perrito: ¿traía collar o placa? ¿alguna seña particular? Si no sabes, escribe *no sé*."


def process_event(db: Session, event: dict, send: bool = True) -> dict:
    result = handle_event(db, event)
    db.commit()
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
