"""Cliente mínimo de WhatsApp Cloud API (Graph API de Meta).

Meta solo permite mensajes de texto libre dentro de la ventana de atención de 24 h (desde el último
mensaje que nos escribió la persona). Fuera de ella solo se pueden enviar plantillas aprobadas.
"""
import hashlib
import hmac
import logging
import re
import time

import requests

from app.config import settings

logger = logging.getLogger(__name__)

SERVICE_WINDOW_SECONDS = 24 * 60 * 60 - 10 * 60  # 10 min de margen contra la ventana real de Meta
TEMPLATE_PARAM_MAX = 250


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{settings.graph_api_version}/{path.lstrip('/')}"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


def webhook_available() -> bool:
    """El webhook solo existe con WhatsApp configurado (en development también sin llaves, para el simulador)."""
    return settings.whatsapp_enabled or settings.is_development


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """Valida X-Hub-Signature-256 (sha256=<hex>) con WHATSAPP_APP_SECRET.

    En producción la firma es SIEMPRE obligatoria (sin secreto se rechaza todo). Fuera de producción,
    sin secreto se acepta para poder probar localmente.
    """
    if not settings.whatsapp_app_secret:
        return not settings.is_production
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _window_key(phone: str | None) -> str | None:
    digits = _digits(phone)
    # Se comparan los últimos 10 dígitos: Meta manda 521XXXXXXXXXX y la app guarda +52XXXXXXXXXX
    return f"wa:inbound:{digits[-10:]}" if len(digits) >= 10 else None


def mark_inbound(phone: str | None) -> None:
    """Registra que este número nos escribió (abre la ventana de 24 h). Requiere Redis."""
    from app import cache

    key = _window_key(phone)
    r = cache._get_redis()
    if not key or r is None:
        return
    try:
        r.setex(key, SERVICE_WINDOW_SECONDS, int(time.time()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo registrar la ventana de WhatsApp: %s", exc)


def in_service_window(phone: str | None) -> bool:
    """True si el número nos escribió en las últimas 24 h. Sin Redis se asume que no (se usa plantilla)."""
    from app import cache

    key = _window_key(phone)
    r = cache._get_redis()
    if not key or r is None:
        return False
    try:
        return bool(r.exists(key))
    except Exception:  # noqa: BLE001
        return False


def _post_message(payload: dict) -> bool:
    if not settings.whatsapp_enabled:
        logger.info("[whatsapp:dev] Mensaje no enviado (sin credenciales): %s", payload)
        return False
    try:
        resp = requests.post(
            _graph(f"{settings.whatsapp_phone_number_id}/messages"),
            json={"messaging_product": "whatsapp", "recipient_type": "individual", **payload},
            headers=_auth_headers(),
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error("Error enviando WhatsApp: %s", exc)
        return False
    if resp.status_code >= 400:
        logger.error("WhatsApp API %s: %s", resp.status_code, resp.text[:400])
        return False
    return True


def send_text(to: str, body: str) -> bool:
    """Texto libre: solo para respuestas dentro de la ventana de 24 h (ver in_service_window)."""
    return _post_message({"to": to, "type": "text", "text": {"preview_url": True, "body": body[:4096]}})


def _template_param(value) -> str:
    # Meta rechaza parámetros con saltos de línea, tabuladores o más de 4 espacios seguidos
    text = " ".join(str(value if value is not None else "").split())
    return text[:TEMPLATE_PARAM_MAX] or "-"


def send_template(to: str, template_name: str, language: str = "es_MX", body_params: list | None = None) -> bool:
    """Envía una plantilla aprobada por Meta ({{1}}, {{2}}… del cuerpo en body_params)."""
    if not template_name:
        return False
    template = {"name": template_name, "language": {"code": language or settings.whatsapp_template_language}}
    params = [_template_param(p) for p in (body_params or [])]
    if params:
        template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
    return _post_message({"to": _digits(to) or to, "type": "template", "template": template})


def send_buttons(to: str, body: str, buttons: list[dict]) -> bool:
    """buttons: [{"id": "lost", "title": "Perdí a mi perro"}] (máx. 3, títulos ≤ 20 caracteres)."""
    return _post_message({
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}} for b in buttons[:3]
            ]},
        },
    })


def download_media(media_id: str) -> bytes | None:
    """Obtiene la URL temporal del media y descarga el archivo con el token Bearer."""
    if not settings.whatsapp_access_token:
        logger.warning("No se puede descargar media %s sin WHATSAPP_ACCESS_TOKEN", media_id)
        return None
    try:
        meta = requests.get(_graph(media_id), headers=_auth_headers(), timeout=15)
        meta.raise_for_status()
        url = meta.json().get("url")
        if not url:
            return None
        # Solo hosts permitidos (REMOTE_MEDIA_HOSTS: lookaside.fbsbx.com...), con tope de tamaño y sin IPs privadas
        from app.services import images

        return images.fetch_remote_media(url, headers=_auth_headers())
    except requests.RequestException as exc:
        logger.error("Error descargando media de WhatsApp %s: %s", media_id, exc)
        return None


def parse_webhook(payload: dict) -> list[dict]:
    """Normaliza el payload real de Meta a una lista de eventos simples.

    Cada evento: {phone, name, type, text, media_id, latitude, longitude, button_id, message_id}
    Se ignoran los eventos de "statuses" (entregado/leído).
    """
    events = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            for msg in value.get("messages") or []:
                phone = msg.get("from")
                if not phone:
                    continue
                ev = {
                    "phone": phone, "name": names.get(phone), "type": msg.get("type"), "message_id": msg.get("id"),
                    "text": None, "media_id": None, "latitude": None, "longitude": None, "button_id": None,
                }
                mtype = msg.get("type")
                if mtype == "text":
                    ev["text"] = (msg.get("text") or {}).get("body")
                elif mtype == "image":
                    ev["media_id"] = (msg.get("image") or {}).get("id")
                    ev["text"] = (msg.get("image") or {}).get("caption")
                elif mtype == "location":
                    loc = msg.get("location") or {}
                    ev["latitude"], ev["longitude"] = loc.get("latitude"), loc.get("longitude")
                    ev["text"] = loc.get("address") or loc.get("name")
                elif mtype == "interactive":
                    inter = msg.get("interactive") or {}
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    ev["button_id"], ev["text"] = reply.get("id"), reply.get("title")
                elif mtype == "button":
                    ev["button_id"] = (msg.get("button") or {}).get("payload")
                    ev["text"] = (msg.get("button") or {}).get("text")
                events.append(ev)
    return events
