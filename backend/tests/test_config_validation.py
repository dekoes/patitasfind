"""Validación de configuración de producción (app/config.py) y opciones de Sentry (app/observability.py)."""
import os

import pytest

from app import observability
from app.config import MIN_SECRET_KEY_LENGTH, Settings, _is_public_https, settings

_ENV_PREFIXES = ("CORS_", "WHATSAPP_", "SMS", "SMSMASIVOS_", "TWILIO_", "POSTGRES_", "ALLOW_DEMO", "SECRET_KEY",
                 "DATABASE_URL", "PUBLIC_BASE_URL", "SMTP_", "MERCADOPAGO_", "SHOP_", "REQUIRE_PHONE", "ENVIRONMENT",
                 "SENTRY_", "GIT_SHA")


@pytest.fixture
def clean_env(monkeypatch):
    """Quita del entorno del contenedor las variables que afectarían a Settings()."""
    for key in list(os.environ):
        if key.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)


def _prod_kwargs(**overrides):
    base = dict(
        _env_file=None, environment="production", secret_key="s" * 64,
        database_url="postgresql+psycopg2://patitasfind:Clave-Larga-De-Prod@postgres:5432/patitasfind",
        public_base_url="https://guauwoow.com", cors_origins="https://guauwoow.com,https://www.guauwoow.com",
        sms_provider="smsmasivos", smsmasivos_api_key="llave",
        smtp_host="smtp.ejemplo.mx", smtp_from="GuauWoow <no-reply@guauwoow.com>",
        private_files_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",  # 32 bytes en base64
    )
    base.update(overrides)
    return base


def _prod(**overrides):
    return Settings(**_prod_kwargs(**overrides))


def _problems(**overrides) -> str:
    with pytest.raises(Exception) as exc:
        _prod(**overrides)
    return str(exc.value)


def test_valid_production_config(clean_env):
    s = _prod()
    assert s.production_problems() == []
    assert s.public_base_url == "https://guauwoow.com"
    # La tienda arranca apagada en producción salvo SHOP_ENABLED=true explícito
    assert s.effective_shop_enabled is False
    assert _prod(public_base_url="https://guauwoow.com/").public_base_url == "https://guauwoow.com"


def test_development_never_blocks(clean_env):
    s = Settings(_env_file=None, environment="development")
    assert s.production_problems()  # tendría problemas en producción...
    assert s.is_development  # ...pero en desarrollo arranca igual


def test_all_problems_reported_together(clean_env):
    msg = _problems(secret_key="dev-secret-key-change-in-production", public_base_url=None, cors_origins=None,
                    smtp_host=None, smtp_from=None, mercadopago_access_token="APP_USR-1",
                    whatsapp_access_token="EAAG", shop_enabled=True)
    for needle in ("SECRET_KEY", "PUBLIC_BASE_URL", "CORS_ORIGINS", "SMTP_HOST y SMTP_FROM",
                   "MERCADOPAGO_WEBHOOK_SECRET", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN"):
        assert needle in msg, needle
    assert "ENVIRONMENT=production" in msg and "problema(s)" in msg
    # Con token de Mercado Pago los pagos están activos: la tienda no se queja de pagos
    assert "Configura los pagos" not in msg


def test_secret_key_length(clean_env):
    assert "muy corta" in _problems(secret_key="a" * (MIN_SECRET_KEY_LENGTH - 1))
    assert _prod(secret_key="a" * MIN_SECRET_KEY_LENGTH).production_problems() == []


@pytest.mark.parametrize("url", [
    "http://guauwoow.com", "https://localhost", "https://localhost:8443", "https://127.0.0.1",
    "https://app.localhost", "guauwoow.com", "http://localhost:8082",
])
def test_public_base_url_must_be_public_https(clean_env, url):
    assert "PUBLIC_BASE_URL" in _problems(public_base_url=url)


@pytest.mark.parametrize("origins", [
    "http://guauwoow.com", "https://guauwoow.com,http://localhost:8082", "https://localhost",
    "https://guauwoow.com,https://127.0.0.1:8443", "*",
])
def test_cors_origins_must_be_public_https(clean_env, origins):
    assert "CORS_ORIGINS" in _problems(cors_origins=origins)


def test_smtp_required(clean_env):
    assert "SMTP_HOST" in _problems(smtp_host=None)
    msg = _problems(smtp_from=None)
    assert "SMTP_FROM" in msg and "SMTP_HOST" not in msg


def test_mercadopago_webhook_secret(clean_env):
    assert "MERCADOPAGO_WEBHOOK_SECRET" in _problems(mercadopago_access_token="APP_USR-1")
    s = _prod(mercadopago_access_token="APP_USR-1", mercadopago_webhook_secret="firma")
    assert s.payments_enabled and s.production_problems() == []


def test_whatsapp_requirements(clean_env):
    assert "WHATSAPP_APP_SECRET" in _problems(whatsapp_access_token="EAAG", whatsapp_verify_token="token-propio-largo")
    assert "WHATSAPP_VERIFY_TOKEN" in _problems(whatsapp_access_token="EAAG", whatsapp_app_secret="s")
    ok = _prod(whatsapp_access_token="EAAG", whatsapp_app_secret="s", whatsapp_verify_token="token-propio-largo")
    assert ok.production_problems() == []


def test_shop_requires_payments(clean_env):
    assert "SHOP_ENABLED" in _problems(shop_enabled=True)
    # Con split (Mercado Pago Marketplace) también hacen falta las credenciales de la aplicación OAuth
    assert "MERCADOPAGO_APP_ID" in _problems(shop_enabled=True, mercadopago_access_token="APP_USR-1",
                                             mercadopago_webhook_secret="firma")
    shop = dict(shop_enabled=True, mercadopago_access_token="APP_USR-1", mercadopago_webhook_secret="firma",
                mercadopago_app_id="123", mercadopago_client_secret="secreto")
    # Con comisión > 0 hace falta el PAC y los datos del emisor (fiscal-tienda-07; gap-custodia-01)
    assert "PAC_PROVIDER" in _problems(**shop, mercadopago_marketplace_fee_percent=10)
    s = _prod(**shop, mercadopago_marketplace_fee_percent=0)
    assert s.effective_shop_enabled and s.production_problems() == []
    pac = dict(pac_provider="facturama", pac_user="u", pac_password="p", emisor_rfc="PFI010101AB2",
               emisor_nombre="PATITASFIND", emisor_regimen="601", emisor_cp="06600")
    # Además, cobrar comisión exige confirmar el régimen de plataformas (PLATFORM_TAX_REGIME_READY; reglas de negocio)
    assert "PLATFORM_TAX_REGIME_READY" in _problems(**shop, **pac, mercadopago_marketplace_fee_percent=10)
    assert _prod(**shop, **pac, mercadopago_marketplace_fee_percent=10,
                 platform_tax_regime_ready=True).production_problems() == []
    # Apagada explícitamente no exige pagos
    assert _prod(shop_enabled=False).production_problems() == []


def test_jwt_algorithm_must_be_hmac(clean_env):
    assert "ALGORITHM=RS256" in _problems(algorithm="RS256")
    assert _prod(algorithm="HS512").production_problems() == []


def test_existing_checks_kept(clean_env):
    assert "PostgreSQL" in _problems(database_url="postgresql+psycopg2://patitasfind:patitasfind@postgres:5432/patitasfind")
    assert "trycloudflare" in _problems(cors_origin_regex=r"https://.*\.trycloudflare\.com")
    assert "SMS_PROVIDER=dev" in _problems(sms_provider="dev")


def test_env_variables_are_read(clean_env, monkeypatch):
    """Los valores llegan desde el entorno (como en Docker), y las variables vacías cuentan como no definidas."""
    for key, value in _prod_kwargs().items():
        if not key.startswith("_"):
            monkeypatch.setenv(key.upper(), str(value))
    monkeypatch.setenv("SMTP_FROM", "")
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None)
    assert "SMTP_FROM" in str(exc.value)


def test_is_public_https():
    assert _is_public_https("https://guauwoow.com")
    assert _is_public_https("https://www.guauwoow.com:8443/ruta")
    for url in ("http://guauwoow.com", "https://", "https://localhost", "https://0.0.0.0", "ftp://guauwoow.com", ""):
        assert not _is_public_https(url), url


# --------------------------------------------------------------------------- Sentry
def test_sentry_environment_and_release(monkeypatch):
    monkeypatch.setattr(settings, "sentry_environment", None)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "git_sha", None)
    opts = observability.sentry_options()
    assert opts["environment"] == "production" and "release" not in opts
    assert opts["send_default_pii"] is False and opts["before_send"] is observability._before_send

    monkeypatch.setattr(settings, "sentry_environment", "staging")
    monkeypatch.setattr(settings, "git_sha", " 1a2b3c4 ")
    opts = observability.sentry_options()
    assert opts["environment"] == "staging"
    assert opts["release"] == "patitasfind@1a2b3c4" == observability.sentry_release()


def test_git_sha_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    assert Settings(_env_file=None).git_sha == "abc1234"
