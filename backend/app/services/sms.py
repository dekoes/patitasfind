"""Envío de SMS para la verificación de teléfono.

PatitasFind genera y valida su PROPIO código (ver app/services/otp.py); este módulo solo
entrega el mensaje. Así todos los proveedores comparten las mismas reglas (expiración,
intentos, límites) y cambiar de proveedor no cambia la API.

Proveedores (SMS_PROVIDER):
- smsmasivos (recomendado en México, ~$0.47–0.90 MXN por SMS): POST JSON a
  https://api.smsmasivos.com.mx/sms/send con encabezado `apikey`.
- twilio: Messages API (no Verify) con TWILIO_FROM_NUMBER o TWILIO_MESSAGING_SERVICE_SID.
- dev: no envía nada; el código se devuelve como `dev_code` (solo ENVIRONMENT=development).
"""
import logging
import re

import requests

from app.config import settings

logger = logging.getLogger(__name__)
TIMEOUT = 15
TWILIO_MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class SMSError(RuntimeError):
    pass


def normalize_mx_phone(raw: str | None) -> str | None:
    """Normaliza un celular mexicano a E.164 "+52XXXXXXXXXX" (10 dígitos nacionales).

    Acepta "55 1234 5678", "(55) 1234-5678", "+52 55 1234 5678", "52 55...", "521 55..."
    (prefijo móvil antiguo), "+521...", "0052..." y "044/045 55...". Devuelve None si no es válido.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or re.search(r"[^\d\s()+.\-]", text):
        return None
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and not digits.startswith("52"):
        return None  # solo números de México
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 13 and digits.startswith("521"):
        national = digits[3:]
    elif len(digits) == 13 and digits[:3] in ("044", "045"):
        national = digits[3:]
    elif len(digits) == 12 and digits.startswith("52"):
        national = digits[2:]
    elif len(digits) == 10:
        national = digits
    else:
        return None
    if not re.fullmatch(r"[2-9]\d{9}", national):
        return None  # las claves LADA en México empiezan con 2-9
    return f"+52{national}"


def otp_message(code: str) -> str:
    return f"PatitasFind: tu codigo es {code}. Vence en {settings.otp_ttl_minutes} min. No lo compartas con nadie."


def provider() -> str | None:
    return settings.sms_effective_provider


def is_configured() -> bool:
    return provider() is not None


def send_otp(phone_e164: str, code: str) -> str:
    """Envía el código. Devuelve el proveedor usado. Lanza SMSError si el envío falla."""
    name = provider()
    if name is None:
        raise SMSError("La verificación por SMS no está disponible en este momento.")
    message = otp_message(code)
    if name == "smsmasivos":
        _send_smsmasivos(phone_e164, message)
    elif name == "twilio":
        _send_twilio(phone_e164, message)
    else:
        logger.info("[sms:dev] SMS a %s: %s", phone_e164, message)
    return name


def _national(phone_e164: str) -> str:
    digits = re.sub(r"\D", "", phone_e164)
    return digits[-10:]


def _send_smsmasivos(phone_e164: str, message: str) -> None:
    payload = {"numbers": _national(phone_e164), "message": message, "country_code": "52"}
    if settings.smsmasivos_sandbox:
        payload["sandbox"] = 1
    try:
        resp = requests.post(
            settings.smsmasivos_url,
            json=payload,
            headers={"apikey": settings.smsmasivos_api_key or "", "Accept": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("SMS Masivos sin conexión: %s", exc)
        raise SMSError("No pudimos enviar el SMS, intenta de nuevo") from exc
    body_text = resp.text[:500]
    try:
        body = resp.json()
    except ValueError:
        body = None
    success_flag = body.get("success") if isinstance(body, dict) else None
    if resp.status_code >= 300 or success_flag is False or success_flag in ("false", 0):
        logger.error("SMS Masivos rechazó el envío (HTTP %s): %s", resp.status_code, body_text)
        raise SMSError("No pudimos enviar el SMS, intenta de nuevo")
    logger.info("SMS Masivos OK (HTTP %s, sandbox=%s)", resp.status_code, settings.smsmasivos_sandbox)


def _send_twilio(phone_e164: str, message: str) -> None:
    data = {"To": phone_e164, "Body": message}
    if settings.twilio_messaging_service_sid:
        data["MessagingServiceSid"] = settings.twilio_messaging_service_sid
    else:
        data["From"] = settings.twilio_from_number
    try:
        resp = requests.post(
            TWILIO_MESSAGES_URL.format(sid=settings.twilio_account_sid),
            data=data,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Twilio sin conexión: %s", exc)
        raise SMSError("No pudimos enviar el SMS, intenta de nuevo") from exc
    if resp.status_code >= 300:
        logger.error("Twilio rechazó el envío (HTTP %s): %s", resp.status_code, resp.text[:500])
        raise SMSError("No pudimos enviar el SMS, intenta de nuevo")
