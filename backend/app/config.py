from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-secret-key-change-in-production"
MIN_SECRET_KEY_LENGTH = 32
JWT_ALGORITHMS = ("HS256", "HS384", "HS512")  # SECRET_KEY es una clave simétrica
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
DEV_POSTGRES_PASSWORD = "patitasfind"
DEV_WHATSAPP_VERIFY_TOKEN = "patitasfind-dev-token"
DEV_CORS_ORIGINS = (
    "http://localhost:8080,http://localhost:8081,http://localhost:8082,"
    "http://localhost:3000,http://127.0.0.1:5500,http://127.0.0.1:8082"
)
DEV_CORS_ORIGIN_REGEX = r"https://.*\.trycloudflare\.com"
DEMO_EMAIL = "demo@patitasfind.example.com"
SMS_PROVIDERS = ("smsmasivos", "twilio", "zernio", "dev")
AI_PROVIDERS = ("openai_compatible",)
PAC_PROVIDERS = ("", "facturama")


def _is_public_https(url: str) -> bool:
    """True si la URL usa https:// y un host público (no localhost ni 127.0.0.1)."""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(host) and host not in LOCAL_HOSTS and not host.endswith(".localhost")


def _is_aes256_key(value: str) -> bool:
    """True si es el base64 (estándar o url-safe) de exactamente 32 bytes (PRIVATE_FILES_KEY)."""
    import base64
    import binascii

    raw = value.strip()
    try:
        key = base64.b64decode((raw + "=" * (-len(raw) % 4)).replace("-", "+").replace("_", "/"), validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(key) == 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # --- Núcleo ---
    environment: str = "development"
    database_url: str = "postgresql+psycopg2://patitasfind:patitasfind@localhost:5432/patitasfind"
    postgres_password: str | None = None  # solo para validar en producción (lo usa el contenedor de Postgres)
    # Pool de conexiones por proceso (ver la cuenta en app/database.py)
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 10  # segundos esperando una conexión libre antes de fallar
    db_worker_pool_size: int = 2  # procesos de Celery (cada hijo del worker tiene su propio pool)
    db_worker_max_overflow: int = 2
    secret_key: str = DEV_SECRET_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 días
    admin_token_expire_minutes: int = 480  # 8 horas para admin y superadmin
    public_base_url: str | None = None  # p. ej. https://guauwoow.com (sin "/" final)
    allow_demo_login: bool | None = None  # None => True solo en development (nunca en production)

    # --- Tienda y soporte ---
    shop_enabled: bool | None = None  # None => True en development, False en production
    support_email: str | None = None
    support_whatsapp: str | None = None  # p. ej. +525512345678
    # Identidad del operador en el comprobante de compra (LFPC art. 76 Bis fr. III; consumidor-ecommerce-02 y 07):
    # razón social y RFC salen de EMISOR_NOMBRE y EMISOR_RFC; estos deben coincidir con DOMICILIO FISCAL y
    # TELÉFONO de datos-legales.json
    operator_address: str | None = None
    operator_phone: str | None = None

    # --- CORS ---
    # Vacío => en development se usan los orígenes locales; en production es obligatorio.
    cors_origins: str | None = None
    # Vacío => en development se permiten túneles *.trycloudflare.com; en production ninguno.
    cors_origin_regex: str | None = None

    # --- Archivos ---
    upload_dir: str = "uploads"
    max_upload_mb: int = 10
    upload_daily_quota: int = 60  # fotos por usuario al día (429 al rebasarlo; admins exentos)
    # Hosts de los que el servidor puede descargar medios (WhatsApp/Facebook); "*." incluye subdominios
    remote_media_hosts: str = "graph.facebook.com,lookaside.fbsbx.com,*.fbcdn.net,*.fbsbx.com"

    # --- Google OAuth ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Opcional: si se omite se usa {PUBLIC_BASE_URL}/auth/google/callback
    google_redirect_uri: str | None = None

    # --- Redis / Celery ---
    redis_url: str | None = None
    cache_ttl_seconds: int = 300
    list_cache_ttl_seconds: int = 60  # listados públicos sin sesión (/dogs/featured, /lost-reports)
    matches_cache_ttl_seconds: int = 600  # /lost-reports/{id}/matches
    report_matches_ip_minute_limit: int = 30  # /lost-reports/{id}/matches por IP y minuto
    report_expiry_days: int = 90  # reportes activos sin cambios en este plazo pasan a "expired"
    use_celery: bool | None = None  # None => True si hay REDIS_URL

    # --- IA de visión (API compatible con OpenAI Chat Completions) ---
    ai_provider: str = "openai_compatible"
    ai_api_key: str | None = None
    ai_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    ai_model: str = "qwen3-vl-flash"
    ai_timeout_seconds: float = 20.0
    ai_extra_body: str | None = None  # JSON opcional que se agrega al cuerpo, p. ej. {"enable_thinking": false}
    match_score_threshold: int = 60
    ai_max_concurrency: int = 4  # llamadas simultáneas a la IA por proceso (las demás esperan)
    ai_user_hourly_limit: int = 20  # /ai/analyze-photo por usuario y hora
    search_user_hourly_limit: int = 30  # /search/by-photo con sesión, por usuario y hora
    search_anon_minute_limit: int = 5  # /search/by-photo sin sesión, por IP y minuto
    search_anon_daily_limit: int | None = None  # sin sesión, por IP y día; None => 30 (sin tope diario en development)

    # --- Mercado Pago ---
    mercadopago_access_token: str | None = None
    mercadopago_webhook_secret: str | None = None
    currency: str = "MXN"
    # Minutos que se aparta el inventario y dura el link de pago; después el pedido pendiente expira
    checkout_expiration_minutes: int = 60
    # --- Mercado Pago Marketplace (split 1:1): cada refugio cobra con SU cuenta, vinculada por OAuth ---
    mercadopago_app_id: str | None = None  # client_id de la aplicación Marketplace ("Tus integraciones")
    mercadopago_client_secret: str | None = None  # client_secret de esa aplicación (intercambio de códigos OAuth)
    # Comisión de GuauWoow por venta (% del total, IVA incluido); MP la separa sola con marketplace_fee.
    # 0 = premisa de la plataforma (tarifas.html). Mayor a 0 en producción exige PLATFORM_TAX_REGIME_READY=true.
    mercadopago_marketplace_fee_percent: float = 0.0
    mercadopago_donation_fee_percent: float = 0.0  # comisión sobre donativos (la investigación recomienda 0)
    # Donativos a refugios sin Mercado Pago vinculado: true = se cobran con la cuenta de la plataforma (flujo
    # anterior). Vacío => true solo en development; en producción solo si se define explícitamente.
    donations_fallback_to_platform_account: bool | None = None
    # true solo cuando el contador confirme el régimen de plataformas (fiscal-tienda-07; VERIFICAR_REGIMEN_PLATAFORMAS):
    # sin esto, en producción no se puede cobrar comisión (tienda ni donativos) y no se retienen ISR ni IVA
    platform_tax_regime_ready: bool = False

    # --- Donativos: topes y prevención de lavado (donativos-11; prevencion-lavado.html) ---
    # Topes muy por debajo del umbral de identificación de la LFPIORPI (1,605 UMA). Deben coincidir con
    # TOPE_POR_DONATIVO y TOPE_DIARIO_DE_DONATIVOS de datos-legales.json
    donation_max_mxn: float = 50000.0  # monto máximo de un solo donativo
    donation_daily_max_mxn: float = 50000.0  # lo máximo que una misma cuenta puede donar en un día (hora de CDMX)
    uma_daily_mxn: float = 117.31  # UMA diaria vigente (2026: 1-feb-2026 a 31-ene-2027); actualízala cada febrero
    donation_identification_uma: int = 1605  # LFPIORPI art. 17 fr. XIII: identificar a quien dona (acumulado 6 meses)
    donation_notice_uma: int = 3210  # LFPIORPI art. 17 fr. XIII: aviso a la autoridad (acumulado 6 meses)

    # --- Adopción responsable ---
    # Días naturales que un perro encontrado debe esperar (con el reporte activo, microchip revisado y aviso a la
    # autoridad) antes de publicarse en adopción. Debe coincidir con PLAZO_DE_RESGUARDO_DE_PERROS_ENCONTRADOS
    found_dog_hold_days: int = 30

    # --- Tienda: devoluciones y cierre de pedidos ---
    # Revocación de compras a distancia: 5 días hábiles desde la entrega (LFPC art. 56; consumidor-ecommerce-09)
    return_window_days: int = 5
    # Reclamación por producto defectuoso, que no corresponde o que no llegó: 2 meses (LFPC art. 93)
    return_claim_window_days: int = 60
    order_auto_complete_days: int = 10  # entregado sin devolución en este plazo => "completed"
    # Días hábiles de gracia después del plazo de despacho del refugio (handling_days): al vencer el plazo se
    # avisa al refugio y al comprador; al vencer la gracia el pedido se cancela y reembolsa solo
    # (consumidor-ecommerce-13: cancelación y reembolso automáticos al vencer la fecha máxima)
    order_dispatch_grace_days: int = 2

    # --- Facturación (CFDI 4.0 por PAC) y retenciones de plataformas ---
    # Retenciones a refugios vendedores (fiscal-tienda-09): ISR sobre el ingreso sin IVA (LIF 2026 art. 25 fr. VI;
    # LISR 113-A) e IVA como porcentaje del IVA cobrado (LIVA 18-J fr. II a). Tasas 2026 con RFC: 2.5 % y 50 %.
    # Sin RFC serían 20 % de ISR (LISR 113-C fr. IV) y 100 % de IVA (LIVA 18-J fr. II a); no se configuran porque
    # en producción no se vende sin RFC (mercadopago_oauth.refuge_payments_ready). Las tasas cambian cada
    # ejercicio (reforma 2027 pendiente): revísalas con el contador cada diciembre.
    retencion_isr_percent: float = 2.5
    retencion_iva_percent: float = 50.0
    # LIF 2026 art. 25 fr. VI y IX a) extiende las mismas retenciones a personas morales (fiscal-tienda.md);
    # false solo si el contador confirma que no aplican (p. ej. la regla 12.2.5 de la RMF)
    retencion_personas_morales: bool = True
    pac_provider: str = ""  # "" (sin PAC: los CFDI quedan "pending_pac") | facturama
    pac_user: str | None = None
    pac_password: str | None = None
    pac_sandbox: bool = True  # true = apisandbox.facturama.mx (sin validez fiscal)
    emisor_rfc: str | None = None  # RFC de la persona moral que opera GuauWoow
    emisor_nombre: str | None = None  # razón social exacta como aparece en la Constancia del SAT
    emisor_regimen: str | None = None  # clave c_RegimenFiscal, p. ej. 601
    emisor_cp: str | None = None  # código postal del domicilio fiscal (lugar de expedición)
    cfdi_serie: str = "PF"

    # --- Verificación de teléfono (OTP propio + proveedor de SMS) ---
    sms_provider: str = "smsmasivos"  # smsmasivos | twilio | zernio | dev
    require_phone_verification: bool = True
    smsmasivos_api_key: str | None = None
    smsmasivos_sandbox: bool = False
    smsmasivos_url: str = "https://api.smsmasivos.com.mx/sms/send"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None  # +1..., o usa TWILIO_MESSAGING_SERVICE_SID
    twilio_messaging_service_sid: str | None = None
    zernio_api_key: str | None = None
    zernio_from: str | None = None  # Número E.164 (+1..., +52...) o Sender ID alfanumérico (p. ej. GUAUWOOW)
    zernio_sms_url: str = "https://zernio.com/api/v1/sms/messages"
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_sends_per_phone_hour: int = 5
    otp_max_sends_per_ip_hour: int = 10
    default_phone_country_code: str = "52"

    # --- Legal ---
    # Deben coincidir con la versión impresa en app/legal/plantillas/*.html (scripts/render-legal.py)
    legal_terms_version: str = "2026-10-17"
    legal_privacy_version: str = "2026-10-17"
    # Registro de versiones (K-DOCS) que lee "python -m app.cli sync-legal-docs" y el arranque. Vacío => se busca
    # app/data/versiones-legales.json (copia dentro de la imagen) y luego ../app/legal/versiones.json
    legal_versions_file: str | None = None
    # Anexos de aliados (refugios, vendedores, clínicas, casas de paso): exigir la casilla al registrarse o al
    # publicar el primer producto. Vacío => obligatorio solo en production (en development se registra si se marca)
    legal_annex_required: bool | None = None
    # Días mínimos de aviso previo de un cambio importante (historial.html §2): el sync avisa si es menor
    legal_notice_days: int = 30

    # --- Seguridad: verificación en dos pasos, cifrado en reposo y conservación de datos ---
    # Verificación en dos pasos (TOTP) para admin y superadmin. Vacío => obligatoria en todo entorno salvo
    # development (ahí es opcional: quien la active la tendrá que usar)
    mfa_required_for_admins: bool | None = None
    mfa_issuer: str = "GuauWoow"  # nombre que muestra la app de autenticación
    # Llave AES-256 (base64 de 32 bytes) con la que se cifran {UPLOAD_DIR}/private/* y los datos fiscales.
    # Obligatoria en producción; genera una con:
    # python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
    private_files_key: str | None = None
    # Llaves anteriores (separadas por comas) que solo se usan para descifrar al rotar PRIVATE_FILES_KEY
    private_files_old_keys: str | None = None
    # Purga diaria según la tabla de conservación (services/retention.py); false la pausa (p. ej. durante una
    # verificación de la autoridad). Un incidente abierto con "congelar purgas" también la pausa.
    retention_purge_enabled: bool = True

    # --- Observabilidad (todo opcional) ---
    sentry_dsn: str | None = None
    sentry_environment: str | None = None  # por defecto = ENVIRONMENT
    git_sha: str | None = None  # commit desplegado; Sentry lo usa como release (patitasfind@<sha>)
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
    # Plantillas aprobadas por Meta (fuera de la ventana de 24 h solo se permiten plantillas). Vacío = canal apagado.
    whatsapp_template_match: str | None = None
    whatsapp_template_nearby: str | None = None
    whatsapp_template_language: str = "es_MX"

    # --- Alertas de perritos perdidos/encontrados cerca ---
    nearby_alert_radius_km: float = 5.0
    nearby_alert_partner_radius_km: float = 15.0  # refugios y casas de paso aprobados
    nearby_alert_max_recipients: int = 200
    nearby_alert_daily_cap: int = 5  # máximo de alertas por usuario al día

    # --- Facebook Pages ---
    facebook_page_access_token: str | None = None
    facebook_groups: str | None = None  # obsoleto, se conserva por compatibilidad

    # --- Grupos públicos de Facebook (lectura por proveedor externo: Apify) ---
    # Interruptor de la importación automática (grupos y Páginas). Apagado por defecto: el contenido importado
    # solo se activa con la decisión del dueño. En producción también exige FB_GROUPS_LEGAL_OPINION_REF.
    fb_groups_enabled: bool = False
    # Referencia de la opinión legal escrita que autoriza la importación (p. ej. "Opinión Desp. X, 2026-11-02")
    fb_groups_legal_opinion_ref: str | None = None
    apify_token: str | None = None  # vacío = proveedor no configurado: las tareas avisan una vez y no hacen nada
    apify_fb_groups_actor: str = "apify/facebook-groups-scraper"  # actor de Apify ("usuario/nombre")
    fb_groups_fetch_interval_hours: int = 12  # un grupo no se vuelve a leer antes de este plazo
    fb_groups_lookback_days: int = 14  # en la primera lectura (o tras pausas) se piden publicaciones de estos días
    fb_groups_max_posts_per_run: int = 100  # tope de publicaciones por grupo y corrida (controla el costo)
    fb_groups_daily_budget_usd: float = 2.0  # gasto máximo estimado por día (UTC) en el proveedor; al rebasarlo se detiene
    # Precio estimado del proveedor por cada 1000 publicaciones (Apify, plan gratuito, oct. 2026: ~0.005 USD por
    # publicación + 0.002 por el filtro de fecha, que siempre se usa = ~7 USD por 1000)
    fb_groups_cost_per_1000_posts_usd: float = 7.0
    fb_groups_cost_per_run_usd: float = 0.005  # cargo fijo estimado por arranque de cada corrida del actor
    fb_groups_post_ttl_days: int = 30  # los reportes importados de grupos expiran a estos días (desde la publicación)
    fb_volunteer_post_ttl_days: int = 30  # lo mismo para los envíos de voluntarios (fuente "volunteer")
    # Días después de caducar en que se borran texto y fotos del reporte importado (0 = el mismo día)
    fb_imported_purge_after_days: int = 0

    # --- Veterinarias y Google Places (New) ---
    # Llave de servidor de Google Maps Platform con "Places API (New)" habilitada. Vacía => el bloque
    # "Reseñas de Google" es null y la búsqueda de lugares responde 503 con un mensaje claro.
    google_maps_api_key: str | None = None
    # Tope diario de consultas de detalle con reseñas (SKU Enterprise + Atmosphere, de pago); al rebasarlo el
    # perfil se muestra sin el bloque de Google hasta el día siguiente. Las reseñas NUNCA se guardan en caché.
    google_places_daily_limit: int = 200
    # Antigüedad mínima de la cuenta (días) para reseñar una clínica; 0 = sin mínimo (la política de reseñas
    # propone 7: decisión del dueño)
    veterinary_review_min_account_days: int = 0

    # --- Moderación legal: reportes públicos, evidencia, derechos de autor y autoridades ---
    # (moderacion.html, proteccion-nna.html, derechos-de-autor.html, autoridades.html). Los plazos deben coincidir
    # con las claves PLAZO_* de datos-legales.json.
    # Contacto 24/7 para autoridades (Decreto NNA art. 5 fr. I; CONTACTO_24_7_PARA_AUTORIDADES): correo y teléfono
    authority_contact_email: str | None = None
    authority_contact_phone: str | None = None
    # Primera respuesta a autoridades: minutos si hay menores o riesgo para la vida; horas en los demás casos
    authority_first_response_urgent_minutes: int = 60
    authority_first_response_hours: int = 24
    # Plazos objetivo de revisión: urgentes (horas), reportes sobre menores (horas, respuesta a madres, padres y
    # tutores) y el resto (días hábiles: 72 horas hábiles = 3)
    moderation_urgent_hours: int = 24
    moderation_minor_response_hours: int = 72
    moderation_review_business_days: int = 3
    # Apelaciones: días naturales para apelar desde el aviso y días hábiles para resolver
    appeal_window_days: int = 15
    appeal_resolution_business_days: int = 10
    # Derechos de autor: plazo objetivo de retiro (días hábiles) y política de reincidentes (derechos-de-autor.html §8)
    copyright_removal_business_days: int = 1
    copyright_strikes_suspend: int = 2  # avisos procedentes en 12 meses que suspenden la cuenta
    copyright_strikes_cancel: int = 3  # avisos procedentes que cancelan la cuenta
    copyright_suspension_days: int = 30
    # Bóveda de evidencia: días hábiles mínimos de conservación (Decreto NNA art. 5 fr. II) y carpeta cifrada
    # (vacía = <UPLOAD_DIR>/private/evidencia, que nunca se sirve)
    evidence_retention_business_days: int = 90
    evidence_dir: str | None = None
    # Formularios públicos sin cuenta (reportes, avisos y contra-avisos, apelaciones): máximo por IP y hora
    public_reports_hourly_limit: int = 5

    # --- Centro de solicitudes (/cumplimiento/solicitudes) e informe de transparencia ---
    # Quejas y aclaraciones: primera respuesta y respuesta final en días hábiles. Deben coincidir con
    # PLAZO_DE_PRIMERA_RESPUESTA y PLAZO_DE_RESPUESTA_A_QUEJAS de datos-legales.json (atencion-y-quejas.html).
    # Los plazos ARCO (20 y 15 días hábiles) los fija la LFPDPPP (art. 31) y no se configuran.
    complaint_first_response_business_days: int = 2
    complaint_response_business_days: int = 10
    # Horas después de pedir el retiro de una publicación importada en que se borran su texto y fotos si el
    # equipo no lo descartó (contenido-importado.html promete menos de 72 h; se oculta desde el primer momento)
    imported_removal_purge_hours: int = 48
    # Regla de umbral del informe de transparencia: los desgloses con menos casos no se publican
    transparency_min_cases: int = 5

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
        self.pac_provider = (self.pac_provider or "").strip().lower()
        if self.pac_provider not in PAC_PROVIDERS:
            raise ValueError(f"PAC_PROVIDER debe estar vacío o ser facturama (recibido: {self.pac_provider!r}).")
        for name, raw in (("PRIVATE_FILES_KEY", self.private_files_key),
                          *(("PRIVATE_FILES_OLD_KEYS", k) for k in (self.private_files_old_keys or "").split(","))):
            if raw and raw.strip() and not _is_aes256_key(raw):
                raise ValueError(f"{name} no es válida: usa el base64 de 32 bytes aleatorios "
                                 "(python3 -c \"import base64, os; print(base64.b64encode(os.urandom(32)).decode())\").")
        if self.is_production:
            problems = self.production_problems()
            if problems:
                raise ValueError(
                    f"Configuración incompleta o insegura para ENVIRONMENT=production ({len(problems)} problema(s)); "
                    "el backend no arrancará hasta que los corrijas en .env:\n  - "
                    + "\n  - ".join(problems)
                )
        return self

    def production_problems(self) -> list[str]:
        """Lista TODOS los problemas de configuración de producción (vacía = todo bien)."""
        problems = []
        # Secretos
        if self.secret_key == DEV_SECRET_KEY:
            problems.append("SECRET_KEY usa el valor de desarrollo. Define una clave larga y aleatoria.")
        elif len(self.secret_key or "") < MIN_SECRET_KEY_LENGTH:
            problems.append(f"SECRET_KEY es muy corta ({len(self.secret_key or '')} caracteres; mínimo {MIN_SECRET_KEY_LENGTH}). "
                            "Genera una con: python3 -c \"import secrets; print(secrets.token_urlsafe(64))\"")
        if self.algorithm not in JWT_ALGORITHMS:
            problems.append(f"ALGORITHM={self.algorithm} no es válido; usa {', '.join(JWT_ALGORITHMS)} (por defecto HS256).")
        # URL pública (enlaces de correo, back_urls de Mercado Pago, Google OAuth, bot de WhatsApp)
        if not self.public_base_url:
            problems.append("PUBLIC_BASE_URL está vacío. Define la URL pública, p. ej. PUBLIC_BASE_URL=https://guauwoow.com "
                            "(docker-compose.production.yml la toma de https://$DOMAIN si la dejas vacía en .env).")
        elif not _is_public_https(self.public_base_url):
            problems.append(f"PUBLIC_BASE_URL={self.public_base_url} debe usar https:// y un dominio público (no localhost ni 127.0.0.1).")
        # CORS
        origins = self.cors_origin_list
        if not origins:
            problems.append("CORS_ORIGINS está vacío. Define tu dominio, p. ej. CORS_ORIGINS=https://guauwoow.com")
        elif "*" in origins:
            problems.append("CORS_ORIGINS no puede ser \"*\" en producción. Lista solo tus dominios https://.")
        else:
            bad = [o for o in origins if not _is_public_https(o)]
            if bad:
                problems.append("CORS_ORIGINS solo admite orígenes https:// públicos (sin http:// ni localhost); quita: "
                                + ", ".join(bad))
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
            problems.append("SMS_PROVIDER=dev no envía SMS reales. Usa smsmasivos, twilio o zernio en producción.")
        elif self.require_phone_verification and self.sms_effective_provider is None:
            problems.append(f"REQUIRE_PHONE_VERIFICATION=true pero SMS_PROVIDER={self.sms_provider} no tiene llaves "
                            "(SMSMASIVOS_API_KEY, TWILIO_* o ZERNIO_API_KEY/ZERNIO_FROM). Nadie podría verificar su teléfono.")
        # Correo: restablecer contraseña y verificación de correo dependen de SMTP
        missing_smtp = [name for name, value in (("SMTP_HOST", self.smtp_host), ("SMTP_FROM", self.smtp_from)) if not value]
        if missing_smtp:
            problems.append(f"Falta {' y '.join(missing_smtp)}: sin correo no funcionan \"Olvidé mi contraseña\" "
                            "ni la verificación de correo.")
        # Pagos
        if self.mercadopago_access_token and not self.mercadopago_webhook_secret:
            problems.append("MERCADOPAGO_ACCESS_TOKEN está definido pero falta MERCADOPAGO_WEBHOOK_SECRET "
                            "(valida la firma x-signature de los avisos de pago).")
        if self.effective_shop_enabled and not self.payments_enabled:
            problems.append("La tienda está activa (SHOP_ENABLED=true) pero Mercado Pago no está configurado "
                            "(MERCADOPAGO_ACCESS_TOKEN). Configura los pagos o deja SHOP_ENABLED vacío o en false.")
        elif self.effective_shop_enabled and not self.marketplace_enabled:
            problems.append("La tienda está activa pero faltan MERCADOPAGO_APP_ID y MERCADOPAGO_CLIENT_SECRET: los "
                            "refugios no podrían vincular su cuenta de Mercado Pago (split) y nadie podría comprar.")
        if self.pac_provider and not all((self.pac_user, self.pac_password, self.emisor_rfc, self.emisor_nombre,
                                          self.emisor_regimen, self.emisor_cp)):
            problems.append(f"PAC_PROVIDER={self.pac_provider} necesita PAC_USER, PAC_PASSWORD, EMISOR_RFC, "
                            "EMISOR_NOMBRE, EMISOR_REGIMEN y EMISOR_CP.")
        # Cobrar comisión activa el régimen de plataformas de intermediación (fiscal-tienda-07; gap-custodia-01):
        # CFDI de comisión y de retenciones cada mes. Sin PAC ni datos del emisor no se puede cumplir.
        charges_fee = ((self.effective_shop_enabled and self.mercadopago_marketplace_fee_percent > 0)
                       or (self.payments_enabled and self.mercadopago_donation_fee_percent > 0))
        if charges_fee and not self.invoicing_ready:
            problems.append("Hay comisión de GuauWoow mayor a 0 (MERCADOPAGO_MARKETPLACE_FEE_PERCENT o "
                            "MERCADOPAGO_DONATION_FEE_PERCENT) pero la facturación no está lista (PAC_PROVIDER, PAC_USER, "
                            "PAC_PASSWORD, EMISOR_RFC, EMISOR_NOMBRE, EMISOR_REGIMEN y EMISOR_CP). Pon la comisión en 0 "
                            "hasta tener el régimen de plataformas en orden o configura el PAC.")
        # Reglas de negocio (services/reglas.py)
        if (self.mercadopago_marketplace_fee_percent > 0 or self.mercadopago_donation_fee_percent > 0) \
                and not self.platform_tax_regime_ready:
            problems.append("MERCADOPAGO_MARKETPLACE_FEE_PERCENT o MERCADOPAGO_DONATION_FEE_PERCENT es mayor a 0 pero "
                            "PLATFORM_TAX_REGIME_READY no es true: cobrar comisión activa el régimen de plataformas "
                            "(CFDI de comisión, retenciones e informativas). Déjala en 0 hasta que el contador lo confirme.")
        if self.fb_groups_enabled and not (self.fb_groups_legal_opinion_ref or "").strip():
            problems.append("FB_GROUPS_ENABLED=true necesita FB_GROUPS_LEGAL_OPINION_REF (la referencia de la opinión "
                            "legal escrita que autoriza importar publicaciones públicas de Facebook).")
        identification = self.donation_identification_uma * self.uma_daily_mxn
        if self.donation_max_mxn <= 0 or self.donation_daily_max_mxn <= 0:
            problems.append("DONATION_MAX_MXN y DONATION_DAILY_MAX_MXN deben ser mayores a 0.")
        elif max(self.donation_max_mxn, self.donation_daily_max_mxn) >= identification:
            problems.append(f"Los topes de donativos (DONATION_MAX_MXN, DONATION_DAILY_MAX_MXN) deben quedar muy por "
                            f"debajo del umbral de identificación de la LFPIORPI ({identification:,.2f} MXN).")
        if self.found_dog_hold_days < 1:
            problems.append("FOUND_DOG_HOLD_DAYS debe ser de al menos 1 día (perdidos-y-encontrados, sección 6).")
        # Seguridad (contrato L-seguridad): documentos privados cifrados y MFA obligatoria para admins
        if not self.private_files_key:
            problems.append("Falta PRIVATE_FILES_KEY: los documentos privados (INE, actas, cédulas, constancias "
                            "fiscales) y los datos fiscales se guardarían sin cifrar. Genera una con: python3 -c "
                            "\"import base64, os; print(base64.b64encode(os.urandom(32)).decode())\" y guárdala "
                            "también fuera del servidor (sin ella no se pueden leer los respaldos).")
        if self.mfa_required_for_admins is False:
            problems.append("MFA_REQUIRED_FOR_ADMINS=false: en producción la verificación en dos pasos del personal "
                            "administrador es obligatoria (lo promete la página de Seguridad). Déjala vacía o en true.")
        # Páginas legales (veracidad): lo que prometen depende de esta configuración
        if self.donations_fallback_to_platform_account is True:
            problems.append("DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT=true cobraría donativos con la cuenta de la plataforma, "
                            "pero las páginas legales (donativos, tarifas, transparencia-fondos) dicen que GuauWoow no "
                            "recibe ni guarda ese dinero. Déjala vacía o en false.")
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
    def effective_shop_enabled(self) -> bool:
        if self.shop_enabled is None:
            return not self.is_production
        return self.shop_enabled

    @property
    def effective_legal_annex_required(self) -> bool:
        if self.legal_annex_required is None:
            return self.is_production
        return self.legal_annex_required

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
    def marketplace_enabled(self) -> bool:
        """True si los refugios pueden vincular su cuenta de Mercado Pago por OAuth (split 1:1)."""
        return bool(self.mercadopago_app_id and self.mercadopago_client_secret)

    @property
    def payments_simulated(self) -> bool:
        """Desarrollo sin Mercado Pago: compras y donativos se aprueban solos (nunca en producción)."""
        return not self.payments_enabled and self.is_development

    @property
    def effective_donations_fallback(self) -> bool:
        if self.donations_fallback_to_platform_account is None:
            return self.is_development
        return self.donations_fallback_to_platform_account

    @property
    def pac_enabled(self) -> bool:
        return bool(self.pac_provider and self.pac_user and self.pac_password and self.emisor_rfc)

    @property
    def invoicing_ready(self) -> bool:
        """PAC y datos completos del emisor: se pueden timbrar los CFDI de comisión y de retenciones."""
        return bool(self.pac_enabled and self.emisor_nombre and self.emisor_regimen and self.emisor_cp)

    @property
    def sms_effective_provider(self) -> str | None:
        """Proveedor que realmente se usará. En development, si el elegido no tiene llaves, cae a "dev"."""
        configured = {
            "smsmasivos": bool(self.smsmasivos_api_key),
            "twilio": bool(self.twilio_account_sid and self.twilio_auth_token
                           and (self.twilio_from_number or self.twilio_messaging_service_sid)),
            "zernio": bool(self.zernio_api_key and self.zernio_from),
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

    @property
    def fb_groups_provider_configured(self) -> bool:
        """True si hay proveedor para leer grupos públicos de Facebook (APIFY_TOKEN)."""
        return bool(self.apify_token)

    @property
    def fb_groups_active(self) -> bool:
        """True si la importación automática está encendida (FB_GROUPS_ENABLED) y hay proveedor (APIFY_TOKEN)."""
        return bool(self.fb_groups_enabled and self.apify_token)

    @property
    def fees_allowed(self) -> bool:
        """Se puede cobrar comisión (y retener impuestos de plataformas): siempre fuera de producción; en
        producción solo con PLATFORM_TAX_REGIME_READY=true (la validación de arranque ya lo exige)."""
        return self.platform_tax_regime_ready or not self.is_production

    @property
    def google_places_enabled(self) -> bool:
        return bool(self.google_maps_api_key)

    def public_url(self, path: str = "") -> str:
        base = self.public_base_url or "http://localhost:8082"
        return f"{base}{path}"


settings = Settings()
