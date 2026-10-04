"""Google OAuth 2.0 (flujo de código) con `requests` y `state` firmado contra CSRF."""
import secrets
from urllib.parse import urlencode

import requests
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_ACCESS_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPE = "openid email profile"
STATE_COOKIE = "pf_oauth_state"
STATE_MAX_AGE = 600  # 10 minutos
TIMEOUT = 15


class OAuthError(RuntimeError):
    pass


def is_google_configured() -> bool:
    return settings.google_enabled


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="google-oauth-state")


def create_state(extra: dict | None = None) -> tuple[str, str]:
    """Devuelve (state firmado, nonce). El nonce va también en una cookie HttpOnly."""
    nonce = secrets.token_urlsafe(24)
    return _serializer().dumps({"n": nonce, **(extra or {})}), nonce


def verify_state(state: str | None, cookie_nonce: str | None) -> dict:
    """Valida firma, vigencia (10 min) y que coincida con la cookie del mismo navegador."""
    if not state or not cookie_nonce:
        raise OAuthError("La sesión de inicio con Google expiró. Inténtalo de nuevo.")
    try:
        data = _serializer().loads(state, max_age=STATE_MAX_AGE)
    except SignatureExpired as exc:
        raise OAuthError("La sesión de inicio con Google expiró. Inténtalo de nuevo.") from exc
    except BadSignature as exc:
        raise OAuthError("Solicitud de inicio de sesión no válida.") from exc
    if not isinstance(data, dict) or not secrets.compare_digest(str(data.get("n", "")), cookie_nonce):
        raise OAuthError("Solicitud de inicio de sesión no válida.")
    return data


def get_google_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "state": state,
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str, redirect_uri: str) -> dict:
    try:
        resp = requests.post(GOOGLE_ACCESS_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise OAuthError(f"Sin conexión con Google: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthError(f"Google rechazó el código (HTTP {resp.status_code}): {resp.text[:200]}")
    token = resp.json()
    if not token.get("access_token"):
        raise OAuthError("Google no devolvió access_token.")
    return token


def fetch_userinfo(access_token: str) -> dict:
    try:
        resp = requests.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise OAuthError(f"Sin conexión con Google: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthError(f"No se pudo leer el perfil de Google (HTTP {resp.status_code}).")
    return resp.json()


def get_google_userinfo(code: str, redirect_uri: str) -> dict:
    token = exchange_code(code, redirect_uri)
    return fetch_userinfo(token["access_token"])
