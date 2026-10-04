import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services import whatsapp_api
from app.services.background import dispatch
from app.services.whatsapp_bot import process_message

router = APIRouter(tags=["whatsapp"])
logger = logging.getLogger(__name__)


@router.get("/whatsapp/webhook")
def whatsapp_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Verificación del webhook por parte de Meta (WhatsApp Cloud API)."""
    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == settings.whatsapp_verify_token:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Token de verificación incorrecto.")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Recibe eventos de Meta (formato real) o del simulador del panel ({phone, message, media_url})."""
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON inválido.")

    # Formato real de Meta
    if payload.get("object") == "whatsapp_business_account" or "entry" in payload:
        if not whatsapp_api.verify_signature(raw, request.headers.get("x-hub-signature-256")):
            raise HTTPException(status_code=403, detail="Firma inválida.")
        events = whatsapp_api.parse_webhook(payload)
        for event in events:
            dispatch("app.tasks.whatsapp.process_whatsapp_event", event, background_tasks=background_tasks)
        return {"received": True, "events": len(events)}

    # Simulador del panel de administración: respuesta síncrona
    phone = payload.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Falta el teléfono.")
    if settings.is_production:
        # En producción el simulador solo se permite a administradores
        from app.dependencies import _user_from_token

        auth = request.headers.get("authorization", "")
        user = _user_from_token(auth.removeprefix("Bearer ").strip(), db) if auth else None
        if not user or user.role not in ("admin", "superadmin"):
            raise HTTPException(status_code=403, detail="El simulador solo está disponible para administradores.")
    return process_message(
        db, phone=str(phone), message=payload.get("message"), media_url=payload.get("media_url"),
        latitude=payload.get("latitude"), longitude=payload.get("longitude"),
    )
