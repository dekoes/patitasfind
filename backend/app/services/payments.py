"""Mercado Pago Checkout Pro (México) con requests contra https://api.mercadopago.com.

Todas las llamadas aceptan `access_token`: sin él se usa la cuenta de la plataforma (MERCADOPAGO_ACCESS_TOKEN);
con el token OAuth de un refugio la operación ocurre en SU cuenta (Marketplace split 1:1).
"""
import datetime
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
    """Falla al hablar con Mercado Pago. `code` distingue casos que la UI explica (p. ej. "insufficient_balance")."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


INSUFFICIENT_BALANCE_DETAIL = (
    "La cuenta de Mercado Pago del refugio no tiene saldo disponible suficiente para este reembolso. "
    "El refugio debe ingresar saldo a su cuenta de Mercado Pago y volver a intentarlo."
)
# Señales de "saldo insuficiente" en la respuesta de /v1/payments/{id}/refunds. La referencia de reembolsos de
# Orders (Point) documenta `insufficient_money_for_refund` con HTTP 428; la de Payments no publica el código,
# así que también se buscan las palabras del mensaje.
_INSUFFICIENT_HINTS = ("insufficient", "insuficiente", "not enough", "without balance", "sin saldo")


def _headers(idempotency: bool = False, access_token: str | None = None) -> dict:
    token = access_token or settings.mercadopago_access_token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if idempotency:
        headers["X-Idempotency-Key"] = uuid.uuid4().hex
    return headers


def is_valid_payment_id(payment_id) -> bool:
    """Los ids de pago de Mercado Pago son numéricos; evita armar URLs con texto arbitrario."""
    value = str(payment_id or "")
    return value.isdigit() and len(value) <= 30


def _mp_date(value: datetime.datetime) -> str:
    """Fecha ISO 8601 con milisegundos y zona horaria, como la pide Mercado Pago."""
    return value.astimezone(datetime.timezone.utc).isoformat(timespec="milliseconds")


def create_preference(items: list[dict], external_reference: str, back_query: str, payer_email: str | None = None,
                      access_token: str | None = None, marketplace_fee=None, notification_query: str | None = None) -> dict:
    """items: [{title, quantity, unit_price}] -> {"id", "init_point"}. El link vence en CHECKOUT_EXPIRATION_MINUTES.

    Split 1:1: con `access_token` del refugio la preferencia (y el pago) quedan en su cuenta y Mercado Pago
    transfiere `marketplace_fee` (monto en MXN, no porcentaje; así se llama en Checkout Pro, en la API de pagos es
    `application_fee`) a la cuenta de la plataforma. MP descuenta
    primero su propia comisión y la del marketplace sale de lo que queda. `notification_url` sigue apuntando
    al webhook de la plataforma; `notification_query` agrega una pista (p. ej. "ref=order-12") para saber con
    qué token consultar el pago.
    """
    base = settings.public_url()
    now = datetime.datetime.now(datetime.timezone.utc)
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
        "notification_url": f"{base}/payments/mercadopago/webhook" + (f"?{notification_query}" if notification_query else ""),
        "statement_descriptor": "GUAUWOOW",
        # El inventario se aparta solo durante este tiempo; después ya no se puede pagar con este link
        "expires": True,
        "expiration_date_from": _mp_date(now),
        "expiration_date_to": _mp_date(now + datetime.timedelta(minutes=settings.checkout_expiration_minutes)),
    }
    if base.startswith("https://"):
        body["auto_return"] = "approved"  # MP exige back_urls https para auto_return
    if payer_email:
        body["payer"] = {"email": payer_email}
    if marketplace_fee is not None:
        body["marketplace_fee"] = float(Decimal(str(marketplace_fee)))
    try:
        resp = requests.post(f"{MP_API}/checkout/preferences", json=body, headers=_headers(True, access_token), timeout=20)
    except requests.RequestException as exc:
        raise PaymentError("No pudimos conectar con Mercado Pago. Inténtalo de nuevo.") from exc
    if resp.status_code >= 400:
        logger.error("Mercado Pago preference error %s: %s", resp.status_code, resp.text[:500])
        raise PaymentError("Mercado Pago rechazó la solicitud de pago.")
    data = resp.json()
    return {"id": data.get("id"), "init_point": data.get("init_point") or data.get("sandbox_init_point")}


def get_payment(payment_id: str, access_token: str | None = None) -> dict | None:
    """Consulta un pago. None si no existe o no es visible con ese token (401/403/404); PaymentError si Mercado
    Pago no responde (para reintentar)."""
    if not is_valid_payment_id(payment_id):
        return None
    try:
        resp = requests.get(f"{MP_API}/v1/payments/{payment_id}", headers=_headers(access_token=access_token), timeout=20)
    except requests.RequestException as exc:
        logger.error("No se pudo consultar el pago %s: %s", payment_id, exc)
        raise PaymentError("No pudimos conectar con Mercado Pago.") from exc
    if resp.status_code >= 500 or resp.status_code == 429:
        logger.error("Mercado Pago respondió %s al consultar el pago %s", resp.status_code, payment_id)
        raise PaymentError("Mercado Pago no está disponible.")
    if resp.status_code >= 400:
        logger.warning("Pago %s no encontrado en Mercado Pago (%s)", payment_id, resp.status_code)
        return None
    return resp.json()


def search_payments(external_reference: str, access_token: str | None = None) -> list[dict] | None:
    """Pagos asociados a una referencia ("order:12"). None si no se pudo consultar."""
    params = {"external_reference": external_reference, "sort": "date_created", "criteria": "desc", "limit": 20}
    try:
        resp = requests.get(f"{MP_API}/v1/payments/search", params=params, headers=_headers(access_token=access_token),
                            timeout=20)
    except requests.RequestException as exc:
        logger.warning("No se pudieron buscar los pagos de %s: %s", external_reference, exc)
        return None
    if resp.status_code >= 400:
        logger.warning("Mercado Pago respondió %s al buscar pagos de %s", resp.status_code, external_reference)
        return None
    return resp.json().get("results") or []


def refund_payment(payment_id: str, amount=None, access_token: str | None = None) -> dict:
    """Reembolso total (amount=None) o parcial de un pago aprobado. Devuelve el reembolso: {id, amount, status}.

    Lo que dice la documentación de Mercado Pago (consultada el 17-10-2026):
    - "Split de pagos 1:1 > Integrar marketplace": en caso de reembolso, el valor adeudado al comprador se divide
      y se resta de forma PROPORCIONAL de las partes involucradas (cuenta del refugio y cuenta del marketplace,
      es decir, también regresa la parte proporcional de `marketplace_fee`). En modelos 1:1 el marketplace NO
      puede hacer el reembolso total si el vendedor no tiene dinero en su cuenta: en ese caso solo puede
      reembolsar el equivalente a su parte y el resto es responsabilidad del vendedor, por otro medio.
    - "Cancelaciones y reembolsos": se puede reembolsar hasta 180 días después de la aprobación del pago, hace
      falta saldo disponible suficiente en la cuenta (si no, la operación no se concluye) y se debe enviar
      X-Idempotency-Key.
    El pago vive en la cuenta del refugio, así que se reembolsa con SU token (access_token). El dinero regresa al
    medio de pago original. Saldo insuficiente => PaymentError(code="insufficient_balance").
    """
    if not is_valid_payment_id(payment_id):
        raise PaymentError("El pago no tiene un id válido de Mercado Pago.")
    body = {"amount": float(Decimal(str(amount)))} if amount is not None else {}
    try:
        resp = requests.post(f"{MP_API}/v1/payments/{payment_id}/refunds", json=body,
                             headers=_headers(True, access_token), timeout=20)
    except requests.RequestException as exc:
        raise PaymentError("No pudimos conectar con Mercado Pago. Inténtalo de nuevo.") from exc
    if resp.status_code >= 400:
        logger.error("Mercado Pago refund error %s (pago %s): %s", resp.status_code, payment_id, resp.text[:500])
        text = (resp.text or "").lower()
        if resp.status_code == 428 or any(hint in text for hint in _INSUFFICIENT_HINTS):
            raise PaymentError(INSUFFICIENT_BALANCE_DETAIL, code="insufficient_balance")
        raise PaymentError("Mercado Pago no pudo reembolsar el pago. Revísalo en tu panel de Mercado Pago.")
    return resp.json()


def signature_manifest(data_id: str | None, x_request_id: str | None, ts: str) -> str:
    """Plantilla de la documentación: id:<data.id>;request-id:<x-request-id>;ts:<ts>;

    data.id viene del query string y va en minúsculas si es alfanumérico. Los valores ausentes se omiten.
    """
    manifest = ""
    if data_id:
        manifest += f"id:{data_id.lower() if data_id.isalnum() else data_id};"
    if x_request_id:
        manifest += f"request-id:{x_request_id};"
    manifest += f"ts:{ts};"
    return manifest


def verify_signature(x_signature: str | None, x_request_id: str | None, data_id: str | None) -> bool:
    """Valida el encabezado x-signature (ts=...,v1=...) según la documentación de Mercado Pago.

    data_id debe ser el parámetro `data.id` del query string (no el del cuerpo).
    """
    secret = settings.mercadopago_webhook_secret
    if not secret:
        return True
    if not x_signature:
        return False
    parts = {}
    for part in x_signature.split(","):
        key, sep, value = part.partition("=")
        if sep:
            parts[key.strip()] = value.strip()
    ts, v1 = parts.get("ts"), parts.get("v1")
    if not ts or not v1:
        return False
    manifest = signature_manifest(data_id, (x_request_id or "").strip() or None, ts)
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1.lower())
