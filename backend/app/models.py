import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, Float, Numeric, ForeignKey, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _now():
    return datetime.datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    phone_verified = Column(Boolean, default=False, nullable=False)
    phone_otp_hash = Column(String(128), nullable=True)
    phone_otp_expires_at = Column(DateTime, nullable=True)
    avatar_url = Column(String(500), nullable=True)
    role = Column(String(50), default="user", nullable=False)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
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


class Dog(Base):
    __tablename__ = "dogs"

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
    created_at = Column(DateTime, default=_now, nullable=False)

    owner = relationship("User", back_populates="dogs")
    matches = relationship("Match", back_populates="dog")

    # Atributo transitorio (no persistido) que llenan los endpoints con geolocalización
    distance_km = None


class DogPass(Base):
    __tablename__ = "dog_passes"
    __table_args__ = (UniqueConstraint("user_id", "dog_id", name="uq_dog_passes_user_dog"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    dog_id = Column(Integer, ForeignKey("dogs.id"), nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)


class Match(Base):
    __tablename__ = "matches"

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
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
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

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    lost_report_id = Column(Integer, ForeignKey("lost_reports.id"), nullable=True)
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
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="refuges")
    point_logs = relationship("PointLog", back_populates="refuge")
    products = relationship("Product", back_populates="refuge")


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
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer, default=0, nullable=False)
    photos = Column(JSON, default=list, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    refuge = relationship("Refuge", back_populates="products")


class LostReport(Base):
    __tablename__ = "lost_reports"

    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    dog_name = Column(String(255), nullable=False)
    report_type = Column(String(50), default="lost", nullable=False)  # lost | found
    description = Column(Text, nullable=True)
    photos = Column(JSON, default=list, nullable=False)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    status = Column(String(50), default="active", nullable=False)
    source = Column(String(30), default="app", nullable=False)  # app | whatsapp | facebook
    contact_phone = Column(String(50), nullable=True)  # solo visible para admins
    external_url = Column(String(500), nullable=True)  # permalink de Facebook
    ai_analysis = Column(JSON, nullable=True)
    photo_signature = Column(JSON, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    reporter = relationship("User", back_populates="lost_reports")

    distance_km = None


class BotInteraction(Base):
    __tablename__ = "bot_interactions"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(50), nullable=False, index=True)
    stage = Column(String(100), default="welcome", nullable=False)
    data = Column(JSON, default=dict, nullable=False)
    last_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class FacebookGroup(Base):
    """Fuente de Facebook: una Página (Graph API) o una fuente manual (voluntarios)."""

    __tablename__ = "facebook_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    page_id = Column(String(100), nullable=True)
    kind = Column(String(20), default="manual", nullable=False)  # page | manual
    city = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_scraped = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total = Column(Numeric(10, 2), nullable=False)
    shipping_address = Column(Text, nullable=False)
    status = Column(String(50), default="created", nullable=False)
    provider = Column(String(30), nullable=True)
    provider_preference_id = Column(String(255), nullable=True)
    provider_payment_id = Column(String(255), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class Donation(Base):
    __tablename__ = "donations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refuge_id = Column(Integer, ForeignKey("refuges.id"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(30), default="pending", nullable=False)  # pending | approved | rejected
    provider = Column(String(30), nullable=True)
    provider_preference_id = Column(String(255), nullable=True)
    provider_payment_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User")
    refuge = relationship("Refuge")


class FosterHome(Base):
    __tablename__ = "foster_homes"

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
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    title = Column(String(255), nullable=False)
    due_date = Column(DateTime, nullable=False)
    type = Column(String(100), nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="reminders")
    match = relationship("Match")
