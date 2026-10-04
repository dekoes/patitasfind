"""Verificación de teléfono con Twilio Verify (REST con requests)."""
import logging
import re

import requests

from app.config import settings

logger = logging.getLogger(__name__)
VERIFY_BASE = "https://verify.twilio.com/v2/Services"


class OTPError(RuntimeError):
    pass


def normalize_phone(phone: str) -> str:
    """Convierte a E.164. Números de 10 dígitos se asumen de México (+52)."""
    raw = (phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if len(digits) == 10:
        return f"+{settings.default_phone_country_code}{digits}"
    if digits.startswith(settings.default_phone_country_code) and len(digits) >= 12:
        return "+" + digits
    return "+" + digits


def _auth():
    return (settings.twilio_account_sid, settings.twilio_auth_token)


def send_verification(phone: str) -> None:
    url = f"{VERIFY_BASE}/{settings.twilio_verify_service_sid}/Verifications"
    try:
        resp = requests.post(url, data={"To": normalize_phone(phone), "Channel": settings.twilio_channel}, auth=_auth(), timeout=15)
    except requests.RequestException as exc:
        raise OTPError("No pudimos contactar al servicio de SMS. Inténtalo más tarde.") from exc
    if resp.status_code >= 400:
        logger.error("Twilio Verify error %s: %s", resp.status_code, resp.text[:300])
        raise OTPError("No pudimos enviar el código. Revisa que tu número sea correcto.")


def check_verification(phone: str, code: str) -> bool:
    url = f"{VERIFY_BASE}/{settings.twilio_verify_service_sid}/VerificationCheck"
    try:
        resp = requests.post(url, data={"To": normalize_phone(phone), "Code": code}, auth=_auth(), timeout=15)
    except requests.RequestException as exc:
        raise OTPError("No pudimos contactar al servicio de SMS. Inténtalo más tarde.") from exc
    if resp.status_code == 404:
        return False  # verificación expirada o inexistente
    if resp.status_code >= 400:
        logger.error("Twilio VerificationCheck error %s: %s", resp.status_code, resp.text[:300])
        return False
    return resp.json().get("status") == "approved"
