from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-secret-key-change-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # --- Núcleo ---
    environment: str = "development"
    database_url: str = "postgresql+psycopg2://patitasfind:patitasfind@localhost:5432/patitasfind"
    secret_key: str = DEV_SECRET_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 días
    public_base_url: str | None = None  # p. ej. https://patitasfind.mx (sin "/" final)
    allow_demo_login: bool | None = None  # None => True solo en development

    # --- CORS ---
    cors_origins: str = (
        "http://localhost:8080,http://localhost:8081,http://localhost:8082,"
        "http://localhost:3000,http://127.0.0.1:5500,http://127.0.0.1:8082"
    )
    cors_origin_regex: str | None = r"https://.*\.trycloudflare\.com"

    # --- Archivos ---
    upload_dir: str = "uploads"
    max_upload_mb: int = 10

    # --- Google OAuth ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8001/auth/google/callback"

    # --- Redis / Celery ---
    redis_url: str | None = None
    cache_ttl_seconds: int = 300
    use_celery: bool | None = None  # None => True si hay REDIS_URL

    # --- IA (Anthropic Claude) ---
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "low"
    anthropic_use_fallbacks: bool = True
    match_score_threshold: int = 60

    # --- Mercado Pago ---
    mercadopago_access_token: str | None = None
    mercadopago_webhook_secret: str | None = None
    currency: str = "MXN"

    # --- Twilio Verify (OTP) ---
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_verify_service_sid: str | None = None
    twilio_channel: str = "sms"  # sms | whatsapp
    default_phone_country_code: str = "52"

    # --- SMTP ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    # --- WhatsApp Cloud API (Meta) ---
    whatsapp_verify_token: str = "patitasfind-dev-token"
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: str | None = None
    graph_api_version: str = "v21.0"

    # --- Facebook Pages ---
    facebook_page_access_token: str | None = None
    facebook_groups: str | None = None  # obsoleto, se conserva por compatibilidad

    @model_validator(mode="after")
    def _check_production(self):
        if self.is_production and self.secret_key == DEV_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY usa el valor de desarrollo. Define una clave larga y aleatoria antes de arrancar en producción."
            )
        if self.public_base_url:
            self.public_base_url = self.public_base_url.rstrip("/")
        return self

    # --- Propiedades derivadas ---
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def demo_enabled(self) -> bool:
        if self.allow_demo_login is None:
            return self.is_development
        return self.allow_demo_login

    @property
    def celery_enabled(self) -> bool:
        if self.use_celery is None:
            return bool(self.redis_url)
        return self.use_celery and bool(self.redis_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def payments_enabled(self) -> bool:
        return bool(self.mercadopago_access_token)

    @property
    def otp_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_verify_service_sid)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.whatsapp_access_token and self.whatsapp_phone_number_id)

    @property
    def facebook_enabled(self) -> bool:
        return bool(self.facebook_page_access_token)

    def public_url(self, path: str = "") -> str:
        base = self.public_base_url or "http://localhost:8082"
        return f"{base}{path}"


settings = Settings()
