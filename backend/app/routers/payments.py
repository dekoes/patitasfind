import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, get_verified_user, require_admin
from app.models import Donation, Order, Refuge, User
from app.schemas import AdminDonationOut, DonationCheckoutOut, DonationCreate, DonationOut, PaymentResolveRequest
from app.services import legal_acceptance, mercadopago_oauth, payments
from app.services.legal_acceptance import ComplianceError
from app.services.background import dispatch
from app.services.payment_flow import (
    ADMIN_ROLES, REF_HINT_RE, create_donation_checkout, refresh_from_provider, resolve_donation,
)

router = APIRouter(tags=["payments"])
logger = logging.getLogger(__name__)


@router.post("/payments/donations", response_model=DonationCheckoutOut, status_code=201)
def create_donation(payload: DonationCreate, request: Request, current_user: User = Depends(get_verified_user),
                    db: Session = Depends(get_db)):
    """Donativo con Split. Reglas (services/reglas.py): sin autodonaciones, tope por donativo y diario, sin puntos de
    ranking y aviso de deducibilidad en la respuesta.

    La casilla «Leí la Política de donativos» es obligatoria (400 code=policy_required). La constancia queda en la
    bitácora de aceptaciones (K-ACEPT, method="donativo") ligada al donativo, en su propia transacción corta después
    de crearlo (igual que la compra en orders.py)."""
    if payload.accepted_policy is not True:
        raise ComplianceError(400, "Marca que leíste la Política de donativos para continuar.", "policy_required")
    result = create_donation_checkout(db, current_user, payload.refuge_id, payload.amount,
                                      share_name=payload.share_name)
    try:
        legal_acceptance.record_acceptance(db, current_user, legal_acceptance.DONATIONS_SLUG, "donativo", request,
                                           context={"donation_id": result.get("donation_id")}, commit=True)
    except Exception:  # noqa: BLE001 - el donativo ya existe; no se cobra dos veces por una falla de la bitácora
        db.rollback()
        logger.exception("No se pudo registrar la aceptación de la Política de donativos del donativo %s",
                         result.get("donation_id"))
    return result


@router.get("/payments/donations/me", response_model=list[DonationOut])
def my_donations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (db.query(Donation).filter(Donation.user_id == current_user.id)
            .order_by(Donation.created_at.desc(), Donation.id.desc()).offset(skip).limit(limit).all())


@router.get("/payments/status")
def payment_status(
    order: int | None = Query(None),
    donation: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin = current_user.role in ADMIN_ROLES
    if order:
        obj = db.query(Order).filter(Order.id == order).first()
        kind = "order"
    elif donation:
        obj = db.query(Donation).filter(Donation.id == donation).first()
        kind = "donation"
    else:
        raise HTTPException(status_code=400, detail="Indica ?order=<id> o ?donation=<id>.")
    if not obj:
        raise HTTPException(status_code=404, detail="No encontramos ese pago.")
    if obj.user_id != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="No tienes acceso a este pago.")
    refresh_from_provider(db, kind, obj)  # por si el webhook se retrasa o se perdió
    return {"type": kind, "id": obj.id, "status": obj.status}


@router.post("/payments/mercadopago/webhook")
async def mercadopago_webhook(request: Request, background_tasks: BackgroundTasks):
    """Notificaciones de Mercado Pago (Webhooks e IPN). Siempre responde 200 rápido.

    No confía en el contenido: solo toma el id del pago y lo consulta en la API de Mercado Pago.
    """
    params = request.query_params
    body = {}
    try:
        raw = await request.body()
        if raw:
            body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    topic = params.get("type") or params.get("topic") or body.get("type") or body.get("topic") or ""
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    payment_id = params.get("data.id") or data.get("id") or params.get("id")
    if not payment_id and isinstance(body.get("resource"), str) and topic == "payment":
        payment_id = body["resource"].rstrip("/").split("/")[-1]

    if topic == "mp-connect":
        return _mp_connect_event(request, body, params)
    if topic != "payment" or not payment_id:
        return {"received": True, "ignored": True}

    payment_id = str(payment_id)
    # El manifiesto firmado usa el data.id del QUERY STRING (documentación de Mercado Pago)
    if not payments.verify_signature(request.headers.get("x-signature"), request.headers.get("x-request-id"),
                                     params.get("data.id")):
        logger.warning("Webhook de Mercado Pago con firma inválida (pago %s)", payment_id[:40])
        return {"received": True, "ignored": True, "reason": "invalid_signature"}
    if not payments.is_valid_payment_id(payment_id):
        return {"received": True, "ignored": True, "reason": "invalid_payment_id"}

    if not settings.payments_enabled:
        return {"received": True, "ignored": True, "reason": "payments_disabled"}

    # Split 1:1: el pago vive en la cuenta del refugio. Pistas para elegir su token si la plataforma no lo ve:
    # ?ref=order-12 (lo pone nuestra notification_url) y user_id (vendedor) del cuerpo. Solo eligen el token:
    # el pago se vuelve a consultar en Mercado Pago y se valida su external_reference y collector_id.
    ref_hint = params.get("ref") if REF_HINT_RE.match(params.get("ref") or "") else None
    seller = str(body.get("user_id") or "")
    seller = seller if seller.isdigit() and len(seller) <= 20 else None
    args = (payment_id, ref_hint, seller) if (ref_hint or seller) else (payment_id,)
    dispatch("app.tasks.payments.process_mercadopago_payment", *args, background_tasks=background_tasks)
    return {"received": True}


def _mp_connect_event(request: Request, body: dict, params) -> dict:
    """Aviso "mp-connect": un refugio desautorizó la aplicación desde su cuenta de Mercado Pago."""
    action = str(body.get("action") or "")
    seller = str(body.get("user_id") or "")
    # Sin secreto de firma no se puede confiar en el aviso: nadie debe poder desvincular a un refugio
    if not settings.mercadopago_webhook_secret or not payments.verify_signature(
            request.headers.get("x-signature"), request.headers.get("x-request-id"), params.get("data.id")):
        return {"received": True, "ignored": True, "reason": "invalid_signature"}
    if "deauthorized" not in action or not seller.isdigit():
        return {"received": True, "ignored": True}
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        account = mercadopago_oauth.account_for_mp_user(db, seller)
        if account and account.status != "disconnected":
            mercadopago_oauth.disconnect(account, "Desautorizada desde Mercado Pago.")
            db.commit()
            logger.info("Refugio %s desvinculó su cuenta de Mercado Pago", account.refuge_id)
    finally:
        db.close()
    return {"received": True}


@router.get("/payments/mercadopago/oauth/callback")
def mercadopago_oauth_callback(code: str | None = Query(None, max_length=200), state: str | None = Query(None, max_length=500),
                               error: str | None = Query(None, max_length=200), db: Session = Depends(get_db)):
    """Regreso de la autorización de Mercado Pago: guarda los tokens del refugio y vuelve a la app."""
    data = mercadopago_oauth.read_state(state)
    if error or not code or not data or not re.fullmatch(r"[A-Za-z0-9_\-]{4,200}", code):
        return RedirectResponse(settings.public_url("/app/#mp=error"), status_code=302)
    refuge = db.query(Refuge).filter(Refuge.id == data["r"], Refuge.user_id == data.get("u")).first()
    if not refuge:
        return RedirectResponse(settings.public_url("/app/#mp=error"), status_code=302)
    try:
        tokens = mercadopago_oauth.exchange_code(code)
    except mercadopago_oauth.OAuthError as exc:
        logger.warning("Vinculación de Mercado Pago fallida para el refugio %s: %s", refuge.id, exc)
        return RedirectResponse(settings.public_url("/app/#mp=error"), status_code=302)
    other = mercadopago_oauth.account_for_mp_user(db, tokens.get("user_id"))
    if other and other.refuge_id != refuge.id and other.status == "connected":
        logger.warning("La cuenta de MP %s ya está vinculada al refugio %s", tokens.get("user_id"), other.refuge_id)
        return RedirectResponse(settings.public_url("/app/#mp=error"), status_code=302)
    mercadopago_oauth.save_tokens(db, refuge.id, tokens)
    db.commit()
    return RedirectResponse(settings.public_url("/app/#mp=connected"), status_code=302)


@router.post("/admin/donations/{id}/resolve", response_model=AdminDonationOut)
def admin_resolve_donation(id: int, payload: PaymentResolveRequest, request: Request,
                           admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Donaciones en revisión: mark_paid acredita lo cobrado; refund la reembolsa en Mercado Pago."""
    donation = resolve_donation(db, id, admin_user, payload.action, payload.notes, request=request)
    out = AdminDonationOut.model_validate(donation).model_dump()
    out["refuge_name"] = donation.refuge.name if donation.refuge else None
    return out
