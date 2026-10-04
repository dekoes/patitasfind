import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, get_verified_user
from app.models import Donation, Order, User
from app.schemas import DonationCheckoutOut, DonationCreate, DonationOut
from app.services import payments
from app.services.background import dispatch
from app.services.payment_flow import create_donation_checkout

router = APIRouter(tags=["payments"])
logger = logging.getLogger(__name__)


@router.post("/payments/donations", response_model=DonationCheckoutOut, status_code=201)
def create_donation(payload: DonationCreate, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    return create_donation_checkout(db, current_user, payload.refuge_id, payload.amount, share_name=payload.share_name)


@router.get("/payments/donations/me", response_model=list[DonationOut])
def my_donations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Donation).filter(Donation.user_id == current_user.id).order_by(Donation.created_at.desc()).all()


@router.get("/payments/status")
def payment_status(
    order: int | None = Query(None),
    donation: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin = current_user.role in ("admin", "superadmin")
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
    return {"type": kind, "id": obj.id, "status": obj.status}


@router.post("/payments/mercadopago/webhook")
async def mercadopago_webhook(request: Request, background_tasks: BackgroundTasks):
    """Notificaciones de Mercado Pago (Webhooks e IPN). Siempre responde 200 rápido."""
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
    payment_id = params.get("data.id") or (body.get("data") or {}).get("id") or params.get("id")
    if not payment_id and isinstance(body.get("resource"), str) and topic == "payment":
        payment_id = body["resource"].rstrip("/").split("/")[-1]

    if topic != "payment" or not payment_id:
        return {"received": True, "ignored": True}

    payment_id = str(payment_id)
    if not payments.verify_signature(request.headers.get("x-signature"), request.headers.get("x-request-id"),
                                     params.get("data.id") or payment_id):
        logger.warning("Webhook de Mercado Pago con firma inválida (pago %s)", payment_id)
        return {"received": True, "ignored": True, "reason": "invalid_signature"}

    if not settings.payments_enabled:
        return {"received": True, "ignored": True, "reason": "payments_disabled"}

    dispatch("app.tasks.payments.process_mercadopago_payment", payment_id, background_tasks=background_tasks)
    return {"received": True}
