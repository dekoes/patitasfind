from authlib.integrations.requests_client import OAuth2Session

from app.config import settings

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_ACCESS_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPE = "openid email profile"


def is_google_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def get_google_session() -> OAuth2Session:
    if not is_google_configured():
        raise RuntimeError("Google OAuth no está configurado. Define GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET.")
    return OAuth2Session(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scope=GOOGLE_SCOPE,
    )


def get_google_authorize_url(redirect_uri: str | None = None) -> str:
    session = get_google_session()
    uri, _ = session.create_authorization_url(
        GOOGLE_AUTHORIZE_URL,
        redirect_uri=redirect_uri or settings.google_redirect_uri,
        access_type="offline",
        prompt="select_account",
    )
    return uri


def get_google_userinfo(code: str, redirect_uri: str | None = None) -> dict:
    session = get_google_session()
    session.fetch_token(
        GOOGLE_ACCESS_TOKEN_URL,
        authorization_response=code,
        redirect_uri=redirect_uri or settings.google_redirect_uri,
        grant_type="authorization_code",
    )
    resp = session.get(GOOGLE_USERINFO_URL)
    resp.raise_for_status()
    return resp.json()
