"""Mercado Pago Marketplace (split 1:1): vinculación OAuth de la cuenta de cada refugio vendedor.

Con split cada refugio cobra con SU cuenta de Mercado Pago y GuauWoow solo recibe su comisión
(`marketplace_fee`), así la plataforma nunca custodia dinero de terceros (fiscal-tienda-22;
gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago-09 y 13).

Flujo según la documentación de Mercado Pago ("OAuth" y "Split de pagos 1:1 > Integrar marketplace"):
1. GET /refuges/me/payments/connect devuelve
   https://auth.mercadopago.com/authorization?client_id=<APP_ID>&response_type=code&platform_id=mp
   &state=<firmado>&redirect_uri=<PUBLIC_BASE_URL>/payments/mercadopago/oauth/callback
2. Mercado Pago regresa al callback con ?code=...&state=... (el código vale 10 minutos).
3. POST https://api.mercadopago.com/oauth/token {client_id, client_secret, code, grant_type="authorization_code",
   redirect_uri} -> {access_token, token_type, expires_in (15552000 s = 180 días), scope, user_id,
   refresh_token, public_key, live_mode}.
4. Antes de que venza se renueva en el mismo endpoint con grant_type="refresh_token"; la respuesta trae un
   refresh_token NUEVO que hay que guardar (el anterior deja de servir).

Los tokens se guardan cifrados (Fernet) con una llave derivada de SECRET_KEY: si cambia SECRET_KEY los
refugios deben volver a vincular su cuenta.
"""
import base64
import datetime
import logging
import secrets
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Refuge, RefugePaymentAccount

logger = logging.getLogger(__name__)

MP_AUTH_URL = "https://auth.mercadopago.com/authorization"
MP_TOKEN_URL = "https://api.mercadopago.com/oauth/token"
CALLBACK_PATH = "/payments/mercadopago/oauth/callback"
STATE_MAX_AGE_SECONDS = 15 * 60
CHECKOUT_REFRESH_MARGIN = datetime.timedelta(days=1)  # al cobrar: renovar si vence en menos de un día
TASK_REFRESH_MARGIN = datetime.timedelta(days=30)  # tarea semanal: renovar lo que vence en un mes
NOT_READY_DETAIL = "Este refugio aún no activa cobros."


class OAuthError(RuntimeError):
    pass


def _now():
    return datetime.datetime.utcnow()


# --------------------------------------------------------------------------- cifrado
def _fernet() -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"patitasfind-mp-oauth",
               info=b"refuge-payment-accounts").derive(settings.secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        logger.error("No se pudo descifrar un token de Mercado Pago (¿cambió SECRET_KEY?)")
        return None


# --------------------------------------------------------------------------- state firmado
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="mp-oauth-state")


def make_state(refuge_id: int, user_id: int) -> str:
    return _serializer().dumps({"r": refuge_id, "u": user_id, "n": secrets.token_hex(8)})


def read_state(state: str | None) -> dict | None:
    if not state:
        return None
    try:
        data = _serializer().loads(state, max_age=STATE_MAX_AGE_SECONDS)
    except BadSignature:  # incluye SignatureExpired
        return None
    return data if isinstance(data, dict) and isinstance(data.get("r"), int) else None


def redirect_uri() -> str:
    return settings.public_url(CALLBACK_PATH)


def authorization_url(refuge: Refuge, user_id: int) -> str:
    if not settings.marketplace_enabled:
        raise OAuthError("La vinculación con Mercado Pago no está configurada (MERCADOPAGO_APP_ID y "
                         "MERCADOPAGO_CLIENT_SECRET).")
    query = {
        "client_id": settings.mercadopago_app_id,
        "response_type": "code",
        "platform_id": "mp",
        "state": make_state(refuge.id, user_id),
        "redirect_uri": redirect_uri(),
    }
    return f"{MP_AUTH_URL}?{urlencode(query)}"


# --------------------------------------------------------------------------- tokens
def _token_request(body: dict) -> dict:
    payload = {"client_id": settings.mercadopago_app_id, "client_secret": settings.mercadopago_client_secret, **body}
    try:
        resp = requests.post(MP_TOKEN_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=20)
    except requests.RequestException as exc:
        raise OAuthError("No pudimos conectar con Mercado Pago. Inténtalo de nuevo.") from exc
    if resp.status_code >= 400:
        logger.warning("Mercado Pago OAuth respondió %s: %s", resp.status_code, resp.text[:300])
        raise OAuthError("Mercado Pago no autorizó la vinculación. Vuelve a intentarlo.")
    data = resp.json()
    if not data.get("access_token") or not data.get("user_id"):
        raise OAuthError("Mercado Pago respondió sin token de acceso.")
    return data


def exchange_code(code: str) -> dict:
    return _token_request({"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri()})


def _apply_tokens(account: RefugePaymentAccount, data: dict) -> None:
    now = _now()
    account.mp_user_id = str(data.get("user_id"))
    account.access_token_enc = encrypt(data["access_token"])
    if data.get("refresh_token"):
        account.refresh_token_enc = encrypt(data["refresh_token"])
    account.public_key = data.get("public_key") or account.public_key
    account.scope = (data.get("scope") or "")[:255] or None
    account.live_mode = data.get("live_mode")
    expires_in = int(data.get("expires_in") or 15552000)
    account.expires_at = now + datetime.timedelta(seconds=expires_in)
    account.refreshed_at = now
    account.status = "connected"
    account.last_error = None
    account.disconnected_at = None


def save_tokens(db: Session, refuge_id: int, data: dict) -> RefugePaymentAccount:
    """Guarda (cifrados) los tokens de la vinculación. Quien llama hace el commit."""
    account = db.query(RefugePaymentAccount).filter(RefugePaymentAccount.refuge_id == refuge_id).first()
    if not account:
        account = RefugePaymentAccount(refuge_id=refuge_id, provider="mercadopago")
        db.add(account)
    _apply_tokens(account, data)
    account.connected_at = _now()
    return account


def refresh_account(db: Session, account: RefugePaymentAccount) -> RefugePaymentAccount:
    """Renueva el access_token con el refresh_token (commit incluido). OAuthError si no se pudo."""
    refresh_token = decrypt(account.refresh_token_enc)
    if not refresh_token:
        raise OAuthError("La cuenta de Mercado Pago del refugio no tiene token de renovación; hay que volver a vincularla.")
    try:
        data = _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
    except OAuthError as exc:
        account.last_error = str(exc)
        if account.expires_at and account.expires_at <= _now():
            account.status = "error"  # ya venció y no se pudo renovar: se bloquean sus ventas
        db.commit()
        raise
    _apply_tokens(account, data)
    db.commit()
    return account


def account_usable(account: RefugePaymentAccount | None) -> bool:
    if not account or account.status != "connected" or not account.access_token_enc:
        return False
    if account.expires_at and account.expires_at <= _now() and not account.refresh_token_enc:
        return False
    return True


def seller_access_token(db: Session, account: RefugePaymentAccount | None,
                        margin: datetime.timedelta = CHECKOUT_REFRESH_MARGIN) -> str:
    """Access token vigente del refugio (lo renueva si está por vencer). OAuthError si no se puede usar."""
    if not account_usable(account):
        raise OAuthError(NOT_READY_DETAIL)
    if account.expires_at and account.expires_at - margin <= _now():
        refresh_account(db, account)
    token = decrypt(account.access_token_enc)
    if not token:
        raise OAuthError(NOT_READY_DETAIL)
    return token


def account_for_mp_user(db: Session, mp_user_id) -> RefugePaymentAccount | None:
    if mp_user_id in (None, ""):
        return None
    return db.query(RefugePaymentAccount).filter(RefugePaymentAccount.mp_user_id == str(mp_user_id)).first()


def disconnect(account: RefugePaymentAccount, reason: str | None = None) -> None:
    """Borra los tokens (la autorización también se puede revocar desde la cuenta de Mercado Pago)."""
    account.status = "disconnected"
    account.access_token_enc = None
    account.refresh_token_enc = None
    account.disconnected_at = _now()
    account.last_error = reason


def refuge_payments_ready(refuge: Refuge | None) -> bool:
    """¿Se le puede comprar (y donar por split) a este refugio hoy?

    - Desarrollo sin Mercado Pago: todo se simula, siempre True.
    - Con Mercado Pago: cuenta vinculada y usable; en producción además perfil fiscal con RFC
      (fiscal-tienda-19: no se vende sin RFC activo; los donativos sí se aceptan).
    """
    if refuge is None:
        return False
    if settings.payments_simulated:
        return True
    if not settings.payments_enabled:
        return False
    if not account_usable(refuge.payment_account):
        return False
    if settings.is_production and not (refuge.fiscal_profile and refuge.fiscal_profile.rfc):
        return False
    return True


def refuge_donations_ready(refuge: Refuge | None) -> bool:
    """¿Se le puede donar a este refugio hoy? Mismas reglas que create_donation_checkout.

    A diferencia de las ventas, los donativos NO exigen RFC (fiscal-tienda-19): basta la cuenta de Mercado Pago
    vinculada o, sin ella, el respaldo con la cuenta de la plataforma (DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT).
    """
    if refuge is None:
        return False
    if settings.payments_simulated:
        return True
    if not settings.payments_enabled:
        return False
    return account_usable(refuge.payment_account) or settings.effective_donations_fallback


def status_out(refuge: Refuge) -> dict:
    account = refuge.payment_account
    connected = account_usable(account)
    return {
        "connected": connected,
        "ready": refuge_payments_ready(refuge),
        "simulated": settings.payments_simulated,
        "marketplace_configured": settings.marketplace_enabled,
        "mp_user_id": account.mp_user_id if connected else None,
        "connected_at": account.connected_at if connected else None,
        "expires_at": account.expires_at if connected else None,
        "status": account.status if account else "not_connected",
        "last_error": account.last_error if account else None,
        "fee_percent": settings.mercadopago_marketplace_fee_percent,
        "donation_fee_percent": settings.mercadopago_donation_fee_percent,
        "fiscal_profile_complete": bool(refuge.fiscal_profile and refuge.fiscal_profile.rfc),
    }


def refresh_expiring_accounts(db: Session, margin: datetime.timedelta = TASK_REFRESH_MARGIN) -> dict:
    """Tarea semanal: renueva los tokens que vencen pronto (gap-custodia-...-09: renovar antes de 180 días).

    Solo refugios aprobados: un refugio cerrado (p. ej. su cuenta se eliminó) o suspendido no debe seguir
    renovando credenciales de una cuenta de Mercado Pago ajena.
    """
    result = {"refreshed": 0, "failed": 0}
    if not settings.marketplace_enabled:
        return result
    cutoff = _now() + margin
    ids = [a.id for a in db.query(RefugePaymentAccount.id).join(Refuge, Refuge.id == RefugePaymentAccount.refuge_id).filter(
        RefugePaymentAccount.status == "connected", RefugePaymentAccount.expires_at < cutoff,
        RefugePaymentAccount.refresh_token_enc.isnot(None), Refuge.status == "approved")]
    for account_id in ids:
        account = db.query(RefugePaymentAccount).filter(RefugePaymentAccount.id == account_id).first()
        try:
            refresh_account(db, account)
            result["refreshed"] += 1
        except OAuthError:
            result["failed"] += 1
            logger.warning("No se pudo renovar el token de Mercado Pago del refugio %s", account.refuge_id)
    return result
