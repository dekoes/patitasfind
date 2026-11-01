from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, field_serializer, model_validator

import re as _re_shop

from app.services.images import validate_upload_url
from app.services.privacy import coarse, round_distance

# Fotos y avatares que manda el usuario: solo archivos de nuestros /uploads (sin enlaces externos ni "..")
UploadUrl = Annotated[str, AfterValidator(validate_upload_url)]
PhotoList = Annotated[list[UploadUrl], Field(max_length=10)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- Usuarios
class UserBase(BaseModel):
    email: str
    full_name: str
    phone: str | None = None
    city: str | None = None
    country: str | None = None


class UserCreate(UserBase):
    password: str
    # Casilla de Términos + Aviso de Privacidad (también acepta "accept_terms")
    accepted_terms: bool = Field(False, validation_alias=AliasChoices("accepted_terms", "accept_terms"))
    # Casilla SEPARADA de mayoría de edad y fecha de nacimiento (L-edad): se rechaza a menores de 18
    is_adult: bool = False
    birth_date: date | None = None
    marketing_opt_in: bool = False


class UserLogin(BaseModel):
    email: str
    password: str


class User(UserBase, ORM):
    id: int
    role: str
    is_active: bool
    latitude: float | None = None
    longitude: float | None = None
    phone_verified: bool = False
    phone_verification_required: bool = False
    has_password: bool = False
    avatar_url: str | None = None
    terms_accepted_at: datetime | None = None
    terms_version: str | None = None
    privacy_version: str | None = None
    marketing_opt_in: bool = False
    email_verified: bool = False
    notify_nearby: bool = False
    # Consentimiento y edad (K-PREF, L-edad)
    whatsapp_alerts: bool = False
    email_marketing: bool = False
    birth_date: date | None = None
    age_declared: bool = False
    age_check_required: bool = False
    age_declaration_required: bool = False
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    avatar_url: UploadUrl | None = None
    marketing_opt_in: bool | None = None
    notify_nearby: bool | None = None


class UserMini(ORM):
    id: int
    full_name: str
    avatar_url: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str


class LoginResponse(BaseModel):
    """POST /auth/login: sesión, o (admins) el segundo paso de la verificación en dos pasos.

    Con mfa_required=true no hay access_token: se manda el código a POST /auth/mfa/verify con el mfa_token
    (vale 5 minutos). mfa_enrollment_required=true: aún no la configura y es obligatoria (POST /auth/mfa/setup).
    """

    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool | None = None
    mfa_token: str | None = None
    mfa_enrollment_required: bool | None = None


class MfaVerifyRequest(BaseModel):
    mfa_token: str = Field(..., max_length=2000)
    code: str = Field(..., max_length=20)  # 6 dígitos de la app o un código de recuperación


class MfaSetupRequest(BaseModel):
    mfa_token: str | None = Field(None, max_length=2000)  # sin sesión: el comprobante del primer paso
    # Cambio de app (la cuenta ya tiene MFA): código vigente de la app o de recuperación y la contraseña
    code: str | None = Field(None, max_length=20)
    password: str | None = Field(None, max_length=200)


class MfaEnableRequest(BaseModel):
    code: str = Field(..., max_length=20)
    mfa_token: str | None = Field(None, max_length=2000)


class MfaCodeRequest(BaseModel):
    code: str = Field(..., max_length=20)
    password: str | None = Field(None, max_length=200)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class PhoneVerifyRequest(BaseModel):
    code: str


class PhoneSendRequest(BaseModel):
    phone: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str | None = None
    new_password: str


class AccountDeleteRequest(BaseModel):
    password: str | None = None
    confirm: str


class TermsAcceptRequest(BaseModel):
    accepted_terms: bool = Field(validation_alias=AliasChoices("accepted_terms", "accept_terms"))
    marketing_opt_in: bool | None = None
    # Obligatorios si la cuenta aún no los tiene (p. ej. creada con Google)
    is_adult: bool | None = None
    birth_date: date | None = None


class VerifyEmailRequest(BaseModel):
    token: str


# ---------------------------------------------------------------- Perros
class DogCreate(BaseModel):
    name: str
    breed: str | None = None
    age_years: int | None = None
    age_months: int | None = None
    size: str | None = None
    color: str | None = None
    description: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photos: PhotoList | None = None
    # Perro encontrado (perdidos-y-encontrados §6; services/reglas.py): reporte de «encontrado» y lista de revisión
    found_report_id: int | None = None
    was_found: bool | None = None  # «Lo encontré en la calle»: no se publica en adopción hasta cumplir el plazo
    microchip_checked: bool | None = None
    microchip_result: Literal["sin_chip", "chip_sin_registro", "chip_tutor_contactado"] | None = None
    authority_notified: bool | None = None
    authority_notice: str | None = Field(None, max_length=255)  # a qué autoridad se avisó y folio


class DogUpdate(BaseModel):
    name: str | None = None
    breed: str | None = None
    age_years: int | None = None
    age_months: int | None = None
    size: str | None = None
    color: str | None = None
    description: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photos: PhotoList | None = None
    found_report_id: int | None = None
    was_found: bool | None = None
    microchip_checked: bool | None = None
    microchip_result: Literal["sin_chip", "chip_sin_registro", "chip_tutor_contactado"] | None = None
    authority_notified: bool | None = None
    authority_notice: str | None = Field(None, max_length=255)


class DogUpdateStatus(BaseModel):
    status: str


class DogOut(ORM):
    id: int
    owner_id: int
    name: str
    breed: str | None = None
    age_years: int | None = None
    age_months: int | None = None
    size: str | None = None
    color: str | None = None
    description: str | None = None
    status: str
    photos: list
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime
    owner: UserMini | None = None
    distance_km: float | None = None
    # ai_analysis y photo_signature no se exponen: son JSON pesados que solo usa el matching
    is_hidden: bool = False  # solo lo ven en True el dueño y los admins

    # Público: coordenadas aproximadas (~1 km). DogPrivateOut (dueño y admins) las da exactas.
    exact_coords: ClassVar[bool] = False

    @field_serializer("latitude", "longitude")
    def _ser_coord(self, value: float | None):
        return value if self.exact_coords else coarse(value)

    @field_serializer("distance_km")
    def _ser_distance(self, value: float | None):
        return round_distance(value)


class DogPrivateOut(DogOut):
    """Coordenadas exactas: solo para el dueño del perro y los admins."""

    exact_coords: ClassVar[bool] = True
    # Reglas de negocio (services/reglas.py): retención para revisión y resguardo de perros encontrados
    review: dict | None = None  # {status: en_revision|rechazado, reason, label, terms, message, since}
    found_hold: dict | None = None  # {active, until, missing[], message, ...}


# ---------------------------------------------------------------- Matches
CONTACT_VISIBLE_STATUSES = ("approved", "completed")


class MatchUserOut(ORM):
    id: int
    full_name: str
    email: str | None = None  # null hasta que se aprueba la solicitud
    phone: str | None = None  # null hasta que se aprueba la solicitud
    avatar_url: str | None = None
    contact_visible: bool = False


class MatchDogOut(ORM):
    id: int
    name: str
    breed: str | None = None
    size: str | None = None
    photos: list
    status: str
    owner_id: int
    city: str | None = None


class MatchOut(ORM):
    id: int
    user_id: int
    dog_id: int
    status: str
    created_at: datetime
    user: MatchUserOut
    dog: MatchDogOut
    conversation_id: int | None = None
    has_application: bool = False
    compatibility: int | None = None

    @model_validator(mode="after")
    def _gate_contact(self):
        """El correo y el teléfono del solicitante solo se muestran cuando se aprueba la solicitud."""
        visible = self.status in CONTACT_VISIBLE_STATUSES
        self.user.contact_visible = visible
        if not visible:
            self.user.email = None
            self.user.phone = None
        return self


class AdoptionApplicationCreate(BaseModel):
    answers: dict[str, Any]


class AdoptionApplicationOut(ORM):
    id: int
    match_id: int
    answers: dict
    status: str
    created_at: datetime
    compatibility: int | None = None


class ConversationOut(ORM):
    id: int
    match_id: int | None = None
    lost_report_id: int | None = None
    created_at: datetime


class LastMessageOut(BaseModel):
    content: str
    created_at: datetime
    sender_id: int


class ConversationSummary(BaseModel):
    id: int
    match_id: int | None = None
    lost_report_id: int | None = None
    title: str
    photo: str | None = None
    other_user: UserMini | None = None
    last_message: LastMessageOut | None = None
    unread_count: int = 0
    created_at: datetime


class MessageCreate(BaseModel):
    content: str


class MessageOut(ORM):
    id: int
    conversation_id: int
    sender_id: int
    content: str
    is_read: bool
    created_at: datetime


class NotificationOut(ORM):
    id: int
    user_id: int
    type: str
    title: str
    body: str
    data: dict | None = None
    is_read: bool
    created_at: datetime


# ---------------------------------------------------------------- Refugios
class RefugeCreate(BaseModel):
    name: str
    description: str | None = None
    city: str | None = None
    country: str | None = None
    documents: list[str] | None = None
    # Casilla separada (sin marcar) del anexo de aliados: queda en la bitácora de aceptaciones (método "anexo")
    accepted_annex: bool = False


class RefugeOut(ORM):
    id: int
    user_id: int
    name: str
    description: str | None = None
    city: str | None = None
    country: str | None = None
    status: str
    rescued_count: int
    adopted_count: int
    foster_count: int
    points: int
    created_at: datetime
    seller_payments_ready: bool = False  # tienda: Mercado Pago vinculado (y RFC en producción) o pagos simulados
    donations_ready: bool = False  # donativos: Mercado Pago vinculado (sin exigir RFC) o respaldo de la plataforma
    is_donataria: bool = False  # autodeclarado en sus datos fiscales: define el aviso «no es deducible»


class RefugePrivateOut(RefugeOut):
    """Incluye los documentos (ids privados o rutas antiguas /uploads/...): solo responsable y admins."""

    documents: list = []


class RefugeAction(BaseModel):
    description: str | None = None


class PointLogOut(ORM):
    id: int
    refuge_id: int
    action: str
    points: int
    description: str | None = None
    created_at: datetime


class RefugeStats(BaseModel):
    refuge: RefugeOut
    dogs_by_status: dict[str, int]
    total_dogs: int
    pending_applications: int
    donations_total: Decimal
    donations_count: int


# ---------------------------------------------------------------- Tienda
_RFC_FISICA_RE = _re_shop.compile(r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$")
_RFC_MORAL_RE = _re_shop.compile(r"^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$")
# Claves c_RegimenFiscal del SAT por tipo de persona (catálogo CFDI 4.0)
REGIMENES_FISICA = ("605", "606", "607", "608", "610", "611", "612", "614", "615", "616", "621", "625", "626")
REGIMENES_MORAL = ("601", "603", "607", "609", "610", "620", "622", "623", "624", "626")
USOS_CFDI = ("G01", "G02", "G03", "I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "D01", "D02", "D03", "D04",
             "D05", "D06", "D07", "D08", "D09", "D10", "S01", "CP01")
ORDER_STATUSES = ("pending_payment", "paid", "preparing", "shipped", "delivered", "completed", "cancelled", "expired",
                  "return_requested", "return_approved", "return_rejected", "refunded", "refund_pending",
                  "amount_mismatch")


def rfc_person_type(rfc: str | None) -> str | None:
    """"fisica" (13 caracteres), "moral" (12) o None si el RFC no tiene un formato válido."""
    value = (rfc or "").strip().upper()
    if _RFC_FISICA_RE.match(value):
        return "fisica"
    if _RFC_MORAL_RE.match(value):
        return "moral"
    return None


def _clean_rfc(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().upper().replace(" ", "").replace("-", "")
    if not rfc_person_type(value):
        raise ValueError("El RFC no es válido: 13 caracteres para persona física o 12 para persona moral.")
    return value


ShopRfc = Annotated[str, AfterValidator(_clean_rfc)]


def _clean_states(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    from app.data.estados_mx import normalize_state

    out = []
    for raw in value:
        state = normalize_state(raw)
        if not state:
            raise ValueError(f"No reconocemos el estado «{raw}».")
        if state not in out:
            out.append(state)
    return out


class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal
    stock: int | None = 0
    photos: PhotoList | None = None
    shipping_cost: Decimal = Field(Decimal("0"), ge=0, le=100000)  # 0 = envío gratis
    ships_nationwide: bool = True
    ships_states: list[str] | None = Field(None, max_length=32)  # estados que cubre si no envía a todo el país
    handling_days: int = Field(3, ge=0, le=60)  # días hábiles para despachar
    # Obligatorios (consumidor-ecommerce-04 y 12): el backend responde 400 con un mensaje claro si faltan
    category: str | None = Field(None, max_length=40)  # services/reglas.PRODUCT_CATEGORIES
    warranty_text: str | None = Field(None, max_length=2000)  # póliza o "Sin garantía adicional"
    warranty_days: int | None = Field(None, ge=0, le=3650)  # si hay garantía: 90 días o más (LFPC art. 77)
    is_perishable: bool = False  # perecedero: no admite revocación (LFPC art. 51); se avisa antes de pagar
    # Casilla separada (sin marcar) del anexo de aliados: queda en la bitácora de aceptaciones (método "anexo")
    accepted_annex: bool = False

    @model_validator(mode="after")
    def _shipping(self):
        self.ships_states = _clean_states(self.ships_states)
        if not self.ships_nationwide and not self.ships_states:
            raise ValueError("Elige al menos un estado al que envías o marca «Envío a todo el país».")
        return self


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    stock: int | None = None
    photos: PhotoList | None = None
    is_active: bool | None = None
    shipping_cost: Decimal | None = Field(None, ge=0, le=100000)
    ships_nationwide: bool | None = None
    ships_states: list[str] | None = Field(None, max_length=32)
    handling_days: int | None = Field(None, ge=0, le=60)
    category: str | None = Field(None, max_length=40)
    warranty_text: str | None = Field(None, max_length=2000)
    warranty_days: int | None = Field(None, ge=0, le=3650)
    is_perishable: bool | None = None

    @model_validator(mode="after")
    def _shipping(self):
        self.ships_states = _clean_states(self.ships_states)
        return self


class ProductOut(ORM):
    id: int
    refuge_id: int
    name: str
    description: str | None = None
    price: Decimal
    stock: int
    photos: list
    is_active: bool
    is_hidden: bool = False
    created_at: datetime
    shipping_cost: Decimal = Decimal("0")
    ships_nationwide: bool = True
    ships_states: list[str] | None = None
    handling_days: int = 3
    seller_payments_ready: bool = False  # False: se ve pero no se puede comprar ("Este refugio aún no activa cobros")
    refuge_name: str | None = None
    platform_fee_percent: float = 0.0  # comisión de GuauWoow: la ficha dice cuánto recibe el refugio
    category: str | None = None
    category_label: str | None = None
    warranty_text: str | None = None
    warranty_days: int | None = None
    is_perishable: bool = False
    review: dict | None = None  # solo mientras está retenido: {status, reason, label, terms, message, since}


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int


class ShippingAddressIn(BaseModel):
    """Dirección estructurada (también se acepta plana con prefijo shipping_ en OrderCreate)."""

    name: str | None = None
    phone: str | None = None
    street: str | None = None
    ext_number: str | None = None
    int_number: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    references: str | None = None


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(..., max_length=50)
    shipping_address: str | None = Field(None, max_length=1000)  # texto libre (clientes anteriores)
    shipping: ShippingAddressIn | None = None
    shipping_name: str | None = Field(None, max_length=255)
    shipping_phone: str | None = Field(None, max_length=30)
    shipping_street: str | None = Field(None, max_length=255)
    shipping_ext_number: str | None = Field(None, max_length=30)
    shipping_int_number: str | None = Field(None, max_length=30)
    shipping_neighborhood: str | None = Field(None, max_length=255)
    shipping_city: str | None = Field(None, max_length=120)
    shipping_state: str | None = Field(None, max_length=100)
    shipping_postal_code: str | None = Field(None, max_length=10)
    shipping_references: str | None = Field(None, max_length=500)
    # Casillas no premarcadas del checkout (consumidor-ecommerce-05 y 06): el backend exige las dos
    accepted_terms: bool = False
    consent_prepayment: bool = False
    terms_version: str | None = Field(None, max_length=20)  # versión que leyó (debe ser la vigente)

    @model_validator(mode="after")
    def _merge_shipping(self):
        if self.shipping is not None:
            for key, value in self.shipping.model_dump().items():
                if value is not None and getattr(self, f"shipping_{key}") is None:
                    setattr(self, f"shipping_{key}", value)
        for key in ("name", "phone", "street", "ext_number", "int_number", "neighborhood", "city", "state",
                    "postal_code", "references"):
            value = getattr(self, f"shipping_{key}")
            if isinstance(value, str):
                setattr(self, f"shipping_{key}", " ".join(value.split()) or None)
        return self

    def structured_shipping(self) -> dict | None:
        """Campos shipping_* si vino la dirección estructurada; None si solo vino el texto libre."""
        fields = ("shipping_name", "shipping_phone", "shipping_street", "shipping_ext_number", "shipping_int_number",
                  "shipping_neighborhood", "shipping_city", "shipping_state", "shipping_postal_code",
                  "shipping_references")
        data = {f: getattr(self, f) for f in fields}
        return data if any(data.values()) else None


class OrderItemOut(ORM):
    id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    product: ProductOut


class TimelineEntry(BaseModel):
    status: str
    at: str
    note: str | None = None
    by: str | None = None


class OrderOut(ORM):
    id: int
    user_id: int
    refuge_id: int | None = None
    refuge_name: str | None = None
    subtotal: Decimal | None = None
    shipping_total: Decimal = Decimal("0")
    total: Decimal
    fee_percent: Decimal | None = None  # comisión de GuauWoow (transparencia: consumidor-ecommerce-17)
    fee_amount: Decimal = Decimal("0")
    shipping_address: str
    shipping_name: str | None = None
    shipping_phone: str | None = None
    shipping_street: str | None = None
    shipping_ext_number: str | None = None
    shipping_int_number: str | None = None
    shipping_neighborhood: str | None = None
    shipping_city: str | None = None
    shipping_state: str | None = None
    shipping_postal_code: str | None = None
    shipping_references: str | None = None
    status: str
    payment_mode: str | None = None
    paid_at: datetime | None = None
    carrier: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    preparing_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    cancel_note: str | None = None  # causa registrada cuando cancela el refugio o el equipo
    return_reason: str | None = None
    return_details: str | None = None
    return_photos: list | None = None
    return_requested_at: datetime | None = None
    return_decided_at: datetime | None = None
    return_decision_note: str | None = None
    refund_amount: Decimal | None = None  # total reembolsado (suma de reembolsos parciales)
    refund_status: str | None = None
    refunded_at: datetime | None = None
    created_at: datetime
    items: list[OrderItemOut]
    checkout_url: str | None = None  # link de Mercado Pago para terminar el pago (solo pendiente y vigente)
    dispatch_due_at: datetime | None = None  # el refugio debe enviarlo antes de esta fecha (pagado / preparando)
    terms_version: str | None = None
    terms_accepted_at: datetime | None = None
    timeline: list[TimelineEntry] | None = []  # null en pedidos anteriores al historial: se devuelve []
    # Calculados por el router
    status_label: str | None = None
    can_cancel: bool = False
    can_confirm_delivery: bool = False
    can_return: bool = False
    revocation_until: datetime | None = None  # 5 días hábiles desde la entrega (LFPC art. 56)
    claim_until: datetime | None = None  # reclamación por defecto o no correspondencia (LFPC art. 93)
    invoice_status: str | None = None  # None | requested | issued | rejected
    # Bonificación de LFPC art. 92 Ter (reclamación por defecto o no corresponde): a cargo del refugio vendedor
    bonus_info: dict | None = None

    @field_serializer("timeline")
    def _ser_timeline(self, value):
        return [e.model_dump() if isinstance(e, BaseModel) else e for e in (value or [])]


class OrderCheckoutOut(OrderOut):
    checkout_url: str | None = None
    simulated: bool = False


class AdminOrderOut(OrderOut):
    provider: str | None = None
    provider_payment_id: str | None = None
    paid_amount: Decimal | None = None
    review_note: str | None = None
    user: UserMini | None = None
    collector_id: str | None = None
    isr_retenido: Decimal = Decimal("0")
    iva_retenido: Decimal = Decimal("0")
    net_amount: Decimal | None = None
    refund_id: str | None = None
    # Evidencia de la aceptación de las condiciones de compra (consumidor-ecommerce-05 y 06)
    terms_hash: str | None = None
    consent_prepayment_at: datetime | None = None
    terms_ip: str | None = None
    terms_user_agent: str | None = None


class RefugeOrderOut(BaseModel):
    """Pedido visto por el refugio que vende (solo sus productos)."""

    id: int
    status: str
    status_label: str | None = None
    total: Decimal
    subtotal: Decimal | None = None
    shipping_total: Decimal = Decimal("0")
    fee_amount: Decimal = Decimal("0")
    isr_retenido: Decimal = Decimal("0")
    iva_retenido: Decimal = Decimal("0")
    net_amount: Decimal | None = None
    buyer_name: str | None = None
    shipping_address: str
    shipping_name: str | None = None
    shipping_phone: str | None = None
    shipping_street: str | None = None
    shipping_ext_number: str | None = None
    shipping_int_number: str | None = None
    shipping_neighborhood: str | None = None
    shipping_city: str | None = None
    shipping_state: str | None = None
    shipping_postal_code: str | None = None
    shipping_references: str | None = None
    items: list[OrderItemOut]
    carrier: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    paid_at: datetime | None = None
    preparing_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    return_reason: str | None = None
    return_details: str | None = None
    return_photos: list | None = None
    return_requested_at: datetime | None = None
    return_decided_at: datetime | None = None
    return_decision_note: str | None = None
    refund_amount: Decimal | None = None
    refund_status: str | None = None  # ... | error | insufficient_funds (falta saldo en tu Mercado Pago)
    cancel_reason: str | None = None
    cancel_note: str | None = None
    dispatch_due_at: datetime | None = None  # envíalo antes de esta fecha
    dispatch_cancel_at: datetime | None = None  # si no, se cancela y reembolsa solo en esta fecha
    can_cancel: bool = False  # pagado y sin enviar: puedes cancelarlo con un motivo
    can_retry_refund: bool = False  # devolución aprobada con el reembolso pendiente
    timeline: list = []
    invoice: dict | None = None  # solicitud de factura del comprador (datos fiscales y estado)
    created_at: datetime


class OrderCancelRequest(BaseModel):
    """Cancelación por el refugio o el equipo: solo por una causa objetiva que queda registrada."""

    reason: Literal["sin_inventario", "no_puedo_enviar", "direccion_invalida", "sospecha_fraude", "otro"]
    note: str = Field(..., min_length=10, max_length=1000)


class RefugeOrderUpdate(BaseModel):
    status: str = Field(..., pattern="^(preparing|shipped|delivered)$")
    carrier: str | None = Field(None, max_length=100)
    tracking_number: str | None = Field(None, max_length=100)
    tracking_url: str | None = Field(None, max_length=500, pattern=r"^https?://\S+$")


class OrderReturnRequest(BaseModel):
    reason: Literal["defectuoso", "no_corresponde", "no_llego", "arrepentimiento", "otro"]
    details: str | None = Field(None, max_length=2000)
    photos: PhotoList = []


class ReturnDecisionRequest(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=2000)


class AdminRefundRequest(BaseModel):
    amount: Decimal | None = Field(None, gt=0)  # vacío = reembolso total
    # Partidas del pedido que se reembolsan por defecto o porque no corresponden (base de la bonificación de 20 %)
    item_ids: list[int] | None = Field(None, max_length=100)


class PaymentResolveRequest(BaseModel):
    """Decisión de un admin sobre un pago en revisión (monto distinto, reembolso pendiente)."""

    action: str = Field(..., pattern="^(mark_paid|refund)$")
    notes: str | None = Field(None, max_length=1000)


class DonationCreate(BaseModel):
    refuge_id: int
    amount: Decimal = Field(..., ge=10)
    share_name: bool = False  # True = el refugio puede ver tu nombre; si no, "Donante anónimo"
    # Casilla «Leí la Política de donativos»: si se marca, queda en la bitácora de aceptaciones (K-ACEPT)
    accepted_policy: bool = False


class DonationCheckoutOut(BaseModel):
    donation_id: int
    status: str
    checkout_url: str | None = None
    simulated: bool = False
    deducible: bool | None = None  # el refugio declara ser donataria autorizada
    aviso_fiscal: str | None = None  # «no es deducible» o cómo pedir el CFDI de donativo


class DonationOut(ORM):
    id: int
    user_id: int
    refuge_id: int
    amount: Decimal
    status: str
    provider: str | None = None
    provider_payment_id: str | None = None
    share_name: bool = False
    payment_mode: str | None = None
    fee_amount: Decimal = Decimal("0")
    net_amount: Decimal | None = None
    created_at: datetime


class AdminDonationOut(DonationOut):
    user: UserMini | None = None
    refuge_name: str | None = None
    paid_amount: Decimal | None = None
    review_note: str | None = None


# ---------------------------------------------------------------- Mercado Pago (vinculación) y fiscal
class PaymentConnectOut(BaseModel):
    url: str


class SellerPaymentsStatusOut(BaseModel):
    connected: bool
    ready: bool = False  # se le puede comprar hoy (incluye pagos simulados en desarrollo)
    simulated: bool = False
    marketplace_configured: bool = False
    mp_user_id: str | None = None
    connected_at: datetime | None = None
    expires_at: datetime | None = None
    status: str = "not_connected"
    last_error: str | None = None
    fee_percent: float
    donation_fee_percent: float
    fiscal_profile_complete: bool = False


class RefugeFiscalUpdate(BaseModel):
    person_type: Literal["fisica", "moral"] | None = None
    rfc: str | None = Field(None, max_length=13)
    legal_name: str | None = Field(None, min_length=3, max_length=255)
    regimen_fiscal: str | None = Field(None, pattern=r"^\d{3}$")
    postal_code: str | None = Field(None, pattern=r"^\d{5}$")
    is_donataria: bool | None = None
    csf_document_id: str | None = Field(None, max_length=64)


class RefugeFiscalOut(ORM):
    person_type: str
    rfc: str
    legal_name: str
    regimen_fiscal: str
    postal_code: str
    is_donataria: bool = False
    csf_document_id: str | None = None
    updated_at: datetime | None = None


class InvoiceRequestIn(BaseModel):
    rfc: ShopRfc
    legal_name: str = Field(..., min_length=3, max_length=255)
    regimen_fiscal: str = Field(..., pattern=r"^\d{3}$")
    postal_code: str = Field(..., pattern=r"^\d{5}$")
    uso_cfdi: str = Field(..., pattern=r"^[A-Z]{1,2}\d{2}$")
    email: str = Field(..., min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @model_validator(mode="after")
    def _check(self):
        self.legal_name = " ".join(self.legal_name.upper().split())
        if self.uso_cfdi not in USOS_CFDI:
            raise ValueError("El uso de CFDI no es una clave válida del catálogo del SAT.")
        valid = REGIMENES_FISICA if rfc_person_type(self.rfc) == "fisica" else REGIMENES_MORAL
        if self.regimen_fiscal not in valid:
            raise ValueError("El régimen fiscal no corresponde al tipo de RFC.")
        return self


class InvoiceIssueIn(BaseModel):
    status: Literal["issued", "rejected"]
    uuid: str | None = Field(None, pattern=r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
    xml_document_id: str | None = Field(None, max_length=64)
    pdf_document_id: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=1000)


class InvoiceOut(BaseModel):
    order_id: int
    status: str  # requested | issued | rejected
    rfc: str
    legal_name: str
    regimen_fiscal: str
    postal_code: str
    uso_cfdi: str
    email: str
    uuid: str | None = None
    note: str | None = None
    requested_at: datetime
    issued_at: datetime | None = None
    xml_url: str | None = None
    pdf_url: str | None = None


class CfdiOut(ORM):
    id: int
    kind: str
    period: str
    refuge_id: int
    refuge_name: str | None = None
    uuid: str | None = None
    status: str
    subtotal: Decimal
    iva: Decimal
    isr_retenido: Decimal
    iva_retenido: Decimal
    total: Decimal
    error: str | None = None
    attempts: int = 0
    issued_at: datetime | None = None
    created_at: datetime
    has_xml: bool = False
    has_pdf: bool = False


# ---------------------------------------------------------------- Perdidos / encontrados
class LostReportCreate(BaseModel):
    dog_name: str
    report_type: str = "lost"  # lost | found
    description: str | None = None
    city: str | None = None
    state: str | None = Field(None, max_length=100)  # estado de México (del geocodificador de la app); si falta se deduce
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photos: PhotoList | None = None


class LostReportUpdate(BaseModel):
    status: str


class LostReportOut(ORM):
    id: int
    reporter_id: int | None = None
    reporter: UserMini | None = None
    dog_name: str
    report_type: str
    description: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photos: list
    status: str
    source: str = "app"
    distance_km: float | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    # ai_analysis y photo_signature no se exponen: son JSON pesados que solo usa el matching
    is_hidden: bool = False
    # Contenido importado (fuentes facebook | volunteer): enlace a la publicación original y su fecha, para la
    # etiqueta con atribución. En los demás reportes external_url no se expone (solo admins).
    external_url: str | None = None
    external_posted_at: datetime | None = None
    # «Importado de una publicación pública; su autor no es usuario de GuauWoow» (contrato L-fb)
    import_notice: str | None = None

    # Público: coordenadas aproximadas (~1 km). LostReportPrivateOut (quien reporta y admins) las da exactas.
    exact_coords: ClassVar[bool] = False
    all_external_urls: ClassVar[bool] = False

    @field_serializer("latitude", "longitude")
    def _ser_coord(self, value: float | None):
        return value if self.exact_coords else coarse(value)

    @field_serializer("external_url")
    def _ser_external_url(self, value: str | None):
        return value if self.all_external_urls or self.source in ("facebook", "volunteer") else None

    @field_serializer("distance_km")
    def _ser_distance(self, value: float | None):
        return round_distance(value)


class LostReportPrivateOut(LostReportOut):
    """Coordenadas exactas: solo para quien reporta y los admins."""

    exact_coords: ClassVar[bool] = True


class LostReportAdminOut(LostReportPrivateOut):
    contact_phone: str | None = None
    all_external_urls: ClassVar[bool] = True


class MatchCandidate(BaseModel):
    type: str  # lost | found | adoption
    id: int
    name: str
    city: str | None = None
    photos: list
    score: int
    distance_km: float | None = None

    @field_serializer("distance_km")
    def _ser_distance(self, value: float | None):
        return round_distance(value)


class PhotoSearchOut(BaseModel):
    analysis: dict | None = None
    matches: list[MatchCandidate]


# ---------------------------------------------------------------- Casas de paso / recordatorios
class FosterHomeCreate(BaseModel):
    description: str | None = None
    city: str | None = None
    country: str | None = None
    capacity: int | None = 1
    # Casilla separada (sin marcar) del anexo de aliados: queda en la bitácora de aceptaciones (método "anexo")
    accepted_annex: bool = False


class FosterHomeOut(ORM):
    id: int
    user_id: int
    description: str | None = None
    city: str | None = None
    country: str | None = None
    capacity: int
    status: str
    created_at: datetime


class ReminderCreate(BaseModel):
    match_id: int
    title: str
    due_date: datetime
    type: str


class ReminderOut(ORM):
    id: int
    user_id: int
    match_id: int
    title: str
    due_date: datetime
    type: str
    is_completed: bool
    created_at: datetime


# ---------------------------------------------------------------- Moderación
ReportTargetType = Literal["dog", "lost_report", "user", "refuge", "product", "message", "veterinary", "veterinary_review"]
# Catálogo y etiquetas en services/legal_moderation.REASONS (moderacion.html §1, proteccion-nna.html §7).
# honor_reputacion ... publicidad_enganosa los pide la política de reseñas y clínicas (gap-veterinarias-y-resenas 13 y 16);
# las siete categorías del Decreto NNA (art. 3), involucra_menor y abuso_sexual_infantil van primero en la cola.
ReportReason = Literal[
    "spam", "fraude", "maltrato", "contenido_inapropiado", "datos_falsos", "otro",
    "honor_reputacion", "resena_falsa", "datos_personales", "cedula_falsa", "condiciones_sanitarias", "publicidad_enganosa",
    "involucra_menor", "abuso_sexual_infantil", "acoso", "abuso_sexual", "odio_violencia_masiva",
    "incitacion_odio_violencia", "conductas_ilicitas", "pornografia", "suicidio_autolesiones", "contenido_intimo",
    "venta_animal", "mi_imagen", "difamacion", "suplantacion",
]


class ContentReportCreate(BaseModel):
    target_type: ReportTargetType
    target_id: int
    reason: ReportReason
    details: str | None = Field(None, max_length=1000)


class ContentReportOut(ORM):
    id: int
    status: str
    target_type: str
    target_id: int
    reason: str
    created_at: datetime


class ContentReportResolve(BaseModel):
    status: Literal["resolved", "dismissed"]
    # quarantine: material de abuso sexual infantil (services/legal_moderation.quarantine)
    action: Literal["hide_content", "suspend_user", "quarantine"] | None = None
    notes: str | None = Field(None, max_length=2000)
    rule: ReportReason | None = None  # regla aplicada si no es el motivo del reporte (va en el aviso a la persona)


class ContentReportAdminOut(ContentReportOut):
    details: str | None = None
    action: str | None = None
    admin_notes: str | None = None
    resolved_at: datetime | None = None
    reporter: dict | None = None  # {id, full_name, email}
    resolved_by: dict | None = None  # {id, full_name}
    target: dict | None = None  # resumen corto del contenido reportado
    open_reports_for_target: int = 0
    source: str = "app"  # app | publico | equipo
    priority: int = 3  # 0 menores · 1 urgente · 2 estafa/venta · 3 resto
    due_at: datetime | None = None
    auto_hidden: bool = False
    folio: str | None = None
    contact_email: str | None = None
    target_url: str | None = None


# ---------------------------------------------------------------- Admin
class AdminStats(BaseModel):
    total_users: int
    total_dogs: int
    pending_matches: int
    pending_refuges: int
    total_products: int
    total_lost_reports: int


class UserRoleUpdate(BaseModel):
    role: str


class UserActiveUpdate(BaseModel):
    is_active: bool


class AdminAuditLogOut(ORM):
    id: int
    actor_id: int | None = None
    actor_email: str | None = None
    actor_name: str | None = None
    action: str
    target_type: str
    target_id: int | None = None
    details: dict[str, Any] | None = None
    ip: str | None = None
    created_at: datetime


class MatchWithApplicationOut(ORM):
    id: int
    user_id: int
    dog_id: int
    status: str
    created_at: datetime
    user: MatchUserOut
    dog: MatchDogOut
    application: AdoptionApplicationOut | None = None

    @model_validator(mode="after")
    def _admin_contact(self):
        self.user.contact_visible = True  # vista de admins: contacto completo
        return self


class BotInteractionOut(ORM):
    id: int
    phone: str
    stage: str
    data: dict
    last_message: str | None = None
    created_at: datetime
    updated_at: datetime


class WhatsappWebhookPayload(BaseModel):
    """Formato simple usado por el simulador del panel de administración."""

    phone: str
    message: str | None = None
    media_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class WhatsappBotResponse(BaseModel):
    phone: str
    stage: str
    response: str
    buttons: list[dict] | None = None


class FacebookGroupCreate(BaseModel):
    name: str
    url: str
    page_id: str | None = None
    kind: str | None = None  # page | manual (por defecto: page si hay page_id)
    city: str | None = None


class FacebookGroupOut(ORM):
    id: int
    name: str
    url: str
    page_id: str | None = None
    kind: str = "manual"  # page | manual | group
    city: str | None = None
    is_active: bool
    last_scraped: datetime | None = None
    created_at: datetime
    # Grupos públicos (kind="group")
    state: str | None = None
    group_url: str | None = None
    provider: str | None = None
    provider_ref: str | None = None
    last_fetched_at: datetime | None = None
    last_attempt_at: datetime | None = None  # último intento (también con error)
    last_post_at: datetime | None = None
    posts_fetched_total: int = 0
    reports_created_total: int = 0
    cost_estimate_total: float = 0.0  # USD estimados
    last_error: str | None = None


class FacebookPublicGroupCreate(BaseModel):
    """Alta de un grupo público de Facebook (kind="group") desde el panel."""

    name: str = Field(..., min_length=2, max_length=255)
    state: str = Field(..., max_length=100)  # se normaliza al nombre oficial del estado
    city: str | None = Field(None, max_length=100)
    group_url: str = Field(..., max_length=500)  # https://www.facebook.com/groups/<id o alias>
    is_active: bool = True


class FacebookGroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    state: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    group_url: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class FacebookImportRequest(BaseModel):
    post_url: str | None = None
    text: str = ""
    image_urls: list[str] = []
    report_type: str = "found"
    city: str | None = None
    state: str | None = Field(None, max_length=100)


class VolunteerImportRequest(BaseModel):
    """Publicación de Facebook que comparte un voluntario (botón de compartir o marcador)."""

    url: str = Field(..., max_length=1000)
    text: str = Field("", max_length=5000)
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=100)
    report_type: Literal["lost", "found"] | None = None  # si falta se deduce del texto
    photos: Annotated[list[UploadUrl], Field(max_length=5)] = []  # subidas propias (POST /upload)
    # Leyenda de aceptación del voluntario (obligatoria): se guarda con la fecha y la versión de los términos
    consent: bool = False


class AuthorRemovalRequest(BaseModel):
    """«Soy el autor: retirar» de una publicación importada de Facebook, sin cuenta."""

    report_id: int | None = None
    url: str | None = Field(None, max_length=1000)  # enlace a la publicación original (si no se sabe el reporte)
    relation: Literal["autor", "aparezco", "otro"] = "autor"
    email: str = Field(..., min_length=5, max_length=255)  # para responder la solicitud
    details: str | None = Field(None, max_length=1000)


# ---------------------------------------------------------------- Veterinarias
import re as _re  # noqa: E402

HOURS_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME_RE = _re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CEDULA_RE = _re.compile(r"^[0-9]{5,10}$")
_VISITED_RE = _re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
VETERINARY_STATUSES = ("pending", "verified", "rejected")


class VeterinaryHoursRange(BaseModel):
    open: str = Field(..., pattern=_TIME_RE.pattern)  # "09:00"
    close: str = Field(..., pattern=_TIME_RE.pattern)  # "18:00"; menor que open = cierra pasada la medianoche


def _clean_hours(value: dict | None) -> dict:
    """Solo días conocidos; cada día es una lista (vacía = cerrado) de rangos {open, close}."""
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("El horario debe ser un objeto con los días mon..sun.")
    out = {}
    for day, ranges in value.items():
        if day not in HOURS_DAYS:
            raise ValueError(f"Día de horario no válido: {day}. Usa mon, tue, wed, thu, fri, sat o sun.")
        if ranges is None:
            ranges = []
        if not isinstance(ranges, list) or len(ranges) > 4:
            raise ValueError("Cada día admite hasta 4 rangos de horario.")
        out[day] = [VeterinaryHoursRange.model_validate(r).model_dump() for r in ranges]
    return out


def _clean_services(value: list | None) -> list[str]:
    out = []
    for item in value or []:
        item = " ".join(str(item or "").split())
        if not item:
            continue
        if len(item) > 60:
            raise ValueError("Cada servicio debe tener máximo 60 caracteres.")
        if item.lower() not in {s.lower() for s in out}:
            out.append(item)
    if len(out) > 20:
        raise ValueError("Puedes registrar máximo 20 servicios.")
    return out


def _clean_website(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if not value.lower().startswith(("http://", "https://")):
        value = "https://" + value
    if len(value) > 500 or " " in value:
        raise ValueError("El sitio web no es una dirección válida.")
    return value


class VeterinaryBase(BaseModel):
    description: str | None = Field(None, max_length=2000)
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, pattern=r"^\d{5}$")
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    phone: str | None = Field(None, max_length=30)
    whatsapp: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=255)
    website: str | None = None
    hours: dict[str, list[VeterinaryHoursRange]] | None = None
    services: list[str] | None = None
    emergency_24h: bool | None = None
    photos: PhotoList | None = None
    cedula_institution: str | None = Field(None, max_length=255)
    cedula_document_id: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def _normalize(self):
        # Solo se normaliza lo que se envió: asignar un campo lo marca como enviado y rompería el PATCH
        # (model_dump(exclude_unset=True))
        sent = self.model_fields_set
        if "hours" in sent and self.hours is not None:
            cleaned = _clean_hours({k: [r.model_dump() for r in v] for k, v in self.hours.items()})
            self.hours = {k: [VeterinaryHoursRange(**r) for r in v] for k, v in cleaned.items()}
        if "services" in sent and self.services is not None:
            self.services = _clean_services(self.services)
        if "website" in sent:
            self.website = _clean_website(self.website)
        return self


class VeterinaryCreate(VeterinaryBase):
    name: str = Field(..., min_length=3, max_length=255)
    responsible_vet_name: str = Field(..., min_length=3, max_length=255)
    cedula_profesional: str = Field(..., pattern=_CEDULA_RE.pattern)
    hours: dict[str, list[VeterinaryHoursRange]] = {}
    services: list[str] = []
    emergency_24h: bool = False
    photos: PhotoList = []
    # Casilla obligatoria del formulario: datos verdaderos, autorización del responsable y publicación de su
    # nombre, cédula e institución. Se guarda con fecha y versión de los Términos (consent_at).
    consent: bool = False
    # Casilla separada (sin marcar) del anexo de aliados: queda en la bitácora de aceptaciones (método "anexo")
    accepted_annex: bool = False


class VeterinaryUpdate(VeterinaryBase):
    name: str | None = Field(None, min_length=3, max_length=255)
    responsible_vet_name: str | None = Field(None, min_length=3, max_length=255)
    cedula_profesional: str | None = Field(None, pattern=_CEDULA_RE.pattern)


class VeterinaryOut(ORM):
    """Perfil público de una clínica (coordenadas exactas: la dirección del negocio es pública)."""

    id: int
    is_owner: bool = False  # la clínica es de quien consulta (en lugar de exponer owner_user_id)
    name: str
    description: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    website: str | None = None
    hours: dict = {}
    services: list = []
    emergency_24h: bool = False
    photos: list = []
    responsible_vet_name: str
    cedula_profesional: str
    cedula_institution: str | None = None
    status: str
    is_hidden: bool = False
    verified_at: datetime | None = None
    verification_expires_at: datetime | None = None
    google_linked: bool = False  # hay place_id (el contenido de Google se pide en tiempo real)
    google_maps_url: str | None = None
    rating_avg: float | None = None
    rating_count: int = 0
    distance_km: float | None = None
    open_now: bool | None = None
    badge_text: str | None = None  # texto fijo de la insignia "Cédula verificada" (solo si está verificada)
    verified_label: str | None = None  # "Cédula consultada en el Registro Nacional de Profesionistas el ..."
    created_at: datetime

    @field_serializer("distance_km")
    def _ser_distance(self, value: float | None):
        return round_distance(value)


class VeterinaryPrivateOut(VeterinaryOut):
    """Para la clínica dueña y los admins: documento de la cédula, motivo de rechazo y place_id."""

    owner_user_id: int
    cedula_document_id: str | None = None
    # La imagen de la cédula verificada se borró (30 días después de la decisión); queda la constancia
    cedula_document_purged_at: datetime | None = None
    cedula_carrera: str | None = None
    consent_at: datetime | None = None
    consent_terms_version: str | None = None
    rejection_note: str | None = None
    google_place_id: str | None = None
    google_place_checked_at: datetime | None = None
    updated_at: datetime | None = None


class VeterinaryAdminOut(VeterinaryPrivateOut):
    owner: UserMini | None = None
    owner_email: str | None = None
    verified_by_id: int | None = None
    verification_evidence_document_id: str | None = None  # captura privada del cotejo en el RNP
    unpublished_at: datetime | None = None


class VeterinaryReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    text: str | None = Field(None, max_length=1000)
    visited_month: str | None = Field(None, pattern=_VISITED_RE.pattern)  # "2026-03"
    incentivized: bool = False  # recibió descuento o regalo por reseñar (se etiqueta "Reseña incentivada")


class VeterinaryReviewReply(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class ReviewAuthorOut(BaseModel):
    """Autor público de una reseña: nombre abreviado ("Ana G.") y foto, sin id de cuenta."""

    full_name: str
    avatar_url: str | None = None


class VeterinaryReviewOut(ORM):
    id: int
    veterinary_id: int
    mine: bool = False  # la escribió quien consulta (en lugar de exponer user_id)
    user: ReviewAuthorOut | None = None  # full_name viene abreviado ("Ana G."): nunca teléfono ni correo
    author_name: str | None = None
    rating: int
    text: str | None = None
    visited_month: str | None = None
    incentivized: bool = False  # la app la etiqueta "Reseña incentivada"
    owner_reply: str | None = None
    owner_reply_at: datetime | None = None
    clarification: str | None = None  # aclaración publicada sin comentarios (solicitud aprobada)
    clarification_at: datetime | None = None
    is_hidden: bool = False  # para su autor: True = en revisión u oculta por moderación
    created_at: datetime
    updated_at: datetime | None = None


class VeterinaryReviewAdminOut(VeterinaryReviewOut):
    user_id: int
    veterinary_name: str | None = None
    user_email: str | None = None


class GoogleReviewOut(BaseModel):
    """Una reseña de Google tal como llega (sin recortar ni reordenar); nunca se guarda."""

    author_name: str | None = None
    author_url: str | None = None
    profile_photo_url: str | None = None
    rating: int | None = None
    text: str | None = None
    original_text: str | None = None  # distinto de text cuando Google tradujo la reseña
    language: str | None = None
    relative_time: str | None = None
    publish_time: str | None = None
    google_maps_url: str | None = None  # "Ver esta reseña en Google Maps"
    flag_content_url: str | None = None  # "Reportar a Google"


class GoogleBlockOut(BaseModel):
    place_id: str
    available: bool = True  # False: Google no respondió, llave ausente o tope diario alcanzado
    rating: float | None = None
    ratings_total: int | None = None
    reviews: list[GoogleReviewOut] = []
    google_maps_url: str | None = None  # "Ver todas las reseñas en Google Maps"
    attribution: str = "Google Maps"  # texto o logotipo obligatorio (translate="no")
    order_notice: str = ""
    translated_notice: str | None = None  # cuando alguna reseña llegó traducida por Google
    fetched_at: datetime | None = None


class VeterinaryDetailOut(VeterinaryOut):
    reviews: list[VeterinaryReviewOut] = []  # las 10 más recientes visibles
    my_review: VeterinaryReviewOut | None = None  # la reseña propia (aunque esté en revisión)
    google: GoogleBlockOut | None = None  # null: clínica sin ficha de Google o GOOGLE_MAPS_API_KEY vacía
    notices: dict[str, str] = {}  # deslinde, aviso de urgencias, insignia, reseñas y Google (textos fijos)


class GooglePlaceSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)


class GooglePlaceCandidate(BaseModel):
    place_id: str
    name: str | None = None
    address: str | None = None
    rating: float | None = None
    ratings_total: int | None = None


class GooglePlaceLinkRequest(BaseModel):
    place_id: str | None = Field(None, max_length=255)  # null = desvincular


class VeterinaryRejectPayload(BaseModel):
    note: str = Field(..., min_length=3, max_length=2000)


class VeterinaryVerifyPayload(BaseModel):
    """Evidencia del cotejo (gap-veterinarias-y-resenas 03 y 16): carrera registrada en el RNP y captura fechada
    (documento privado de POST /upload/document que sube el admin)."""

    carrera: str = Field(..., min_length=3, max_length=255)
    evidence_document_id: str = Field(..., pattern=r"^[0-9a-f]{32}\.(jpg|png|webp|pdf)$")


VETERINARY_REQUEST_KINDS = ("aclaracion", "queja")
VETERINARY_REQUEST_RELATIONS = ("clinica", "aludido", "cliente", "otro")
VETERINARY_REQUEST_REASONS = (
    "honor_reputacion", "resena_falsa", "datos_personales", "cedula_falsa", "condiciones_sanitarias",
    "publicidad_enganosa", "otro",
)
VETERINARY_REQUEST_STATUSES = ("pending", "published", "resolved", "rejected")


class VeterinaryRequestCreate(BaseModel):
    """Solicitud de aclaración o queja sobre una clínica o una reseña. Sin cuenta: nombre y correo obligatorios."""

    kind: Literal["aclaracion", "queja"]
    review_id: int | None = None  # obligatorio para una aclaración
    relation: Literal["clinica", "aludido", "cliente", "otro"]
    reason: Literal["honor_reputacion", "resena_falsa", "datos_personales", "cedula_falsa", "condiciones_sanitarias",
                    "publicidad_enganosa", "otro"] | None = None  # obligatorio para una queja
    name: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=255)
    text: str = Field(..., min_length=10, max_length=2000)
    accept_privacy: bool = False  # aceptó el aviso de privacidad (obligatorio sin cuenta)


class VeterinaryRequestOut(BaseModel):
    id: int
    kind: str
    status: str
    due_at: datetime
    created_at: datetime


class VeterinaryRequestAdminOut(VeterinaryRequestOut):
    veterinary_id: int
    veterinary_name: str | None = None
    review_id: int | None = None
    review_text: str | None = None
    review_clarification: str | None = None
    user_id: int | None = None
    name: str | None = None
    email: str | None = None
    relation: str
    reason: str | None = None
    text: str
    overdue: bool = False
    resolution_note: str | None = None
    resolved_by_id: int | None = None
    resolved_at: datetime | None = None


class VeterinaryRequestResolve(BaseModel):
    """publish: publica la aclaración junto a la reseña (sin comentarios); resolve: atendida (p. ej. se ocultó el
    contenido); reject: no procede. La nota se envía a quien presentó la solicitud."""

    action: Literal["publish", "resolve", "reject"]
    note: str = Field(..., min_length=3, max_length=2000)


# ---------------------------------------------------------------- Centro de solicitudes (/cumplimiento/solicitudes)
SolicitudTipo = Literal["acceso", "rectificacion", "cancelacion", "oposicion", "revocacion", "limitacion", "queja",
                        "aclaracion", "retiro_importado"]
SolicitudPermiso = Literal["alertas", "correos", "whatsapp", "analitica", "publicidad", "otro"]


class SolicitudCreate(BaseModel):
    """Solicitud con o sin cuenta. Sin cuenta: nombre, correo y aceptar el aviso de privacidad."""

    tipo: SolicitudTipo
    nombre: str = Field(..., min_length=3, max_length=120)
    email: str | None = Field(None, max_length=255)  # con sesión iniciada, por defecto el de la cuenta
    telefono: str | None = Field(None, max_length=30)
    descripcion: str = Field(..., min_length=10, max_length=4000)
    report_id: int | None = None  # reporte de GuauWoow relacionado (retiro_importado o el dato a corregir)
    documento_id: str | None = Field(None, max_length=64)  # documento privado subido con POST /upload/document
    enlace: str | None = Field(None, max_length=1000)  # retiro_importado: enlace a la publicación o al reporte
    relacion: Literal["autor", "aparezco", "otro"] | None = None  # retiro_importado
    actua_como: Literal["titular", "representante"] = "titular"
    nombre_titular: str | None = Field(None, max_length=120)  # si actúa en representación de otra persona
    permisos: list[SolicitudPermiso] = Field(default_factory=list, max_length=6)  # revocación / limitación
    alcance: Literal["cuenta", "datos", "whatsapp", "importado"] | None = None  # cancelación
    publicidad: bool = False  # acceso a la información usada para publicidad (LFPC art. 16)
    motivo: Literal["servicio", "compra", "producto_defectuoso", "donativo", "refugio", "otro"] | None = None  # quejas
    pedido_id: int | None = None
    acepta_privacidad: bool = False
    website: str | None = Field(None, max_length=200)  # trampa para bots: debe llegar vacío


class SolicitudAcuse(BaseModel):
    folio: str
    tipo: str
    estado: str
    recibida_en: datetime
    responde_antes_de: datetime
    primera_respuesta_antes_de: datetime | None = None
    requiere_confirmacion: bool = False
    publicacion_oculta: bool | None = None  # retiro_importado
    mensaje: str


class SolicitudConfirmar(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)


class SolicitudAdminAccion(BaseModel):
    accion: Literal["en_revision", "primera_respuesta", "requerir_info", "verificar_identidad", "ampliar", "responder",
                    "hacer_efectiva", "cerrar", "nota"]
    mensaje: str | None = Field(None, max_length=8000)  # lo que se le comunica a la persona
    nota_interna: str | None = Field(None, max_length=4000)
    resultado: Literal["procede", "procede_parcial", "no_procede", "sin_datos"] | None = None
    motivo_negativa: Literal["identidad_no_acreditada", "sin_datos", "derechos_de_terceros", "impedimento_legal",
                             "ya_realizada", "obligacion_legal", "informacion_incompleta", "otro"] | None = None
    pedir_identificacion: bool = False  # requerir_info: además pide subir una identificación
    metodo: Literal["identificacion", "correo", "whatsapp", "cuenta", "otro"] | None = None  # verificar_identidad
    eliminar_cuenta: bool = False  # hacer_efectiva (cancelación): misma anonimización que «Eliminar mi cuenta»
    eliminar_whatsapp: bool = False  # hacer_efectiva (cancelación): conversación del bot y sus reportes


class SolicitudAdminCreate(SolicitudCreate):
    """Solicitud que llegó por correo, por escrito o por teléfono y el equipo registra para darle folio."""

    canal: Literal["correo", "escrito", "telefono", "whatsapp"] = "correo"
    identidad: Literal["identificacion", "whatsapp", "otro"] | None = None  # si ya se comprobó por ese medio


class TransparenciaOptIn(BaseModel):
    """El Refugio acepta (o retira) publicar con su nombre sus cifras de donativos y ventas."""

    publicar: bool
