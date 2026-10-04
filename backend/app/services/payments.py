"""Mercado Pago Checkout Pro (México) con requests contra https://api.mercadopago.com."""
import hashlib
import hmac
import logging
import uuid
from decimal import Decimal

import requests

from app.config import settings

logger = logging.getLogger(__name__)
MP_API = "https://api.mercadopago.com"


class PaymentError(RuntimeError):
    pass


def _headers(idempotency: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {settings.mercadopago_access_token}", "Content-Type": "application/json"}
    if idempotency:
        headers["X-Idempotency-Key"] = uuid.uuid4().hex
    return headers


def create_preference(items: list[dict], external_reference: str, back_query: str, payer_email: str | None = None) -> dict:
    """items: [{title, quantity, unit_price}] -> {"id", "init_point"}."""
    base = settings.public_url()
    body = {
        "items": [
            {
                "title": i["title"][:250],
                "quantity": int(i["quantity"]),
                "unit_price": float(Decimal(str(i["unit_price"]))),
                "currency_id": settings.currency,
            }
            for i in items
        ],
        "external_reference": external_reference,
        "back_urls": {
            "success": f"{base}/app/?payment=success&{back_query}",
            "failure": f"{base}/app/?payment=failure&{back_query}",
            "pending": f"{base}/app/?payment=pending&{back_query}",
        },
        "notification_url": f"{base}/payments/mercadopago/webhook",
        "statement_descriptor": "PATITASFIND",
    }
    if base.startswith("https://"):
        body["auto_return"] = "approved"  # MP exige back_urls https para auto_return
    if payer_email:
        body["payer"] = {"email": payer_email}
    try:
        resp = requests.post(f"{MP_API}/checkout/preferences", json=body, headers=_headers(True), timeout=20)
    except requests.RequestException as exc:
        raise PaymentError("No pudimos conectar con Mercado Pago. Inténtalo de nuevo.") from exc
    if resp.status_code >= 400:
        logger.error("Mercado Pago preference error %s: %s", resp.status_code, resp.text[:500])
        raise PaymentError("Mercado Pago rechazó la solicitud de pago.")
    data = resp.json()
    return {"id": data.get("id"), "init_point": data.get("init_point") or data.get("sandbox_init_point")}


def get_payment(payment_id: str) -> dict | None:
    try:
        resp = requests.get(f"{MP_API}/v1/payments/{payment_id}", headers=_headers(), timeout=20)
    except requests.RequestException as exc:
        logger.error("No se pudo consultar el pago %s: %s", payment_id, exc)
        return None
    if resp.status_code >= 400:
        logger.warning("Pago %s no encontrado en Mercado Pago (%s)", payment_id, resp.status_code)
        return None
    return resp.json()


def verify_signature(x_signature: str | None, x_request_id: str | None, data_id: str | None) -> bool:
    """Valida el encabezado x-signature (ts=...,v1=...) según la documentación de Mercado Pago."""
    secret = settings.mercadopago_webhook_secret
    if not secret:
        return True
    if not x_signature:
        return False
    parts = dict(p.strip().split("=", 1) for p in x_signature.split(",") if "=" in p)
    ts, v1 = parts.get("ts"), parts.get("v1")
    if not ts or not v1:
        return False
    manifest = ""
    if data_id:
        manifest += f"id:{data_id.lower() if data_id.isalnum() else data_id};"
    if x_request_id:
        manifest += f"request-id:{x_request_id};"
    manifest += f"ts:{ts};"
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
