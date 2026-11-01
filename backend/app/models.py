import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, Text, Float, Numeric, ForeignKey, JSON, UniqueConstraint, Index,
    text,
)
from sqlalchemy.orm import relationship

from app.config import DEMO_EMAIL, settings
from app.database import Base
from app.services.crypto_storage import EncryptedText


def _now():
    return datetime.datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Un teléfono verificado solo puede pertenecer a una cuenta activa
        Index("uq_users_verified_phone", "phone", unique=True,
              postgresql_where=text("phone_verified AND is_active AND phone IS NOT NULL")),
        # Alertas de perritos cercanos: solo cuentas activas, con ubicación y avisos encendidos
        Index("ix_users_nearby_geo", "latitude", "longitude",
              postgresql_where=text("notify_nearby AND is_active AND latitude IS NOT NULL")),
        # Ya existía en STARTUP_MIGRATIONS (redundante con ix_users_email; se conserva el nombre)
        Index("idx_users_email", "email"),
    )

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    phone_verified = Column(Boolean, default=False, nullable=False)
    phone_otp_hash = Column(String(128), nullable=True)
    phone_otp_expires_at = Column(DateTime, nullable=True)
    phone_otp_attempts = Column(Integer, default=0, nullable=False)
    phone_otp_sent_at = Column(DateTime, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
    google_sub = Column(String(64), nullable=True, index=True)
    avatar_url = Column(String(500), nullable=True)
    role = Column(String(50), default="user", nullable=False)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    terms_accepted_at = Column(DateTime, nullable=True)
    terms_version = Column(String(20), nullable=True)
    privacy_version = Column(String(20), nullable=True)
    marketing_opt_in = Column(Boolean, default=False, nullable=False)  # "correos promocionales" (K-PREF email_marketing)
    # Avisos de perritos cerca: apagados hasta que la persona los activa (cada cambio queda en consent_records)
    notify_nearby = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    # Avisos por WhatsApp (plantillas de utilidad): solo con permiso expreso; BAJA/ALTA en el bot los cambian
    whatsapp_alerts = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    # --- Edad (L-edad): fecha de nacimiento y casilla separada de 18+ al registrarse ---
    birth_date = Column(Date, nullable=True)
    adult_declared_at = Column(DateTime, nullable=True)
    # Verificación reforzada de edad: None | required (cuenta limitada) | passed | cleared (la liberó un admin)
    age_check_status = Column(String(20), nullable=True)
    suspended_at = Column(DateTime, nullable=True)  # suspendida por moderación (is_active = False)
    deleted_at = Column(DateTime, nullable=True)
    email_verified = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    email_verified_at = Column(DateTime, nullable=True)
    # Va en el claim "tv" del JWT: al incrementarlo se invalidan todas las sesiones anteriores
    token_version = Column(Integer, default=0, server_default=text("0"), nullable=False)
    # --- Verificación en dos pasos (admins; services/totp.py): secretos TOTP cifrados (crypto_storage) ---
    mfa_secret_enc = Column(EncryptedText, nullable=True)
    mfa_pending_secret_enc = Column(EncryptedText, nullable=True)  # alta en curso, hasta confirmar el primer código
    mfa_enabled_at = Column(DateTime, nullable=True)
    mfa_last_step = Column(Integer, nullable=True)  # último intervalo TOTP aceptado (un código no sirve dos veces)
    created_at = Column(DateTime, default=_now, nullable=False)

    dogs = relationship("Dog", back_populates="owner")
    matches = relationship("Match", back_populates="user")
    sent_messages = relationship("Message", back_populates="sender")
    notifications = relationship("Notification", back_populates="user")
    refuges = relationship("Refuge", back_populates="user")
    lost_reports = relationship("LostReport", back_populates="reporter")
    orders = relationship("Order", back_populates="user")
    foster_homes = relationship("FosterHome", back_populates="user")
    reminders = relationship("Reminder", back_populates="user")

    @property
    def has_password(self) -> bool:
        return bool(self.hashed_password)

    @property
    def is_phone_exempt(self) -> bool:
        """Admins (y el usuario demo fuera de producción) no necesitan verificar teléfono."""
        if self.role in ("admin", "superadmin"):
            return True
        return not settings.is_production and (self.email or "").lower() == DEMO_EMAIL

    @property
    def phone_verification_required(self) -> bool:
        """True si este usuario aún debe verificar su teléfono para acciones de escritura."""
        return bool(settings.require_phone_verification and not self.phone_verified and not self.is_phone_exempt)

    @property
    def age_check_required(self) -> bool:
        """Verificación reforzada de edad pendiente: la cuenta queda limitada (solo lectura) hasta completarla."""
        return self.age_check_status == "required" and self.role not in ("admin", "superadmin")

    @property
    def age_declaration_required(self) -> bool:
        """Cuenta creada con Google que aún no indicó su fecha de nacimiento ni la casilla de 18+."""
        if self.is_phone_exempt:
            return False
        return bool(self.google_sub and (self.birth_date is None or self.adult_declared_at is None))

    @property
    def email_marketing(self) -> bool:
        return bool(self.marketing_opt_in)

    @email_marketing.setter
    def email_marketing(self, value: bool) -> None:
        self.marketing_opt_in = bool(value)

    @property
    def age_declared(self) -> bool:
        """Ya indicó su fecha de nacimiento y marcó la casilla de 18+ (registro o al completar la cuenta)."""
        return self.birth_date is not None and self.adult_declared_at is not None


class Dog(Base):
    __tablename__ = "dogs"
    __table_args__ = (
        Index("idx_dogs_status", "status"),
        Index("idx_dogs_city", "city"),
        Index("idx_dogs_owner", "owner_id"),
        Index("idx_dogs_geo", "latitude", "longitude"),  # caja de búsqueda por distancia
        Index("idx_dogs_status_created", "status", "created_at"),  # listados por estado y fecha
    )

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    breed = Column(String(255), nullable=True)
    age_years = Column(Integer, nullable=True)
    age_months = Column(Integer, nullable=True)
    size = Column(String(50), nullable=True)
    color = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="available", nullable=False)
    photos = Column(JSON, default=list, nullable=False)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    ai_analysis = Column(JSON, nullable=True)
    photo_signature = Column(JSON, nullable=True)
    is_hidden = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # oculto por moderación
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
    # --- Reglas de negocio (services/reglas.py) ---
    # Retención automática para revisión humana (cobros, venta, rifas): motivo | "liberado" | "rechazado"
    review_hold = Column(String(40), nullable=True)
    review_terms = Column(JSON, nullable=True)  # palabras detectadas (las aprobadas al liberar no vuelven a retener)
    review_hold_at = Column(DateTime, nullable=True)
    # Perro encontrado (perdidos-y-encontrados §6): no se publica en adopción antes de FOUND_DOG_HOLD_DAYS
    # Un reporte de «encontrado» se liga a una sola ficha (índice único; los NULL no chocan)
    found_report_id = Column(Integer, ForeignKey("lost_reports.id"), nullable=True, index=True, unique=True)
    found_at = Column(DateTime, nullable=True)  # fecha en que se encontró (la del reporte si está ligado)
    microchip_checked_at = Column(DateTime, nullable=True)  # le leyeron el microchip en una clínica
    microchip_result = Column(String(30), nullable=True)  # sin_chip | chip_sin_registro | chip_tutor_contactado
    authority_notified_at = Column(DateTime, nullable=True)  # aviso a la autoridad local
    authority_notice = Column(String(255), nullable=True)  # a quién se avisó y folio de la constancia

    owner = relationship("User", back_populates="dogs")
    matches = relationship("Match", back_populates="dog")

    # Atributo transitorio (no persistido) que llenan los endpoints con geolocalización
    distance_km = None

    @property
    def review(self) -> dict | None:
        """Retención para revisión humana (solo la ven el dueño y los admins: DogPrivateOut)."""
        from app.services.reglas import review_info

        return review_info(self)

    @property
    def found_hold(self) -> dict | None:
        """Resguardo de un perro encontrado antes de poder ofrecerse en adopción (DogPrivateOut)."""
        from app.services.reglas import found_hold_info

        return found_hold_info(None, self)


class DogPass(Base):
    __tablename__ = "dog_passes"
    __table_args__ = (UniqueConstraint("user_id", "dog_id", name="uq_dog_passes_user_dog"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    dog_id = Column(Integer, ForeignKey("dogs.id"), nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        Index("idx_matches_status", "status"),
        Index("idx_matches_user", "user_id"),
        Index("idx_matches_dog", "dog_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    dog_id = Column(Integer, ForeignKey("dogs.id"), nullable=False)
    status = Column(String(50), default="pending_application", nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="matches")
    dog = relationship("Dog", back_populates="matches")
    application = relationship("AdoptionApplication", back_populates="match", uselist=False)
    conversation = relationship("Conversation", back_populates="match", uselist=False)

    @property
    def conversation_id(self):
        return self.conversation.id if self.conversation else None

    @property
    def has_application(self) -> bool:
        return self.application is not None

    @property
    def compatibility(self):
        from app.services.compatibility import compute_compatibility

        if not self.application:
            return None
        return compute_compatibility(self.application.answers or {}, self.dog)


class AdoptionApplication(Base):
    __tablename__ = "adoption_applications"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False, index=True)
    answers = Column(JSON, default=dict, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    match = relationship("Match", back_populates="application")

    @property
    def compatibility(self):
        from app.services.compatibility import compute_compatibility

        return compute_compatibility(self.answers or {}, self.match.dog if self.match else None)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("idx_conversations_users", "user_a_id", "user_b_id"),)

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True, index=True)
    lost_report_id = Column(Integer, ForeignKey("lost_reports.id"), nullable=True, index=True)
    user_a_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user_b_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    last_message_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    match = relationship("Match", back_populates="conversation")
    lost_report = relationship("LostReport")
    user_a = relationship("User", foreign_keys=[user_a_id])
    user_b = relationship("User", foreign_keys=[user_b_id])
    messages = relationship("Message", back_populates="conversation")

    def has_participant(self, user_id: int) -> bool:
        return user_id in (self.user_a_id, self.user_b_id)

    def other_user_id(self, user_id: int):
        return self.user_b_id if user_id == self.user_a_id else self.user_a_id


class Message(Base):
    __tablename__ = "messages"
    # Último mensaje y no leídos por conversación (resumen de /conversations)
    __table_args__ = (
        Index("idx_messages_conv", "conversation_id", "id"),
        Index("idx_messages_unread", "conversation_id", "sender_id", postgresql_where=text("NOT is_read")),
    )

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", back_populates="sent_messages")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_user_read", "user_id", "is_read"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    data = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="notifications")


class Refuge(Base):
    __tablename__ = "refuges"
    __table_args__ = (Index("idx_refuges_status", "status"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    status = Column(String(50), default="pending", nullable=False)
    documents = Column(JSON, default=list, nullable=False)
    rescued_count = Column(Integer, default=0, nullable=False)
    adopted_count = Column(Integer, default=0, nullable=False)
    foster_count = Column(Integer, default=0, nullable=False)
    points = Column(Integer, default=0, nullable=False)
    # Consintió publicar con su nombre sus cifras de donativos y ventas en el informe de transparencia
    # (donativos-22: los montos de Refugios que son personas físicas solo se muestran con su consentimiento)
    transparency_opt_in_at = Column(DateTime, nullable=True)
    # Conservación (R15/R17): las imágenes de verificación (INE, acta) se borran 30 días después de aprobar o
    # rechazar; queda la constancia (estado, bitácora refuge.approve/reject y documents_purged_at)
    verification_decided_at = Column(DateTime, nullable=True)
    documents_purged_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="refuges")
    point_logs = relationship("PointLog", back_populates="refuge")
    products = relationship("Product", back_populates="refuge")
    # Tienda: cuenta de Mercado Pago vinculada (split) y perfil fiscal del vendedor
    # lazy="selectin": los listados de refugios y productos calculan seller_payments_ready sin N+1
    payment_account = relationship("RefugePaymentAccount", back_populates="refuge", uselist=False, lazy="selectin")
    fiscal_profile = relationship("RefugeFiscalProfile", back_populates="refuge", uselist=False, lazy="selectin")

    @property
    def seller_payments_ready(self) -> bool:
        """True si hoy se le puede comprar (Mercado Pago vinculado o pagos simulados en desarrollo)."""
        from app.services.mercadopago_oauth import refuge_payments_ready

        return refuge_payments_ready(self)

    @property
    def donations_ready(self) -> bool:
        """True si hoy se le puede donar: Mercado Pago vinculado (sin exigir RFC: fiscal-tienda-19), pagos
        simulados en desarrollo o el respaldo con la cuenta de la plataforma (DONATIONS_FALLBACK_...)."""
        from app.services.mercadopago_oauth import refuge_donations_ready

        return refuge_donations_ready(self)

    @property
    def is_donataria(self) -> bool:
        """Donataria autorizada según sus datos fiscales (autodeclarado): define el aviso de deducibilidad."""
        return bool(self.fiscal_profile and self.fiscal_profile.is_donataria)


class PointLog(Base):
    __tablename__ = "point_logs"

    id = Column(Integer, primary_key=True, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False)
    action = Column(String(255), nullable=False)
    points = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    refuge = relationship("Refuge", back_populates="point_logs")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer, default=0, nullable=False)
    photos = Column(JSON, default=list, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_hidden = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # oculto por moderación
    created_at = Column(DateTime, default=_now, nullable=False)
    # --- Envío (consumidor-ecommerce-03 y 13): se cobra una sola vez por pedido (el mayor de sus productos) ---
    shipping_cost = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)  # 0 = envío gratis
    ships_nationwide = Column(Boolean, default=True, server_default=text("true"), nullable=False)
    ships_states = Column(JSON, nullable=True)  # estados que cubre cuando no envía a todo el país
    handling_days = Column(Integer, default=3, server_default=text("3"), nullable=False)  # días hábiles para despachar
    # --- Datos obligatorios (consumidor-ecommerce-04 y 12) y lista de productos prohibidos (services/reglas.py) ---
    category = Column(String(40), nullable=True)  # reglas.PRODUCT_CATEGORIES (NULL solo en productos anteriores)
    warranty_text = Column(Text, nullable=True)  # póliza: duración, alcance y cómo hacerla válida, o "Sin garantía adicional"
    warranty_days = Column(Integer, nullable=True)  # NULL = sin garantía adicional; si hay, 90 días o más (LFPC 77)
    is_perishable = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # sin revocación (LFPC 51)
    review_hold = Column(String(40), nullable=True)  # motivo | "liberado" | "rechazado"
    review_terms = Column(JSON, nullable=True)
    review_hold_at = Column(DateTime, nullable=True)

    refuge = relationship("Refuge", back_populates="products")

    @property
    def seller_payments_ready(self) -> bool:
        return bool(self.refuge and self.refuge.seller_payments_ready)

    @property
    def refuge_name(self) -> str | None:
        return self.refuge.name if self.refuge else None

    @property
    def platform_fee_percent(self) -> float:
        """Comisión de GuauWoow que se muestra en la ficha (consumidor-ecommerce-17: cuánto recibe el refugio)."""
        return float(settings.mercadopago_marketplace_fee_percent)

    @property
    def category_label(self) -> str | None:
        from app.services.reglas import PRODUCT_CATEGORIES

        return PRODUCT_CATEGORIES.get(self.category or "", (None,))[0]

    @property
    def review(self) -> dict | None:
        """Retención para revisión (lista de productos prohibidos); None si está publicado."""
        from app.services.reglas import review_info

        return review_info(self)


class LostReport(Base):
    __tablename__ = "lost_reports"
    __table_args__ = (
        Index("idx_lost_reports_status", "status"),
        Index("idx_lost_reports_geo", "latitude", "longitude"),  # caja de búsqueda por distancia
        # Una publicación de Facebook = un reporte (deduplicación por enlace, también con envíos simultáneos)
        Index("uq_lost_reports_external_url", "external_url", unique=True,
              postgresql_where=text("external_url IS NOT NULL")),
        Index("idx_lost_reports_status_created", "status", "created_at"),  # listados por estado y fecha
    )

    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    dog_name = Column(String(255), nullable=False)
    report_type = Column(String(50), default="lost", nullable=False)  # lost | found
    description = Column(Text, nullable=True)
    photos = Column(JSON, default=list, nullable=False)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True, index=True)  # estado de México (lo manda la app o se deduce de la ciudad)
    country = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    status = Column(String(50), default="active", nullable=False)
    source = Column(String(30), default="app", nullable=False)  # app | whatsapp | facebook | volunteer
    contact_phone = Column(String(50), nullable=True)  # solo visible para admins
    external_url = Column(String(500), nullable=True)  # permalink de Facebook
    # --- Contenido importado de Facebook (fuentes facebook | volunteer) ---
    external_posted_at = Column(DateTime, nullable=True)  # fecha de la publicación original (cuenta la caducidad)
    consent_at = Column(DateTime, nullable=True)  # el voluntario aceptó la leyenda de envío
    consent_version = Column(String(20), nullable=True)  # versión de los términos aceptada
    purged_at = Column(DateTime, nullable=True)  # se borraron texto y fotos al caducar o por retiro
    ai_analysis = Column(JSON, nullable=True)
    photo_signature = Column(JSON, nullable=True)
    is_hidden = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # oculto por moderación
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
    # Último cambio de cualquier origen (también firmas/IA en segundo plano y moderación); NULL en filas viejas
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=True)
    # Última acción de quien reporta (crear, renovar, resolver; reactivación por admin). Es el reloj de la
    # expiración: activo sin actividad en 90 días => "expired". NULL en filas viejas (se usa created_at).
    # No lleva onupdate a propósito: las escrituras en segundo plano no deben extender la vigencia.
    last_activity_at = Column(DateTime, default=_now, nullable=True)

    reporter = relationship("User", back_populates="lost_reports")

    distance_km = None

    @property
    def import_notice(self) -> str | None:
        """Etiqueta del contenido importado (contrato L-fb); None en los reportes propios de la app."""
        from app.services.reglas import import_notice

        return import_notice(self)


class BotInteraction(Base):
    __tablename__ = "bot_interactions"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(50), nullable=False, index=True)
    stage = Column(String(100), default="welcome", nullable=False)
    data = Column(JSON, default=dict, nullable=False)
    last_message = Column(Text, nullable=True)
    opted_out_at = Column(DateTime, nullable=True)  # escribió BAJA/STOP: no se le envían mensajes proactivos
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class FacebookGroup(Base):
    """Fuente de Facebook: una Página (Graph API), un grupo público (proveedor externo) o una fuente manual."""

    __tablename__ = "facebook_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    page_id = Column(String(100), nullable=True)
    kind = Column(String(20), default="manual", nullable=False)  # page | manual | group
    city = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_scraped = Column(DateTime, nullable=True)  # Páginas (Graph API)
    created_at = Column(DateTime, default=_now, nullable=False)
    # --- Grupos públicos (kind="group"): se leen con un proveedor externo (Apify) por zona ---
    state = Column(String(100), nullable=True, index=True)  # estado de México que cubre el grupo
    group_url = Column(String(500), nullable=True)  # https://www.facebook.com/groups/<id o alias>
    provider = Column(String(30), nullable=True)  # apify
    provider_ref = Column(String(255), nullable=True)  # id de la última corrida del proveedor
    last_fetched_at = Column(DateTime, nullable=True)  # última lectura correcta: desde aquí se pide la siguiente
    last_attempt_at = Column(DateTime, nullable=True)  # último intento (bien o con error): cuenta el intervalo
    last_post_at = Column(DateTime, nullable=True)  # fecha de la publicación más reciente leída
    posts_fetched_total = Column(Integer, default=0, server_default=text("0"), nullable=False)
    reports_created_total = Column(Integer, default=0, server_default=text("0"), nullable=False)
    cost_estimate_total = Column(Numeric(10, 4), default=0, server_default=text("0"), nullable=False)  # USD estimados
    last_error = Column(Text, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_status_created_at", "status", "created_at"),
        Index("ix_orders_refuge_paid_at", "refuge_id", "paid_at"),  # estados de cuenta mensuales por refugio
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=True, index=True)  # un pedido = un refugio vendedor
    total = Column(Numeric(10, 2), nullable=False)
    shipping_address = Column(Text, nullable=False)  # dirección unida en una línea (compatibilidad)
    # pending_payment -> paid -> preparing -> shipped -> delivered -> completed | cancelled |
    # return_requested -> return_approved -> refunded | return_rejected; además refund_pending, amount_mismatch
    # y expired (pedidos anteriores: hoy un pago vencido queda "cancelled")
    status = Column(String(50), default="created", nullable=False)
    # --- Importes (consumidor-ecommerce-03): total = subtotal + shipping_total ---
    subtotal = Column(Numeric(10, 2), nullable=True)
    shipping_total = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)
    fee_percent = Column(Numeric(5, 2), nullable=True)  # comisión de GuauWoow aplicada (%)
    fee_amount = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)  # comisión (IVA incluido)
    isr_retenido = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)
    iva_retenido = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)
    net_amount = Column(Numeric(10, 2), nullable=True)  # lo que llega al refugio (antes de la comisión de MP)
    # split = token del refugio + marketplace_fee | platform = cuenta de GuauWoow (anterior) | simulated
    payment_mode = Column(String(20), nullable=True)
    collector_id = Column(String(50), nullable=True)  # user_id de Mercado Pago del refugio que cobra
    # --- Dirección de envío estructurada ---
    shipping_name = Column(String(255), nullable=True)
    shipping_phone = Column(String(30), nullable=True)
    shipping_street = Column(String(255), nullable=True)
    shipping_ext_number = Column(String(30), nullable=True)
    shipping_int_number = Column(String(30), nullable=True)
    shipping_neighborhood = Column(String(255), nullable=True)
    shipping_city = Column(String(120), nullable=True)
    shipping_state = Column(String(100), nullable=True)
    shipping_postal_code = Column(String(10), nullable=True)
    shipping_references = Column(Text, nullable=True)
    tracking_url = Column(String(500), nullable=True)
    timeline = Column(JSON, nullable=True)  # [{status, at, note, by}] en orden cronológico
    preparing_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    # buyer | payment_expired | checkout_failed | dispatch_timeout | refuge | admin
    cancel_reason = Column(String(50), nullable=True)
    cancel_note = Column(Text, nullable=True)  # causa objetiva registrada al cancelar (refugio/admin; consumidor-ecommerce-14)
    dispatch_warned_at = Column(DateTime, nullable=True)  # aviso de despacho vencido (consumidor-ecommerce-13)
    checkout_url = Column(String(500), nullable=True)  # link de pago de Mercado Pago (init_point) mientras está pendiente
    # --- Aceptación de las condiciones de compra (consumidor-ecommerce-05 y 06) ---
    terms_version = Column(String(20), nullable=True)  # LEGAL_TERMS_VERSION aceptada
    terms_hash = Column(String(64), nullable=True)  # sha256 de la versión + textos exactos aceptados en el checkout
    terms_accepted_at = Column(DateTime, nullable=True)
    consent_prepayment_at = Column(DateTime, nullable=True)  # autorizó el cobro antes de la entrega
    terms_ip = Column(String(45), nullable=True)
    terms_user_agent = Column(String(255), nullable=True)
    # --- Devoluciones y reembolsos ---
    return_reason = Column(String(30), nullable=True)  # defectuoso | no_corresponde | no_llego | arrepentimiento | otro
    return_details = Column(Text, nullable=True)
    return_photos = Column(JSON, nullable=True)
    return_requested_at = Column(DateTime, nullable=True)
    return_decided_at = Column(DateTime, nullable=True)
    return_decision_note = Column(Text, nullable=True)
    refund_id = Column(String(100), nullable=True)
    refund_amount = Column(Numeric(10, 2), nullable=True)
    refund_status = Column(String(30), nullable=True)  # approved | pending | error | simulated
    refunded_at = Column(DateTime, nullable=True)
    provider = Column(String(30), nullable=True)
    provider_preference_id = Column(String(255), nullable=True)
    provider_payment_id = Column(String(255), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    paid_amount = Column(Numeric(10, 2), nullable=True)  # lo que cobró Mercado Pago (transaction_amount)
    review_note = Column(Text, nullable=True)  # motivo de revisión para admins (monto distinto, reembolso)
    carrier = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    shipped_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    refuge = relationship("Refuge")
    invoice = relationship("OrderInvoice", back_populates="order", uselist=False)
    # Bonificación de LFPC art. 92 Ter (defecto o no corresponde): obligación del refugio vendedor
    bonus = relationship("OrderBonus", back_populates="order", uselist=False, lazy="selectin")

    @property
    def refuge_name(self) -> str | None:
        return self.refuge.name if self.refuge else None

    @property
    def status_label(self) -> str:
        from app.services.order_flow import STATUS_LABELS

        return STATUS_LABELS.get(self.status, self.status)

    @property
    def bonus_info(self) -> dict | None:
        from app.services.reglas import bonus_out

        return bonus_out(self.bonus)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class OrderRefund(Base):
    """Cada reembolso (total o parcial) de un pedido, en el mes en que ocurre.

    Los estados de cuenta restan los reembolsos en el periodo en que se hicieron (fiscal-tienda: un reembolso en
    un mes distinto se descuenta del siguiente estado y del CFDI de retenciones), así un mes ya facturado no
    cambia. Mercado Pago reparte el reembolso en proporción entre el refugio y la plataforma (Split 1:1), por
    eso se guarda qué parte de la comisión y de las retenciones regresó (fee/isr/iva_reversed).
    """

    __tablename__ = "order_refunds"
    __table_args__ = (Index("ix_order_refunds_refuge_created", "refuge_id", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    fee_reversed = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)
    isr_reversed = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)
    iva_reversed = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)
    is_full = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # cierra el pedido
    provider_refund_id = Column(String(100), nullable=True)
    status = Column(String(30), nullable=True)  # approved | pending | simulated | refunded | charged_back
    by = Column(String(20), nullable=True)  # buyer | refuge | admin | system | mercadopago
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    order = relationship("Order")


class OrderBonus(Base):
    """Bonificación mínima de 20 % del precio pagado cuando procede una reclamación por defecto o porque el producto
    no corresponde (LFPC arts. 92 y 92 Ter). La paga el refugio vendedor; GuauWoow la registra y le da seguimiento."""

    __tablename__ = "order_bonuses"
    __table_args__ = (Index("ix_order_bonuses_status_due", "status", "due_at"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # comprador
    reason = Column(String(30), nullable=True)  # defectuoso | no_corresponde
    base_amount = Column(Numeric(10, 2), nullable=False)  # precio pagado de los productos reclamados (sin envío)
    # Partidas que cubre: [{order_item_id, product_id, quantity, unit_price}]; None = parte del pedido sin partidas
    # señaladas (la base es entonces lo reembolsado, sin el envío)
    covered_items = Column(JSON, nullable=True)
    percent = Column(Numeric(5, 2), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), default="pendiente", server_default=text("'pendiente'"), nullable=False)  # pendiente | pagada | improcedente
    due_at = Column(DateTime, nullable=True)  # 15 días para resolver la reclamación (LFPC art. 93)
    paid_at = Column(DateTime, nullable=True)
    payment_reference = Column(String(255), nullable=True)  # referencia de la transferencia o del reembolso
    note = Column(Text, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reminded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    order = relationship("Order", back_populates="bonus")


class DonationAmlFlag(Base):
    """Alerta de la ley antilavado (LFPIORPI art. 17 fr. XIII): lo que una misma cuenta dona a un refugio en 6 meses
    se acerca o rebasa el umbral de identificación (1,605 UMA) o de aviso (3,210 UMA). Avisa al refugio y al equipo."""

    __tablename__ = "donation_aml_flags"
    __table_args__ = (Index("ix_donation_aml_flags_pair", "user_id", "refuge_id", "level", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False)
    level = Column(String(20), nullable=False)  # aproximacion | identificacion | aviso
    total = Column(Numeric(12, 2), nullable=False)  # acumulado de 6 meses al momento de la alerta
    threshold = Column(Numeric(12, 2), nullable=False)
    window_start = Column(DateTime, nullable=False)
    donation_ids = Column(JSON, default=list, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class Donation(Base):
    __tablename__ = "donations"
    __table_args__ = (Index("ix_donations_status_created_at", "status", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    # pending | approved | expired | cancelled | amount_mismatch | refunded (rejected: datos anteriores)
    status = Column(String(30), default="pending", nullable=False)
    provider = Column(String(30), nullable=True)
    provider_preference_id = Column(String(255), nullable=True)
    provider_payment_id = Column(String(255), nullable=True)
    paid_amount = Column(Numeric(10, 2), nullable=True)  # lo que cobró Mercado Pago (transaction_amount)
    review_note = Column(Text, nullable=True)  # motivo de revisión para admins
    share_name = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # el refugio solo ve el nombre si es True
    created_at = Column(DateTime, default=_now, nullable=False)
    # Split (donativos-01): con qué cuenta se cobró y cuánto se quedó la plataforma
    payment_mode = Column(String(20), nullable=True)  # split | platform | simulated
    collector_id = Column(String(50), nullable=True)  # user_id de Mercado Pago del refugio
    fee_percent = Column(Numeric(5, 2), nullable=True)
    fee_amount = Column(Numeric(10, 2), default=0, server_default=text("0"), nullable=False)
    net_amount = Column(Numeric(10, 2), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    user = relationship("User")
    refuge = relationship("Refuge")

    @property
    def donor_display_name(self) -> str:
        """Nombre que puede ver el refugio."""
        if self.share_name and self.user and self.user.is_active:
            return self.user.full_name
        return "Donante anónimo"


class PaymentEvent(Base):
    """Pagos de Mercado Pago ya aplicados. Evita acreditar dos veces (webhook, IPN y reintentos en paralelo)."""

    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "payment_id", "status", name="uq_payment_events_payment_status"),)

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(30), default="mercadopago", nullable=False)
    payment_id = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False)  # estado en Mercado Pago: approved | refunded | charged_back
    kind = Column(String(20), nullable=False)  # order | donation
    object_id = Column(Integer, nullable=False)
    outcome = Column(String(50), nullable=False)  # paid | approved | refund_pending | amount_mismatch | duplicate | refunded
    amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class RefugePaymentAccount(Base):
    """Cuenta de Mercado Pago del refugio vinculada por OAuth (Marketplace split 1:1).

    Los tokens se guardan cifrados con una llave derivada de SECRET_KEY (services/mercadopago_oauth.py);
    nunca se devuelven por la API. El access_token dura 180 días y se renueva con el refresh_token.
    """

    __tablename__ = "refuge_payment_accounts"

    id = Column(Integer, primary_key=True, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False, unique=True)
    provider = Column(String(30), default="mercadopago", server_default=text("'mercadopago'"), nullable=False)
    status = Column(String(20), default="connected", server_default=text("'connected'"), nullable=False)  # connected | disconnected | error
    mp_user_id = Column(String(50), nullable=True, index=True)  # collector_id de los pagos
    access_token_enc = Column(Text, nullable=True)
    refresh_token_enc = Column(Text, nullable=True)
    public_key = Column(String(255), nullable=True)
    scope = Column(String(255), nullable=True)
    live_mode = Column(Boolean, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    refreshed_at = Column(DateTime, nullable=True)
    disconnected_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    refuge = relationship("Refuge", back_populates="payment_account")


class RefugeFiscalProfile(Base):
    """Datos fiscales del refugio vendedor (fiscal-tienda-21): receptor de los CFDI de comisión y retenciones."""

    __tablename__ = "refuge_fiscal_profiles"

    id = Column(Integer, primary_key=True, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False, unique=True)
    person_type = Column(String(10), nullable=False)  # fisica | moral
    # RFC, nombre y CP van cifrados en la base (crypto_storage.EncryptedText; se leen en claro)
    rfc = Column(EncryptedText, nullable=False)
    legal_name = Column(EncryptedText, nullable=False)  # nombre o razón social exacta del SAT
    regimen_fiscal = Column(String(3), nullable=False)  # clave c_RegimenFiscal
    postal_code = Column(EncryptedText, nullable=False)  # CP del domicilio fiscal
    is_donataria = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    csf_document_id = Column(String(64), nullable=True)  # Constancia de Situación Fiscal (documento privado)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    refuge = relationship("Refuge", back_populates="fiscal_profile")


class OrderInvoice(Base):
    """Factura que pide el comprador. Modelo B: el refugio vendedor emite el CFDI del producto y lo sube."""

    __tablename__ = "order_invoices"
    __table_args__ = (
        Index("ix_order_invoices_refuge_status", "refuge_id", "status"),
        Index("uq_order_invoices_uuid", "uuid", unique=True),  # un CFDI (UUID) no se adjunta a dos pedidos
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), default="requested", server_default=text("'requested'"), nullable=False)  # requested | issued | rejected
    # Datos fiscales del comprador cifrados en la base (crypto_storage.EncryptedText; se leen en claro)
    rfc = Column(EncryptedText, nullable=False)
    legal_name = Column(EncryptedText, nullable=False)
    regimen_fiscal = Column(String(3), nullable=False)
    postal_code = Column(EncryptedText, nullable=False)
    uso_cfdi = Column(String(4), nullable=False)
    email = Column(EncryptedText, nullable=False)
    uuid = Column(String(36), nullable=True)
    xml_document_id = Column(String(64), nullable=True)
    pdf_document_id = Column(String(64), nullable=True)
    note = Column(Text, nullable=True)
    requested_at = Column(DateTime, default=_now, nullable=False)
    issued_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    # Meta de 24 h (terminos-tienda 8.2): recordatorio al refugio y, si sigue pendiente, aviso al equipo
    reminded_at = Column(DateTime, nullable=True)
    escalated_at = Column(DateTime, nullable=True)

    order = relationship("Order", back_populates="invoice")


class Cfdi(Base):
    """CFDI que emite GuauWoow a cada refugio por periodo: comisión (ingreso) y retenciones."""

    __tablename__ = "cfdis"
    __table_args__ = (
        UniqueConstraint("kind", "period", "refuge_id", name="uq_cfdis_kind_period_refuge"),
        Index("ix_cfdis_status_period", "status", "period"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False)  # comision | retencion
    period = Column(String(7), nullable=False)  # YYYY-MM
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False, index=True)
    uuid = Column(String(36), nullable=True)
    status = Column(String(20), default="pending_pac", server_default=text("'pending_pac'"), nullable=False)  # pending_pac | issued | error
    subtotal = Column(Numeric(12, 2), default=0, server_default=text("0"), nullable=False)
    iva = Column(Numeric(12, 2), default=0, server_default=text("0"), nullable=False)
    isr_retenido = Column(Numeric(12, 2), default=0, server_default=text("0"), nullable=False)
    iva_retenido = Column(Numeric(12, 2), default=0, server_default=text("0"), nullable=False)
    total = Column(Numeric(12, 2), default=0, server_default=text("0"), nullable=False)
    xml_document_id = Column(String(64), nullable=True)
    pdf_document_id = Column(String(64), nullable=True)
    provider_ref = Column(String(100), nullable=True)  # id del CFDI en el PAC
    error = Column(Text, nullable=True)
    attempts = Column(Integer, default=0, server_default=text("0"), nullable=False)
    issued_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    refuge = relationship("Refuge")


class FosterHome(Base):
    __tablename__ = "foster_homes"
    __table_args__ = (Index("idx_foster_homes_status", "status"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    capacity = Column(Integer, default=1, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="foster_homes")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    due_date = Column(DateTime, nullable=False)
    type = Column(String(100), nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="reminders")
    match = relationship("Match")


class PhoneVerificationLog(Base):
    """Bitácora de envíos de código (auditoría, costos y límite de envíos cuando no hay Redis)."""

    __tablename__ = "phone_verification_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    phone = Column(String(20), nullable=False, index=True)
    ip = Column(String(64), nullable=True, index=True)
    provider = Column(String(20), nullable=False)
    success = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)


class AdminAuditLog(Base):
    """Bitácora de acciones de administración (quién hizo qué, sobre qué y desde dónde)."""

    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(Integer, nullable=True)
    details = Column(JSON, nullable=True)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)

    actor = relationship("User")


class ContentReport(Base):
    """Reporte de contenido (moderación): un usuario señala un perro, reporte, usuario, refugio, producto o mensaje."""

    __tablename__ = "content_reports"
    __table_args__ = (
        Index("ix_content_reports_status_created", "status", "created_at"),
        Index("ix_content_reports_target", "target_type", "target_id"),
        Index("ix_content_reports_reporter_created", "reporter_id", "created_at"),
        # Cola de moderación: abiertos por prioridad (0 = menores) y antigüedad
        Index("ix_content_reports_queue", "status", "priority", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # NULL = solicitud sin cuenta (retiro de una publicación importada por su autor: POST /facebook/author-removal,
    # o formulario público de reportes: POST /cumplimiento/reportes-publicos)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # dog | lost_report | user | refuge | product | message | veterinary | veterinary_review
    # | sin_identificar (formulario público sin enlace reconocible; target_id = 0)
    target_type = Column(String(30), nullable=False)
    target_id = Column(Integer, nullable=False)
    reason = Column(String(40), nullable=False)  # catálogo en services/legal_moderation.REASONS
    details = Column(Text, nullable=True)
    status = Column(String(20), default="open", server_default=text("'open'"), nullable=False)  # open | resolved | dismissed
    action = Column(String(30), nullable=True)  # hide_content | suspend_user | quarantine
    admin_notes = Column(Text, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    # --- Moderación legal (moderacion.html §1 y §4; proteccion-nna.html §7) ---
    source = Column(String(20), default="app", server_default=text("'app'"), nullable=False)  # app | publico | equipo
    priority = Column(Integer, default=3, server_default=text("3"), nullable=False)  # 0 menores · 1 urgente · 2 estafa/venta · 3 resto
    due_at = Column(DateTime, nullable=True)  # plazo objetivo de revisión
    auto_hidden = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # ocultado al recibirlo
    folio = Column(String(24), nullable=True, unique=True)  # acuse del formulario público
    contact_email = Column(String(255), nullable=True)  # correo opcional de quien reporta sin cuenta
    reporter_ip = Column(String(64), nullable=True)
    target_url = Column(String(1000), nullable=True)  # enlace que pegó quien reporta (formulario público)

    reporter = relationship("User", foreign_keys=[reporter_id])
    resolver = relationship("User", foreign_keys=[resolved_by])


class ModerationAction(Base):
    """Medida de moderación con su declaración de motivos (moderacion.html §5 a §7).

    Cada medida que afecta a una persona (ocultar, suspender, cancelar, retirar por derechos de autor, cuarentena)
    queda aquí con la regla aplicada, el origen de la detección, la duración y el plazo para apelar.
    """

    __tablename__ = "moderation_actions"
    __table_args__ = (
        Index("ix_moderation_actions_user", "user_id", "created_at"),
        Index("ix_moderation_actions_status_ends", "status", "ends_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(24), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # persona afectada
    target_type = Column(String(30), nullable=False)
    target_id = Column(Integer, nullable=True)
    action = Column(String(30), nullable=False)  # hide_content | suspend_user | cancel_account | copyright_removal | quarantine
    rule = Column(String(60), nullable=False)  # motivo del catálogo (p. ej. venta_animal) o regla de derechos de autor
    rule_text = Column(String(300), nullable=False)  # regla de los Lineamientos o de los Términos, en palabras
    detection = Column(String(20), nullable=False)  # reporte | equipo | filtro | autoridad | aviso_derechos
    duration_days = Column(Integer, nullable=True)  # None = sin fecha de fin
    ends_at = Column(DateTime, nullable=True)
    content_report_id = Column(Integer, ForeignKey("content_reports.id"), nullable=True)
    copyright_notice_id = Column(Integer, ForeignKey("copyright_notices.id"), nullable=True)
    evidence_id = Column(Integer, ForeignKey("evidence_records.id"), nullable=True)
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # None = automática
    notes = Column(Text, nullable=True)  # notas internas
    details = Column(JSON, nullable=True)  # lo que se ocultó en bloque (para revertir)
    notice_sent_at = Column(DateTime, nullable=True)
    notice_withheld_reason = Column(String(120), nullable=True)  # riesgo inminente, investigación o material de abuso
    appeal_until = Column(DateTime, nullable=True)
    status = Column(String(20), default="active", server_default=text("'active'"), nullable=False)  # active | revoked | lifted
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class ModerationAppeal(Base):
    """Apelación de una medida (moderacion.html §7). Funciona sin sesión: con el folio y el correo de la cuenta."""

    __tablename__ = "moderation_appeals"
    __table_args__ = (Index("ix_moderation_appeals_status_due", "status", "due_at"),)

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(24), nullable=False, unique=True)
    action_id = Column(Integer, ForeignKey("moderation_actions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    email = Column(String(255), nullable=True)
    arguments = Column(Text, nullable=False)
    evidence_text = Column(Text, nullable=True)  # pruebas: enlaces o descripción
    status = Column(String(20), default="pending", server_default=text("'pending'"), nullable=False)  # pending | upheld | reversed
    due_at = Column(DateTime, nullable=False)  # plazo para resolver (días hábiles)
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decision_note = Column(Text, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    action_ref = relationship("ModerationAction")


class EvidenceRecord(Base):
    """Bóveda de evidencia (Decreto NNA art. 5 fr. II): copia cifrada de lo retirado, al menos 90 días hábiles.

    El contenido vive cifrado en disco (services/evidence.py); aquí solo el índice de solo inserción con hash
    encadenado (row_hash = SHA-256 de prev_hash + campos inmutables). Al vencer sin retención legal se borra el
    archivo y la fila se queda con purged_at (la cadena no se rompe).
    """

    __tablename__ = "evidence_records"
    __table_args__ = (
        Index("ix_evidence_records_target", "target_type", "target_id"),
        Index("ix_evidence_records_purge", "retained_until", "legal_hold", "purged_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(30), nullable=False)  # ocultamiento_preventivo | contenido_retirado | cuenta_suspendida | derechos_autor | csam | preservacion
    target_type = Column(String(30), nullable=False)
    target_id = Column(Integer, nullable=True)
    owner_user_id = Column(Integer, nullable=True, index=True)  # sin FK: la evidencia sobrevive al borrado de la cuenta
    content_report_id = Column(Integer, nullable=True)
    copyright_notice_id = Column(Integer, nullable=True)
    authority_request_id = Column(Integer, nullable=True)
    reason = Column(String(60), nullable=True)
    is_csam = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    storage_path = Column(String(300), nullable=True)  # relativa a la carpeta de evidencia; None tras la purga
    size_bytes = Column(Integer, nullable=False, default=0, server_default=text("0"))
    content_sha256 = Column(String(64), nullable=False)  # del paquete sin cifrar
    files = Column(JSON, nullable=True)  # [{name, sha256, bytes}] solo metadatos
    prev_hash = Column(String(64), nullable=True)
    row_hash = Column(String(64), nullable=False, unique=True)
    retained_until = Column(DateTime, nullable=False)
    legal_hold = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    legal_hold_reason = Column(String(300), nullable=True)
    legal_hold_by_id = Column(Integer, nullable=True)
    legal_hold_at = Column(DateTime, nullable=True)
    purged_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class BlockedImageHash(Base):
    """Lista de bloqueo por hash (staydown): impide volver a subir una imagen idéntica a una retirada."""

    __tablename__ = "blocked_image_hashes"
    __table_args__ = (Index("ix_blocked_image_hashes_active", "active", "kind"),)

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False)  # derechos_autor | csam | autoridad | moderacion
    ahash = Column(String(16), nullable=False)  # hash promedio 8x8
    dhash = Column(String(16), nullable=False)  # hash de diferencias 9x8
    sha256 = Column(String(64), nullable=True)  # del archivo retirado
    source_url = Column(String(500), nullable=True)  # URL /uploads/ retirada (para no mandarla a la IA)
    copyright_notice_id = Column(Integer, ForeignKey("copyright_notices.id"), nullable=True)
    evidence_id = Column(Integer, nullable=True)
    active = Column(Boolean, default=True, server_default=text("true"), nullable=False)
    hits = Column(Integer, default=0, server_default=text("0"), nullable=False)  # intentos de volver a subirla
    last_hit_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class CopyrightNotice(Base):
    """Aviso de derechos de autor o marca (LFDA art. 114 Octies; Reglamento LFDA arts. 37 Bis a 37 Nonies).

    Estados: received → removed → (counter_notice → restored | litigation) → final; incomplete y rejected si no
    procede. El aviso se guarda íntegro con su SHA-256.
    """

    __tablename__ = "copyright_notices"
    __table_args__ = (
        Index("ix_copyright_notices_status_created", "status", "created_at"),
        Index("ix_copyright_notices_uploader", "uploader_user_id", "removed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(24), nullable=False, unique=True)
    kind = Column(String(20), default="derechos_autor", server_default=text("'derechos_autor'"), nullable=False)  # derechos_autor | marca
    status = Column(String(20), default="received", server_default=text("'received'"), nullable=False)
    content_url = Column(String(1000), nullable=False)  # ubicación electrónica (art. 37 Quáter fr. I)
    target_type = Column(String(30), nullable=True)
    target_id = Column(Integer, nullable=True)
    photo_urls = Column(JSON, nullable=True)  # imágenes retiradas (staydown)
    work = Column(Text, nullable=False)  # obra o derecho que se infringe
    facts = Column(Text, nullable=False)  # breve descripción de los hechos
    claimant_name = Column(String(255), nullable=False)
    claimant_capacity = Column(String(20), nullable=False)  # titular | representante
    represented_name = Column(String(255), nullable=True)
    representation_document = Column(Text, nullable=True)  # descripción o enlace del poder o autorización
    email = Column(String(255), nullable=False)
    alt_email = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=False)
    address = Column(Text, nullable=False)
    good_faith = Column(Boolean, nullable=False)  # bajo protesta de decir verdad y de buena fe
    knows_penalty = Column(Boolean, nullable=False)  # conoce la sanción del art. 232 Quinquies
    sha256 = Column(String(64), nullable=False)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    uploader_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_at = Column(DateTime, nullable=True)  # plazo objetivo de retiro
    removed_at = Column(DateTime, nullable=True)
    removed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploader_notified_at = Column(DateTime, nullable=True)
    restore_from = Column(DateTime, nullable=True)  # día hábil 10 después del contra-aviso
    restore_until = Column(DateTime, nullable=True)  # día hábil 15
    proceeding_at = Column(DateTime, nullable=True)  # quien avisó acreditó un procedimiento
    proceeding_note = Column(Text, nullable=True)
    restored_at = Column(DateTime, nullable=True)
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class CopyrightCounterNotice(Base):
    """Contra-aviso de quien subió el contenido retirado (Reglamento LFDA art. 37 Septies)."""

    __tablename__ = "copyright_counter_notices"

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(24), nullable=False, unique=True)
    notice_id = Column(Integer, ForeignKey("copyright_notices.id"), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    capacity = Column(String(20), nullable=False)  # propio | representante
    represented_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(30), nullable=True)
    address = Column(Text, nullable=False)
    basis = Column(String(20), nullable=False)  # licencia | excepcion | dominio_publico
    basis_details = Column(Text, nullable=False)  # contrato o licencia, o la excepción que ampara el uso
    good_faith = Column(Boolean, nullable=False)
    knows_penalty = Column(Boolean, nullable=False)
    sha256 = Column(String(64), nullable=False)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    notice = relationship("CopyrightNotice")


class AuthorityRequest(Base):
    """Registro de requerimientos de autoridad y de denuncias o alertas que presenta GuauWoow (autoridades.html).

    Niveles de entrega (§3): 1 datos de cuenta (oficio fundado y motivado), 2 contenido de comunicaciones
    (autorización judicial), 3 ubicación (Juez de control o CNPP art. 303). Cada cambio va a la bitácora.
    """

    __tablename__ = "authority_requests"
    __table_args__ = (Index("ix_authority_requests_status_due", "status", "first_response_due_at"),)

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(24), nullable=False, unique=True)
    direction = Column(String(10), nullable=False)  # entrante (requerimiento) | saliente (denuncia o alerta)
    kind = Column(String(30), nullable=False)  # datos_cuenta | comunicaciones | ubicacion | conservacion | retiro | orden_proteccion | denuncia | otro
    level = Column(Integer, nullable=True)  # 1 | 2 | 3 (solo entregas de información)
    authority_name = Column(String(255), nullable=False)
    authority_type = Column(String(40), nullable=False)  # ministerio_publico | juez | paot | impi | profeco | indautor | policia | otra
    case_number = Column(String(120), nullable=True)  # expediente, carpeta de investigación o procedimiento
    legal_basis = Column(Text, nullable=True)  # fundamento y motivación
    requested_data = Column(Text, nullable=True)
    targets = Column(JSON, nullable=True)  # [{type, id}] cuentas o contenidos a los que se refiere
    involves_minor = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    life_risk = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    judicial_order = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # trae autorización judicial
    participant_consent = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # lo aporta una persona participante
    received_at = Column(DateTime, nullable=False)
    due_at = Column(DateTime, nullable=True)  # plazo que fija el oficio
    first_response_due_at = Column(DateTime, nullable=True)  # objetivo interno de primera respuesta
    authenticity_verified = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    authenticity_method = Column(String(300), nullable=True)
    legal_review = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    status = Column(String(20), default="recibido", server_default=text("'recibido'"), nullable=False)
    decision = Column(Text, nullable=True)  # qué se entrega y por qué
    response_summary = Column(Text, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    user_notified = Column(Boolean, nullable=True)
    notice_withheld_reason = Column(String(300), nullable=True)
    external_folio = Column(String(120), nullable=True)  # acuse de la autoridad o folio de la denuncia
    evidence_ids = Column(JSON, nullable=True)
    content_report_id = Column(Integer, ForeignKey("content_reports.id"), nullable=True)
    handled_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class Veterinary(Base):
    """Clínica veterinaria del directorio. La publica un usuario (una por cuenta) y un admin la verifica
    cotejando la cédula del médico veterinario responsable en el Registro Nacional de Profesionistas.

    De Google solo se guarda el place_id (y una URL de Google Maps derivada de él): las reseñas, la
    calificación y los autores se piden en tiempo real y nunca se escriben en la base (términos de
    Google Maps Platform 3.2.3(a)/(b); docs/legal/secciones/gap-veterinarias-y-resenas.json).
    """

    __tablename__ = "veterinaries"
    __table_args__ = (
        Index("idx_veterinaries_status", "status"),
        Index("idx_veterinaries_city", "city"),
        Index("idx_veterinaries_geo", "latitude", "longitude"),  # caja de búsqueda por distancia
    )

    id = Column(Integer, primary_key=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    address = Column(String(500), nullable=True)  # domicilio del local: es público (LFPC 76 Bis fr. III)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(10), nullable=True)
    latitude = Column(Float, nullable=True)  # exactas: la dirección del negocio es pública
    longitude = Column(Float, nullable=True)
    phone = Column(String(50), nullable=True)
    whatsapp = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    website = Column(String(500), nullable=True)
    hours = Column(JSON, default=dict, nullable=False)  # {"mon": [{"open": "09:00", "close": "18:00"}], ...}
    services = Column(JSON, default=list, nullable=False)  # lista de servicios (texto corto)
    emergency_24h = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    photos = Column(JSON, default=list, nullable=False)
    responsible_vet_name = Column(String(255), nullable=False)  # como aparece en la cédula
    cedula_profesional = Column(String(20), nullable=False)
    cedula_institution = Column(String(255), nullable=True)  # institución que la expidió (LGS art. 83)
    cedula_document_id = Column(String(64), nullable=True)  # documento privado (POST /upload/document)
    cedula_carrera = Column(String(255), nullable=True)  # carrera registrada en el RNP (la anota el admin al cotejar)
    google_place_id = Column(String(255), nullable=True)  # lo único de Google que se conserva
    google_maps_url = Column(String(500), nullable=True)  # URL de Maps construida con el place_id
    google_place_checked_at = Column(DateTime, nullable=True)  # última validación del place_id (tarea semanal)
    google_place_error_at = Column(DateTime, nullable=True)  # desde cuándo Google responde NOT_FOUND
    google_fetched_at = Column(DateTime, nullable=True)  # última consulta en tiempo real exitosa (solo la fecha)
    status = Column(String(20), default="pending", server_default=text("'pending'"), nullable=False)  # pending | verified | rejected
    rejection_note = Column(Text, nullable=True)
    is_hidden = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # oculta por moderación
    verified_at = Column(DateTime, nullable=True)  # "Cédula consultada en el Registro Nacional de Profesionistas el ..."
    verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    verification_expires_at = Column(DateTime, nullable=True)  # reverificación anual
    # Captura fechada del cotejo en el RNP o la CSP (documento privado que sube el admin al verificar)
    verification_evidence_document_id = Column(String(64), nullable=True)
    # Desde cuándo dejó de publicarse (rechazo, revocación, vencimiento o baja): base de la retención de 12 meses
    # de la cédula y de la evidencia (tarea purge_documents)
    unpublished_at = Column(DateTime, nullable=True)
    # La imagen de la cédula se borra 30 días después de verificar o rechazar (R15/R17, services/retention.py);
    # queda la constancia: número, institución, carrera, verified_at y la captura del cotejo en el RNP
    cedula_document_purged_at = Column(DateTime, nullable=True)
    consent_at = Column(DateTime, nullable=True)  # aceptó publicar nombre, cédula e institución del responsable
    consent_terms_version = Column(String(20), nullable=True)  # versión de los Términos vigente al registrar
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    owner = relationship("User", foreign_keys=[owner_user_id])
    reviews = relationship("VeterinaryReview", back_populates="veterinary", cascade="all, delete-orphan")

    # Atributos transitorios (no persistidos) que llenan los endpoints
    distance_km = None
    open_now = None
    rating_avg = None
    rating_count = None
    badge_text = None
    verified_label = None

    @property
    def google_linked(self) -> bool:
        return bool(self.google_place_id)


class VeterinaryReview(Base):
    """Reseña propia (in-app) de una clínica: una por cuenta y clínica, editable por su autor."""

    __tablename__ = "veterinary_reviews"
    __table_args__ = (
        UniqueConstraint("veterinary_id", "user_id", name="uq_veterinary_reviews_vet_user"),
        Index("idx_veterinary_reviews_vet_created", "veterinary_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    veterinary_id = Column(Integer, ForeignKey("veterinaries.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    visited_month = Column(String(7), nullable=True)  # "YYYY-MM": fecha aproximada de la visita
    incentivized = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # recibió descuento o regalo
    owner_reply = Column(Text, nullable=True)  # respuesta pública de la clínica (una por reseña)
    owner_reply_at = Column(DateTime, nullable=True)
    # Aclaración publicada sin comentarios tras una solicitud aprobada (VeterinaryRequest kind="aclaracion")
    clarification = Column(Text, nullable=True)
    clarification_at = Column(DateTime, nullable=True)
    is_hidden = Column(Boolean, default=False, server_default=text("false"), nullable=False)  # oculta por moderación
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    # Va al final: dentro de la clase el nombre "text" tapa a sqlalchemy.text, que usan los server_default
    text = Column(Text, nullable=True)

    veterinary = relationship("Veterinary", back_populates="reviews")
    user = relationship("User")


class VeterinaryRequest(Base):
    """Solicitud sobre una clínica o una reseña, con o sin cuenta (gap-veterinarias-y-resenas 13, 14 y 16).

    kind="aclaracion": la clínica o una persona aludida pide publicar una aclaración junto a una reseña; el equipo
    la revisa en 5 días hábiles y, si procede, se publica sin comentarios (VeterinaryReview.clarification).
    kind="queja": formulario público (también para personas sin cuenta) para reportar una clínica o una reseña;
    se revisa en 72 horas hábiles (3 días hábiles).
    """

    __tablename__ = "veterinary_requests"
    __table_args__ = (
        Index("idx_veterinary_requests_status_created", "status", "created_at"),
        Index("idx_veterinary_requests_vet", "veterinary_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False)  # aclaracion | queja
    veterinary_id = Column(Integer, ForeignKey("veterinaries.id"), nullable=False)
    review_id = Column(Integer, ForeignKey("veterinary_reviews.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # null: persona sin cuenta
    name = Column(String(255), nullable=True)  # nombre de contacto (sin cuenta) o el de la cuenta
    email = Column(String(255), nullable=True)  # correo para responder (sin cuenta)
    relation = Column(String(20), nullable=False)  # clinica | aludido | cliente | otro
    reason = Column(String(40), nullable=True)  # motivo (quejas): honor_reputacion, resena_falsa, ...
    status = Column(String(20), default="pending", server_default=text("'pending'"), nullable=False)  # pending | published | resolved | rejected
    due_at = Column(DateTime, nullable=False)  # plazo de respuesta (días hábiles)
    resolution_note = Column(Text, nullable=True)  # lo que se le responde a quien la presentó
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    # Va al final: dentro de la clase el nombre "text" tapa a sqlalchemy.text, que usan los server_default
    text = Column(Text, nullable=False)

    veterinary = relationship("Veterinary")
    review = relationship("VeterinaryReview")
    user = relationship("User", foreign_keys=[user_id])


# --------------------------------------------------------------------------- centro de solicitudes (K-SOLIC)
class FolioCounter(Base):
    """Consecutivo de folios por prefijo y año («PF-2026-00001»). Se incrementa con un solo UPDATE atómico
    (services/solicitudes.next_folio), así dos solicitudes simultáneas nunca reciben el mismo folio."""

    __tablename__ = "folio_counters"

    scope = Column(String(10), primary_key=True)  # PF = centro de solicitudes
    year = Column(Integer, primary_key=True)
    last_value = Column(Integer, default=0, server_default=text("0"), nullable=False)


class ComplianceRequest(Base):
    """Solicitud del centro de solicitudes, con o sin cuenta (derechos-arco, atencion-y-quejas, contenido-importado).

    kind: acceso | rectificacion | cancelacion | oposicion | revocacion | limitacion (derechos ARCO y revocación,
    LFPDPPP arts. 21 a 34) | queja | aclaracion (atención a clientes, LFPC) | retiro_importado (publicación
    importada de Facebook: se oculta de inmediato y se borra en menos de 72 h).
    status: recibida -> en_revision -> respondida -> efectiva | cerrada. Plazos en días hábiles con
    services/order_flow.add_business_days (sin fines de semana ni días de descanso obligatorio).
    """

    __tablename__ = "compliance_requests"
    __table_args__ = (
        Index("ix_compliance_requests_status_respond_by", "status", "respond_by"),
        Index("ix_compliance_requests_kind_received", "kind", "received_at"),
        Index("ix_compliance_requests_email", "email"),
        Index("ix_compliance_requests_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), nullable=False, unique=True)  # PF-AAAA-NNNNN
    kind = Column(String(30), nullable=False)
    status = Column(String(20), default="recibida", server_default=text("'recibida'"), nullable=False)
    outcome = Column(String(20), nullable=True)  # procede | procede_parcial | no_procede | sin_datos
    denial_reason = Column(String(40), nullable=True)  # causa de la negativa (LFPDPPP art. 33)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # null: sin cuenta
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)  # minúsculas; null solo si llegó por WhatsApp
    phone = Column(String(30), nullable=True)
    channel = Column(String(20), default="web", server_default=text("'web'"), nullable=False)  # web | app | whatsapp | correo | escrito
    acting_as = Column(String(20), default="titular", server_default=text("'titular'"), nullable=False)  # titular | representante
    holder_name = Column(String(255), nullable=True)  # persona titular, cuando quien presenta es su representante
    description = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)  # campos propios del tipo: permisos, alcance, enlace, relación, motivo...
    lost_report_id = Column(Integer, ForeignKey("lost_reports.id", ondelete="SET NULL"), nullable=True)
    content_report_id = Column(Integer, ForeignKey("content_reports.id", ondelete="SET NULL"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    # Identidad: cuenta con correo verificado, enlace de confirmación, WhatsApp o identificación (que se borra)
    identity_verified_at = Column(DateTime, nullable=True)
    identity_method = Column(String(20), nullable=True)  # cuenta | correo | whatsapp | identificacion | otro
    confirm_token_hash = Column(String(64), nullable=True, index=True)  # sha256 del enlace de confirmación
    confirm_expires_at = Column(DateTime, nullable=True)
    access_token_hash = Column(String(64), nullable=True, index=True)  # enlace para contestar, subir o descargar
    access_expires_at = Column(DateTime, nullable=True)
    id_document_id = Column(String(64), nullable=True)  # identificación en /uploads/private (solo si se pidió)
    id_document_sha256 = Column(String(64), nullable=True)  # constancia que queda después de borrarla
    id_document_requested_at = Column(DateTime, nullable=True)
    id_document_uploaded_at = Column(DateTime, nullable=True)
    id_document_purged_at = Column(DateTime, nullable=True)
    # Plazos
    received_at = Column(DateTime, default=_now, nullable=False)
    first_response_due_at = Column(DateTime, nullable=True)  # quejas: primera respuesta
    first_response_at = Column(DateTime, nullable=True)
    respond_by = Column(DateTime, nullable=False)
    respond_extended_at = Column(DateTime, nullable=True)  # ampliación (una sola vez, LFPDPPP art. 31)
    effective_by = Column(DateTime, nullable=True)  # 15 días hábiles desde la respuesta, si procede
    effective_extended_at = Column(DateTime, nullable=True)
    extension_reason = Column(Text, nullable=True)
    info_requested_at = Column(DateTime, nullable=True)  # requerimiento de información (una sola vez)
    info_due_at = Column(DateTime, nullable=True)
    info_received_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    response_text = Column(Text, nullable=True)
    effective_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    events = relationship("ComplianceRequestEvent", back_populates="request", cascade="all, delete-orphan",
                          order_by="ComplianceRequestEvent.id")


class ComplianceRequestEvent(Base):
    """Historial de una solicitud: cada cambio de estado, requerimiento, ampliación, respuesta o nota."""

    __tablename__ = "compliance_request_events"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("compliance_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)  # creada | confirmada | en_revision | requerimiento | ... | nota
    status = Column(String(20), nullable=False)  # estado de la solicitud después del evento
    public_note = Column(Text, nullable=True)  # lo que se le comunicó a quien presentó la solicitud
    internal_note = Column(Text, nullable=True)  # solo para el equipo
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    request = relationship("ComplianceRequest", back_populates="events")
    actor = relationship("User")


# --------------------------------------------------------------------------- consentimiento (K-DOCS, K-ACEPT, K-PREF)
class LegalDocument(Base):
    """Registro de versiones de los documentos legales (app/legal/versiones.json, lo escribe scripts/render-legal.py).

    Una fila por (slug, sha256): si se vuelve a generar la misma versión con otro texto (p. ej. al llenar datos
    pendientes) queda otra fila, para que cada huella aceptada tenga su registro. La versión «vigente» de un
    documento es la más reciente cuya fecha de entrada en vigor (effective_at) ya pasó o no tiene fecha; las de
    fecha futura son «próximas» (aviso de 30 días). Lo sincroniza «python -m app.cli sync-legal-docs».
    """

    __tablename__ = "legal_documents"
    __table_args__ = (
        UniqueConstraint("slug", "sha256", name="uq_legal_documents_slug_sha256"),
        Index("ix_legal_documents_slug_published", "slug", "published_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(80), nullable=False)
    title = Column(String(255), nullable=False)
    version = Column(String(20), nullable=False)
    effective_at = Column(DateTime, nullable=True)  # entrada en vigor (FECHA_DE_ENTRADA_EN_VIGOR); null = al publicarse
    published_at = Column(DateTime, default=_now, nullable=False)  # primera vez que se registró esta huella
    sha256 = Column(String(64), nullable=False)  # huella del HTML publicado
    requires_reacceptance = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    summary = Column(Text, nullable=True)  # resumen de cambios (sección «Versiones» de la plantilla)
    url = Column(String(255), nullable=False)
    notice_sent_at = Column(DateTime, nullable=True)  # aviso previo (correo + app) ya enviado
    notice_cursor = Column(Integer, default=0, server_default=text("0"), nullable=False)  # último user_id avisado
    created_at = Column(DateTime, default=_now, nullable=False)


class LegalAcceptance(Base):
    """Bitácora de aceptaciones, de solo inserción (Código de Comercio arts. 89 bis y 93).

    Cada fila encadena la huella de la anterior (prev_hash) en row_hash = SHA-256 de prev_hash + los campos
    (services/legal_acceptance.row_digest): si alguien edita o borra una fila, la cadena deja de cuadrar
    (verify_chain). Un trigger de Postgres bloquea UPDATE, DELETE y TRUNCATE (migración 0004).
    """

    __tablename__ = "legal_acceptances"
    __table_args__ = (
        UniqueConstraint("prev_hash", name="uq_legal_acceptances_prev_hash"),  # la cadena no se bifurca
        Index("ix_legal_acceptances_user_slug", "user_id", "slug", "id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    slug = Column(String(80), nullable=False)  # documento (terminos, privacidad, terminos-tienda, mayoria-de-edad...)
    version = Column(String(20), nullable=False)
    sha256 = Column(String(64), nullable=False)  # huella del texto que se le mostró
    accepted_at = Column(DateTime, default=_now, nullable=False)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    method = Column(String(20), nullable=False)  # registro | reaceptacion | checkout | anexo | donativo
    context = Column(JSON, nullable=True)  # p. ej. {"order_id": 12} o {"refuge_id": 3}
    prev_hash = Column(String(64), nullable=False)
    row_hash = Column(String(64), nullable=False, unique=True)


class ConsentRecord(Base):
    """Cada permiso que se da o se retira (alertas cercanas, WhatsApp, correos promocionales, analítica).

    De solo inserción: el estado vigente de un propósito es su fila más reciente. text_version identifica el
    texto exacto que se mostró ("2026-10-17#<12 primeros del sha256 del texto>", services/consent.CONSENT_TEXTS).
    """

    __tablename__ = "consent_records"
    __table_args__ = (Index("ix_consent_records_user_purpose", "user_id", "purpose", "id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # null: número de WhatsApp sin cuenta
    phone = Column(String(30), nullable=True)  # bot de WhatsApp (BAJA/ALTA/ELIMINAR)
    purpose = Column(String(40), nullable=False)  # notify_nearby | whatsapp_alerts | email_marketing | analytics_cookies
    granted = Column(Boolean, nullable=False)
    text_version = Column(String(40), nullable=False)
    channel = Column(String(20), nullable=False)  # app | registro | whatsapp | web | solicitud | sistema
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class AgeCheck(Base):
    """Verificación reforzada de edad (L-edad): constancia de quién la pidió, por qué y con qué resultado.

    Sin copias de identificaciones ni biometría: se vuelve a confirmar la fecha de nacimiento, se verifica un
    código nuevo por SMS y se firma una declaración. Solo se guarda la constancia (fechas, método, resultado).
    """

    __tablename__ = "age_checks"
    __table_args__ = (Index("ix_age_checks_status_created", "status", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), default="required", server_default=text("'required'"), nullable=False)  # required | passed | cleared | failed
    reason = Column(String(40), nullable=False)  # involucra_menor | solicitud_admin | otra_senal
    content_report_id = Column(Integer, ForeignKey("content_reports.id", ondelete="SET NULL"), nullable=True)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # admin que la pidió
    note = Column(Text, nullable=True)  # nota interna del equipo
    attempts = Column(Integer, default=0, server_default=text("0"), nullable=False)  # fechas que no coincidieron
    birth_date_confirmed_at = Column(DateTime, nullable=True)
    otp_sent_at = Column(DateTime, nullable=True)
    otp_verified_at = Column(DateTime, nullable=True)
    declaration_at = Column(DateTime, nullable=True)
    method = Column(String(60), nullable=True)  # fecha_nacimiento+sms+declaracion | liberada_por_admin
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    content_report = relationship("ContentReport")


def _age_signal_before_flush(session, flush_context, instances):
    """Señal de riesgo de edad: un reporte «involucra a un menor» contra una cuenta la pasa a verificación reforzada
    (services/age_check.flag_from_new_reports). Funciona con cualquier ruta que cree el ContentReport."""
    from app.services.age_check import flag_from_new_reports

    flag_from_new_reports(session)


from sqlalchemy import event as _sa_event  # noqa: E402
from sqlalchemy.orm import Session as _SaSession  # noqa: E402

_sa_event.listen(_SaSession, "before_flush", _age_signal_before_flush)


# =========================================================================== seguridad (L-seguridad)
class MfaRecoveryCode(Base):
    """Códigos de recuperación de la verificación en dos pasos: 10 por admin, de un solo uso, con hash PBKDF2."""

    __tablename__ = "mfa_recovery_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(200), nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class SecurityIncident(Base):
    """Registro de incidentes (bitácora de vulneraciones, runbook-incidentes.md §10; LFPDPPP arts. 18 y 19).

    Incluye los incidentes no notificados. category: vulneracion (datos personales) | disponibilidad (caída) |
    mantenimiento (programado; se anuncia en /cumplimiento/estado). Mientras freeze_purges sea true y el incidente
    no esté cerrado, la purga diaria de conservación no borra nada (runbook §5 paso 2). Se conserva 5 años tras el
    cierre (R35).
    """

    __tablename__ = "security_incidents"
    __table_args__ = (
        Index("ix_security_incidents_status_detected", "status", "detected_at"),
        Index("ix_security_incidents_public", "public", "started_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), nullable=True, unique=True)  # INC-AAAA-NNNN
    title = Column(String(200), nullable=False)
    category = Column(String(20), default="vulneracion", server_default=text("'vulneracion'"), nullable=False)
    # perdida | robo_copia | uso_no_autorizado | dano_alteracion | caida | credenciales | aviso_proveedor | otro
    incident_type = Column(String(30), nullable=True)
    severity = Column(String(2), default="S3", server_default=text("'S3'"), nullable=False)  # S1 | S2 | S3
    status = Column(String(20), default="abierto", server_default=text("'abierto'"), nullable=False)  # abierto | contenido | cerrado
    detection_source = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)  # qué pasó (interno)
    systems_affected = Column(JSON, nullable=True)  # ["uploads/private", "api", ...]
    data_categories = Column(JSON, nullable=True)  # ["identificacion", "contacto", ...]
    components = Column(JSON, nullable=True)  # componentes del tablero: api, base_de_datos, cola, correo, pagos...
    affected_count = Column(Integer, nullable=True)  # titulares afectados (estimado)
    significant_impact = Column(Boolean, nullable=True)  # afectación significativa (LFPDPPP art. 19)
    significant_impact_reason = Column(Text, nullable=True)  # la decisión y su razón, también si no se avisa
    contractual_notices = Column(JSON, nullable=True)  # [{to, at, ref}] Mercado Pago, Meta, otros
    authority_report = Column(JSON, nullable=True)  # {authority, at, folio}
    sabg_notified = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    root_cause = Column(Text, nullable=True)
    immediate_actions = Column(Text, nullable=True)
    definitive_actions = Column(Text, nullable=True)
    evidence_ref = Column(String(500), nullable=True)  # dónde está la evidencia preservada (cadena de custodia)
    freeze_purges = Column(Boolean, default=True, server_default=text("true"), nullable=False)
    # El congelamiento dura como máximo 30 días (services/retention.FREEZE_MAX_DIAS); lo renueva un superadmin
    freeze_purges_until = Column(DateTime, nullable=True)
    detected_at = Column(DateTime, default=_now, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    contained_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)  # inicio del impacto (o del mantenimiento programado)
    ended_at = Column(DateTime, nullable=True)  # fin del impacto
    # Publicación en el tablero de estado (solo el resumen; nunca detalles que ayuden a un atacante)
    public = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    public_summary = Column(Text, nullable=True)
    # Aviso a titulares (runbook §7): {version, fecha, resumen, datos, no_afectados, acciones, recomendaciones, mas_info}
    notice = Column(JSON, nullable=True)
    notice_version = Column(Integer, default=0, server_default=text("0"), nullable=False)
    timeline = Column(JSON, nullable=True)  # [{at, by, text}]
    lead_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class SecurityIncidentNotice(Base):
    """Cada aviso enviado a una persona afectada: usuario, canal, fecha y versión del aviso (runbook §5 paso 6)."""

    __tablename__ = "security_incident_notices"
    __table_args__ = (Index("ix_security_incident_notices_incident", "incident_id", "user_id"),)

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("security_incidents.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    channel = Column(String(10), nullable=False)  # app | email
    notice_version = Column(Integer, nullable=False)
    status = Column(String(20), default="enviado", server_default=text("'enviado'"), nullable=False)  # enviado | sin_correo | error
    sent_at = Column(DateTime, default=_now, nullable=False)
    sent_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class RetentionRun(Base):
    """Cada corrida de la purga de conservación (services/retention.py): qué hizo por categoría o por qué no corrió."""

    __tablename__ = "retention_runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=_now, nullable=False, index=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running", server_default=text("'running'"), nullable=False)  # running | ok | error | frozen | disabled
    dry_run = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    results = Column(JSON, nullable=True)  # {clave: {...conteos}}
    error = Column(Text, nullable=True)
