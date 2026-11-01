import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import DEV_WHATSAPP_VERIFY_TOKEN, settings
from app.database import get_db
from app.services import whatsapp_api
from app.services.background import dispatch
from app.services.whatsapp_bot import process_message

router = APIRouter(tags=["whatsapp"])
logger = logging.getLogger(__name__)


def _ensure_available():
    """Sin WhatsApp configurado el webhook no existe (404), salvo en development para el simulador."""
    if not whatsapp_api.webhook_available():
        raise HTTPException(status_code=404, detail="Not Found")  # igual que una ruta inexistente


@router.get("/whatsapp/webhook")
def whatsapp_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Verificación del webhook por parte de Meta (WhatsApp Cloud API)."""
    _ensure_available()
    expected = settings.whatsapp_verify_token or ""
    if settings.is_production and expected == DEV_WHATSAPP_VERIFY_TOKEN:
        expected = ""  # el token de desarrollo nunca sirve en producción
    if (
        hub_mode == "subscribe" and expected and hub_verify_token
        and hmac.compare_digest(hub_verify_token.encode(), expected.encode())
    ):
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Token de verificación incorrecto.")


def _enqueue_events(events: list[dict], background_tasks: BackgroundTasks) -> None:
    """Redis (ventana de 24 h) y el broker de Celery hacen E/S: se llama desde el threadpool."""
    for event in events:
        # La persona nos escribió: se abre la ventana de 24 h para responder con texto libre
        whatsapp_api.mark_inbound(event.get("phone"))
        dispatch("app.tasks.whatsapp.process_whatsapp_event", event, background_tasks=background_tasks)


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Recibe eventos de Meta (formato real) o del simulador del panel ({phone, message, media_url}).

    El handler es async solo para leer el cuerpo crudo (la firma se valida sobre los bytes); todo lo que
    toca Redis, la BD o descarga fotos corre en el threadpool para no bloquear el event loop.
    """
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        payload = None
    is_meta = isinstance(payload, dict) and (payload.get("object") == "whatsapp_business_account" or "entry" in payload)
    if is_meta or request.headers.get("x-hub-signature-256"):
        _ensure_available()
        # La firma se valida antes de interpretar cualquier cosa del cuerpo
        if not whatsapp_api.verify_signature(raw, request.headers.get("x-hub-signature-256")):
            raise HTTPException(status_code=403, detail="Firma inválida.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON inválido.")

    # Formato real de Meta
    if is_meta:
        events = whatsapp_api.parse_webhook(payload)
        await run_in_threadpool(_enqueue_events, events, background_tasks)
        return {"received": True, "events": len(events)}

    # Simulador del panel de administración: respuesta síncrona (no envía nada por Meta)
    phone = payload.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Falta el teléfono.")
    if not settings.is_development:
        # Fuera de development el simulador solo se permite a administradores
        from app.dependencies import _user_from_token

        auth = request.headers.get("authorization", "")
        user = await run_in_threadpool(_user_from_token, auth.removeprefix("Bearer ").strip(), db) if auth else None
        if not user or user.role not in ("admin", "superadmin"):
            raise HTTPException(status_code=403, detail="El simulador solo está disponible para administradores.")
    # Consulta la BD y descarga/decodifica la foto: fuera del event loop
    return await run_in_threadpool(
        process_message, db, phone=str(phone), message=payload.get("message"), media_url=payload.get("media_url"),
        latitude=payload.get("latitude"), longitude=payload.get("longitude"),
    )
