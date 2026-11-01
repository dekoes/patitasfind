"""Verificación en dos pasos (TOTP, RFC 6238) para el personal administrador, solo con la biblioteca estándar.

- Secreto de 20 bytes en base32 (lo que leen Google Authenticator, Authy, 1Password, etc.), guardado cifrado
  (crypto_storage.encrypt_text). Códigos de 6 dígitos cada 30 s, SHA-1, con tolerancia de ±1 intervalo.
- Un código ya usado no se acepta otra vez (User.mfa_last_step): evita que se reutilice uno interceptado.
- 10 códigos de recuperación de un solo uso, guardados con PBKDF2-HMAC-SHA256 y sal propia.
- Al iniciar sesión, un admin recibe primero un mfa_token (JWT de 5 minutos con purpose="mfa", ligado a la
  contraseña y a token_version) y solo con el código obtiene la sesión, que lleva el claim "mfa": 1.
- Es obligatoria cuando MFA_REQUIRED_FOR_ADMINS es true (por defecto en todo entorno salvo development).
"""
import base64
import datetime
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from jose import JWTError, jwt

from app.config import settings

ADMIN_ROLES = ("admin", "superadmin")
DIGITS = 6
PERIOD = 30
WINDOW = 1  # intervalos de tolerancia antes y después (relojes desfasados)
SECRET_BYTES = 20
RECOVERY_CODES = 10
RECOVERY_ITERATIONS = 100_000
MFA_TOKEN_MINUTES = 5
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # sin 0/o ni 1/l/i para dictarlos sin errores


# --------------------------------------------------------------------------- RFC 4226 / 6238
def b32_secret(raw: bytes | None = None) -> str:
    return base64.b32encode(raw or secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _b32_bytes(secret: str) -> bytes:
    clean = "".join((secret or "").split()).upper()
    return base64.b32decode(clean + "=" * (-len(clean) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS, algorithm: str = "sha1") -> str:
    """HOTP (RFC 4226): truncado dinámico del HMAC del contador."""
    mac = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, algorithm)).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_at(key: bytes, for_time: float, digits: int = DIGITS, period: int = PERIOD, algorithm: str = "sha1") -> str:
    """TOTP (RFC 6238) para un instante (segundos Unix)."""
    return hotp(key, int(for_time // period), digits, algorithm)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def matching_step(secret: str, code: str, now: float | None = None, last_step: int | None = None) -> int | None:
    """Intervalo en el que el código es válido (±WINDOW), o None. Rechaza los ya usados (<= last_step)."""
    code = "".join(c for c in str(code or "") if c.isdigit())
    if len(code) != DIGITS:
        return None
    try:
        key = _b32_bytes(secret)
    except (ValueError, TypeError):
        return None
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(hotp(key, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str, issuer: str | None = None) -> str:
    """otpauth://totp/... para el código QR (formato de Google Authenticator Key Uri)."""
    issuer = issuer or settings.mfa_issuer
    label = quote(f"{issuer}:{account}", safe="@:")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}")


# --------------------------------------------------------------------------- códigos de recuperación
def new_recovery_codes(n: int = RECOVERY_CODES) -> list[str]:
    def one():
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"
    return [one() for _ in range(n)]


def normalize_recovery_code(code: str | None) -> str:
    return "".join(c for c in (code or "").lower() if c.isalnum())


def hash_recovery_code(code: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", normalize_recovery_code(code).encode(), salt, RECOVERY_ITERATIONS)
    return f"pbkdf2${RECOVERY_ITERATIONS}${salt.hex()}${digest.hex()}"


def recovery_code_matches(code: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", normalize_recovery_code(code).encode(), bytes.fromhex(salt_hex),
                                     int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def looks_like_recovery_code(code: str | None) -> bool:
    return len(normalize_recovery_code(code)) == 10 and not normalize_recovery_code(code).isdigit()


# --------------------------------------------------------------------------- política
def mfa_required() -> bool:
    """MFA_REQUIRED_FOR_ADMINS; vacío => obligatoria en todo entorno salvo development."""
    if settings.mfa_required_for_admins is None:
        return not settings.is_development
    return bool(settings.mfa_required_for_admins)


def user_has_mfa(user) -> bool:
    return bool(getattr(user, "mfa_enabled_at", None) and getattr(user, "mfa_secret_enc", None))


def login_needs_mfa(user) -> bool:
    """Los admins con MFA activa siempre pasan por el segundo paso; si es obligatoria, también los que no la tienen."""
    return user.role in ADMIN_ROLES and (user_has_mfa(user) or mfa_required())


def session_mfa_ok(user, payload: dict | None) -> bool:
    """¿La sesión de este admin cumple la política? (la usa require_admin)."""
    if user.role not in ADMIN_ROLES:
        return True
    if not (user_has_mfa(user) or mfa_required()):
        return True
    return bool(payload and payload.get("mfa") == 1)


# --------------------------------------------------------------------------- mfa_token
def _password_fp(user) -> str:
    return hashlib.sha256(f"mfa:{user.hashed_password or 'sin-password'}".encode()).hexdigest()[:16]


def create_mfa_token(user, enroll: bool = False) -> str:
    """Comprobante del primer paso (contraseña o Google): vale 5 minutos y solo sirve para el segundo paso."""
    return jwt.encode(
        {
            "sub": str(user.id), "purpose": "mfa", "tv": user.token_version or 0, "fp": _password_fp(user),
            "enroll": 1 if enroll else 0,
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=MFA_TOKEN_MINUTES),
        },
        settings.secret_key, algorithm=settings.algorithm,
    )


def decode_mfa_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    return payload if payload.get("purpose") == "mfa" else None


def mfa_token_matches(payload: dict, user) -> bool:
    """El comprobante deja de servir si cambió la contraseña o se cerraron las sesiones."""
    try:
        tv_ok = int(payload.get("tv", -1)) == (user.token_version or 0)
    except (TypeError, ValueError):
        return False
    return tv_ok and hmac.compare_digest(str(payload.get("fp", "")), _password_fp(user))
