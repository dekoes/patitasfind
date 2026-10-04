from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-secret-key-change-in-production"
DEV_POSTGRES_PASSWORD = "patitasfind"
DEV_WHATSAPP_VERIFY_TOKEN = "patitasfind-dev-token"
DEV_CORS_ORIGINS = (
    "http://localhost:8080,http://localhost:8081,http://localhost:8082,"
    "http://localhost:3000,http://127.0.0.1:5500,http://127.0.0.1:8082"
)
DEV_CORS_ORIGIN_REGEX = r"https://.*\.trycloudflare\.com"
DEMO_EMAIL = "demo@patitasfind.example.com"
SMS_PROVIDERS = ("smsmasivos", "twilio", "dev")
AI_PROVIDERS = ("openai_compatible",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # --- Núcleo ---
    environment: str = "development"
    database_url: str = "postgresql+psycopg2://patitasfind:patitasfind@localhost:5432/patitasfind"
    postgres_password: str | None = None  # solo para validar en producción (lo usa el contenedor de Postgres)
    secret_key: str = DEV_SECRET_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 días
    public_base_url: str | None = None  # p. ej. https://patitasfind.mx (sin "/" final)
    allow_demo_login: bool | None = None  # None => True solo en development (nunca en production)

    # --- CORS ---
    # Vacío => en development se usan los orígenes locales; en production es obligatorio.
    cors_origins: str | None = None
    # Vacío => en development se permiten túneles *.trycloudflare.com; en production ninguno.
    cors_origin_regex: str | None = None

    # --- Archivos ---
    upload_dir: str = "uploads"
    max_upload_mb: int = 10

    # --- Google OAuth ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Opcional: si se omite se usa {PUBLIC_BASE_URL}/auth/google/callback
    google_redirect_uri: str | None = None

    # --- Redis / Celery ---
    redis_url: str | None = None
    cache_ttl_seconds: int = 300
    use_celery: bool | None = None  # None => True si hay REDIS_URL

    # --- IA de visión (API compatible con OpenAI Chat Completions) ---
    ai_provider: str = "openai_compatible"
    ai_api_key: str | None = None
    ai_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    ai_model: str = "qwen3-vl-flash"
    ai_timeout_seconds: float = 20.0
    ai_extra_body: str | None = None  # JSON opcional que se agrega al cuerpo, p. ej. {"enable_thinking": false}
    match_score_threshold: int = 60

    # --- Mercado Pago ---
    mercadopago_access_token: str | None = None
    mercadopago_webhook_secret: str | None = None
    currency: str = "MXN"

    # --- Verificación de teléfono (OTP propio + proveedor de SMS) ---
    sms_provider: str = "smsmasivos"  # smsmasivos | twilio | dev
    require_phone_verification: bool = True
    smsmasivos_api_key: str | None = None
    smsmasivos_sandbox: bool = False
    smsmasivos_url: str = "https://api.smsmasivos.com.mx/sms/send"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None  # +1..., o usa TWILIO_MESSAGING_SERVICE_SID
    twilio_messaging_service_sid: str | None = None
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_sends_per_phone_hour: int = 5
    otp_max_sends_per_ip_hour: int = 10
    default_phone_country_code: str = "52"

    # --- Legal ---
    legal_terms_version: str = "2026-10-04"
    legal_privacy_version: str = "2026-10-04"

    # --- Observabilidad (todo opcional) ---
    sentry_dsn: str | None = None
    sentry_environment: str | None = None  # por defecto = ENVIRONMENT
    sentry_traces_sample_rate: float = 0.1
    sentry_dsn_frontend: str | None = None
    posthog_key: str | None = None
    posthog_host: str = "https://us.i.posthog.com"

    # --- SMTP ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    # --- WhatsApp Cloud API (Meta) ---
    whatsapp_verify_token: str = DEV_WHATSAPP_VERIFY_TOKEN
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: str | None = None
    graph_api_version: str = "v21.0"

    # --- Facebook Pages ---
    facebook_page_access_token: str | None = None
    facebook_groups: str | None = None  # obsoleto, se conserva por compatibilidad

    @model_validator(mode="after")
    def _check_settings(self):
        if self.public_base_url:
            self.public_base_url = self.public_base_url.rstrip("/")
        if self.ai_base_url:
            self.ai_base_url = self.ai_base_url.rstrip("/")
        self.sms_provider = (self.sms_provider or "").strip().lower()
        if self.sms_provider not in SMS_PROVIDERS:
            raise ValueError(f"SMS_PROVIDER debe ser uno de {', '.join(SMS_PROVIDERS)} (recibido: {self.sms_provider!r}).")
        self.ai_provider = (self.ai_provider or "").strip().lower()
        if self.ai_provider not in AI_PROVIDERS:
            raise ValueError(f"AI_PROVIDER debe ser uno de {', '.join(AI_PROVIDERS)} (recibido: {self.ai_provider!r}).")
        if self.is_production:
            problems = self.production_problems()
            if problems:
                raise ValueError(
                    "Configuración insegura para ENVIRONMENT=production; el backend no arrancará:\n  - "
                    + "\n  - ".join(problems)
                )
        return self

    def production_problems(self) -> list[str]:
        problems = []
        if self.secret_key == DEV_SECRET_KEY:
            problems.append("SECRET_KEY usa el valor de desarrollo. Define una clave larga y aleatoria.")
        if not self.cors_origin_list:
            problems.append("CORS_ORIGINS está vacío. Define tu dominio, p. ej. CORS_ORIGINS=https://patitasfind.mx")
        if self.cors_origin_regex and "trycloudflare" in self.cors_origin_regex:
            problems.append("CORS_ORIGIN_REGEX permite túneles *.trycloudflare.com; déjalo vacío en producción.")
        if self._db_password() == DEV_POSTGRES_PASSWORD or self.postgres_password == DEV_POSTGRES_PASSWORD:
            problems.append("La contraseña de PostgreSQL es la de desarrollo ('patitasfind'). Cambia POSTGRES_PASSWORD y DATABASE_URL.")
        if self.whatsapp_access_token:
            if not self.whatsapp_app_secret:
                problems.append("WhatsApp está activo pero falta WHATSAPP_APP_SECRET (firma de los webhooks).")
            if not self.whatsapp_verify_token or self.whatsapp_verify_token == DEV_WHATSAPP_VERIFY_TOKEN:
                problems.append("WhatsApp está activo pero WHATSAPP_VERIFY_TOKEN falta o es el de desarrollo.")
        if self.sms_provider == "dev" and self.require_phone_verification:
            problems.append("SMS_PROVIDER=dev no envía SMS reales. Usa smsmasivos o twilio en producción.")
        elif self.require_phone_verification and self.sms_effective_provider is None:
            problems.append(f"REQUIRE_PHONE_VERIFICATION=true pero SMS_PROVIDER={self.sms_provider} no tiene llaves "
                            "(SMSMASIVOS_API_KEY o TWILIO_*). Nadie podría verificar su teléfono.")
        return problems

    def _db_password(self) -> str | None:
        try:
            from sqlalchemy.engine import make_url

            return make_url(self.database_url).password
        except Exception:  # noqa: BLE001
            return None

    # --- Propiedades derivadas ---
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def demo_enabled(self) -> bool:
        if self.is_production:
            return False
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
        raw = self.cors_origins
        if not raw and not self.is_production:
            raw = DEV_CORS_ORIGINS
        return [o.strip() for o in (raw or "").split(",") if o.strip()]

    @property
    def effective_cors_origin_regex(self) -> str | None:
        if self.cors_origin_regex:
            return self.cors_origin_regex
        return None if self.is_production else DEV_CORS_ORIGIN_REGEX

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_api_key)

    @property
    def payments_enabled(self) -> bool:
        return bool(self.mercadopago_access_token)

    @property
    def sms_effective_provider(self) -> str | None:
        """Proveedor que realmente se usará. En development, si el elegido no tiene llaves, cae a "dev"."""
        configured = {
            "smsmasivos": bool(self.smsmasivos_api_key),
            "twilio": bool(self.twilio_account_sid and self.twilio_auth_token
                           and (self.twilio_from_number or self.twilio_messaging_service_sid)),
            "dev": self.is_development,
        }
        if configured.get(self.sms_provider):
            return self.sms_provider
        if self.is_development:
            return "dev"
        return None

    @property
    def otp_enabled(self) -> bool:
        return self.sms_effective_provider is not None

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
