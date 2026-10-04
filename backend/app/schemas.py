from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    accepted_terms: bool = False
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
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    avatar_url: str | None = None
    marketing_opt_in: bool | None = None


class UserMini(ORM):
    id: int
    full_name: str
    avatar_url: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str


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
    accepted_terms: bool
    marketing_opt_in: bool | None = None


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
    photos: list[str] | None = None


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
    photos: list[str] | None = None


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
    ai_analysis: dict | None = None


# ---------------------------------------------------------------- Matches
class MatchUserOut(ORM):
    id: int
    full_name: str
    email: str
    phone: str | None = None
    avatar_url: str | None = None


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


class RefugeOut(ORM):
    id: int
    user_id: int
    name: str
    description: str | None = None
    city: str | None = None
    country: str | None = None
    status: str
    documents: list
    rescued_count: int
    adopted_count: int
    foster_count: int
    points: int
    created_at: datetime


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
class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal
    stock: int | None = 0
    photos: list[str] | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    stock: int | None = None
    photos: list[str] | None = None
    is_active: bool | None = None


class ProductOut(ORM):
    id: int
    refuge_id: int
    name: str
    description: str | None = None
    price: Decimal
    stock: int
    photos: list
    is_active: bool
    created_at: datetime


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    items: list[OrderItemCreate]
    shipping_address: str


class OrderItemOut(ORM):
    id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    product: ProductOut


class OrderOut(ORM):
    id: int
    user_id: int
    total: Decimal
    shipping_address: str
    status: str
    created_at: datetime
    items: list[OrderItemOut]


class OrderCheckoutOut(OrderOut):
    checkout_url: str | None = None
    simulated: bool = False


class AdminOrderOut(OrderOut):
    provider: str | None = None
    provider_payment_id: str | None = None
    paid_at: datetime | None = None
    user: UserMini | None = None


class DonationCreate(BaseModel):
    refuge_id: int
    amount: Decimal = Field(..., ge=10)
    share_name: bool = False  # True = el refugio puede ver tu nombre; si no, "Donante anónimo"


class DonationCheckoutOut(BaseModel):
    donation_id: int
    status: str
    checkout_url: str | None = None
    simulated: bool = False


class DonationOut(ORM):
    id: int
    user_id: int
    refuge_id: int
    amount: Decimal
    status: str
    provider: str | None = None
    provider_payment_id: str | None = None
    share_name: bool = False
    created_at: datetime


class AdminDonationOut(DonationOut):
    user: UserMini | None = None
    refuge_name: str | None = None


# ---------------------------------------------------------------- Perdidos / encontrados
class LostReportCreate(BaseModel):
    dog_name: str
    report_type: str = "lost"  # lost | found
    description: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photos: list[str] | None = None


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
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photos: list
    status: str
    source: str = "app"
    distance_km: float | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    ai_analysis: dict | None = None


class LostReportAdminOut(LostReportOut):
    contact_phone: str | None = None
    external_url: str | None = None


class MatchCandidate(BaseModel):
    type: str  # lost | found | adoption
    id: int
    name: str
    city: str | None = None
    photos: list
    score: int
    distance_km: float | None = None


class PhotoSearchOut(BaseModel):
    analysis: dict | None = None
    matches: list[MatchCandidate]


# ---------------------------------------------------------------- Casas de paso / recordatorios
class FosterHomeCreate(BaseModel):
    description: str | None = None
    city: str | None = None
    country: str | None = None
    capacity: int | None = 1


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


class MatchWithApplicationOut(ORM):
    id: int
    user_id: int
    dog_id: int
    status: str
    created_at: datetime
    user: MatchUserOut
    dog: MatchDogOut
    application: AdoptionApplicationOut | None = None


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
    kind: str = "manual"
    city: str | None = None
    is_active: bool
    last_scraped: datetime | None = None
    created_at: datetime


class FacebookImportRequest(BaseModel):
    post_url: str | None = None
    text: str = ""
    image_urls: list[str] = []
    report_type: str = "found"
    city: str | None = None
