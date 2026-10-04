"""Cliente mínimo de WhatsApp Cloud API (Graph API de Meta)."""
import hashlib
import hmac
import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{settings.graph_api_version}/{path.lstrip('/')}"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """Valida X-Hub-Signature-256 (sha256=<hex>) con WHATSAPP_APP_SECRET. Sin secreto, acepta."""
    if not settings.whatsapp_app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


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
    return _post_message({"to": to, "type": "text", "text": {"preview_url": True, "body": body[:4096]}})


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
        resp = requests.get(url, headers=_auth_headers(), timeout=30)
        resp.raise_for_status()
        return resp.content
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
