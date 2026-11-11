"""Veri modeli. Proje dokümanı bölüm 7'deki tablolar + uygulama tabloları
(kullanıcılar, paketler, abonelikler, işler, API kullanımı, uyumluluk, denetim)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType

# SQLite'ta BIGSERIAL otomatik artmaz; Integer varyantı kullanılır.
BigId = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


CATEGORIES = ("standard", "deluxe", "suite", "family", "other")
CATEGORY_LABELS = {
    "standard": "Standard",
    "deluxe": "Deluxe",
    "suite": "Suite",
    "family": "Family",
    "other": "Diğer",
}


# --------------------------------------------------------------------------- #
# Doküman şeması
# --------------------------------------------------------------------------- #
class Hotel(Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    province: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    district: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    hotel_type: Mapped[str | None] = mapped_column(Text)  # boutique, pension, midscale, resort, chain
    place_id: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    star_rating: Mapped[int | None] = mapped_column(SmallInteger)
    room_count: Mapped[int | None] = mapped_column(Integer)
    is_subscriber: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    room_types: Mapped[list[RoomType]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    settings: Mapped[HotelSettings | None] = relationship(back_populates="hotel", uselist=False, cascade="all, delete-orphan")
    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="hotel", cascade="all, delete-orphan")

    @property
    def active_subscription(self) -> Subscription | None:
        subs = [s for s in self.subscriptions if s.status in ("trial", "active", "past_due")]
        return sorted(subs, key=lambda s: s.started_at, reverse=True)[0] if subs else None


class RoomType(Base):
    __tablename__ = "room_types"
    __table_args__ = (
        UniqueConstraint("hotel_id", "raw_name"),
        CheckConstraint(f"category IN {CATEGORIES}", name="ck_room_category"),
        CheckConstraint("mapped_by IN ('rule','llm','manual')", name="ck_room_mapped_by"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    mapped_by: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    hotel: Mapped[Hotel] = relationship(back_populates="room_types")


class RateSnapshot(Base):
    __tablename__ = "rate_snapshots"
    __table_args__ = (Index("ix_rate_rt_stay_obs", "room_type_id", "stay_date", "observed_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"), nullable=False)
    stay_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_original: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    price_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    available_rooms: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class CompetitorSet(Base):
    __tablename__ = "competitor_sets"

    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), primary_key=True)
    competitor_hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    similarity_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    components: Mapped[dict | None] = mapped_column(JSONType)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Compset isabeti metriği: otel "bu rakip gerçekten bizimle yarışır" dedi mi?
    feedback: Mapped[str | None] = mapped_column(Text)  # confirmed / rejected
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    competitor: Mapped[Hotel] = relationship(foreign_keys=[competitor_hotel_id])


class CompsetFeedback(Base):
    """Otelin rakip hakkındaki geri bildirimi (compset isabeti metriği için kalıcı kayıt)."""

    __tablename__ = "compset_feedback"
    __table_args__ = (UniqueConstraint("hotel_id", "competitor_hotel_id"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    competitor_hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)  # confirmed / rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PriceSuggestion(Base):
    __tablename__ = "price_suggestions"
    __table_args__ = (Index("ix_sugg_rt_stay_created", "room_type_id", "stay_date", "created_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"), nullable=False)
    stay_date: Mapped[date] = mapped_column(Date, nullable=False)
    suggested_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    price_floor: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_ceiling: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rationale: Mapped[dict | None] = mapped_column(JSONType)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    user_action: Mapped[str | None] = mapped_column(Text)  # applied / ignored (otelin geri bildirimi)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    room_type: Mapped[RoomType] = relationship()


class AppliedObservation(Base):
    __tablename__ = "applied_observations"
    __table_args__ = (UniqueConstraint("room_type_id", "stay_date", "observed_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"), nullable=False)
    stay_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("price_suggestions.id", ondelete="SET NULL"))
    within_tolerance: Mapped[bool | None] = mapped_column(Boolean)


class StayOutcome(Base):
    """Karar birimi (oda tipi × konaklama tarihi): öneri uygulandı mı (otomatik tespit) ve sonucu ne oldu.

    Doluluk ve gelir alanları satış kanalı envanterinden türetilen TAHMİNLERDİR."""

    __tablename__ = "stay_outcomes"
    __table_args__ = (
        UniqueConstraint("room_type_id", "stay_date"),
        CheckConstraint("status IN ('applied','partial','not_applied','unobserved')", name="ck_outcome_status"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"), nullable=False)
    stay_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("price_suggestions.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unobserved")
    first_suggested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suggested_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_before: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    observed_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    own_occ_start: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    own_occ_end: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    comp_occ_start: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    comp_occ_end: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    comp_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    revpar_index: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    @property
    def relative_pickup(self) -> float | None:
        vals = (self.own_occ_start, self.own_occ_end, self.comp_occ_start, self.comp_occ_end)
        if any(v is None for v in vals):
            return None
        return round((float(self.own_occ_end) - float(self.own_occ_start))
                     - (float(self.comp_occ_end) - float(self.comp_occ_start)), 3)


class InventoryEvent(Base):
    __tablename__ = "inventory_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('drop','closed','reopen','unchanged')", name="ck_inv_event"),
        Index("ix_inv_rt_stay", "room_type_id", "stay_date"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"), nullable=False)
    stay_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prev_count: Mapped[int | None] = mapped_column(Integer)
    new_count: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str | None] = mapped_column(Text)


class RoiEstimate(Base):
    __tablename__ = "roi_estimates"
    __table_args__ = (CheckConstraint("confidence IN ('low','medium','high')", name="ck_roi_conf"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_revenue_delta: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    control_group_size: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONType)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# --------------------------------------------------------------------------- #
# Talep verisi
# --------------------------------------------------------------------------- #
class DemandSignal(Base):
    __tablename__ = "demand_signals"
    __table_args__ = (UniqueConstraint("province", "date"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    flight_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    event_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    holiday_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    demand_score: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    components: Mapped[dict | None] = mapped_column(JSONType)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="demo")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    district: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="festival")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False, default=50)  # 0-100
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    external_id: Mapped[str | None] = mapped_column(Text, unique=True)


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("date", "currency"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    per_eur: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)  # 1 EUR = x birim
    source: Mapped[str] = mapped_column(Text, nullable=False, default="demo")


# --------------------------------------------------------------------------- #
# Uygulama: kullanıcılar, paketler, abonelikler
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','hotel')", name="ck_user_role"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="hotel")
    hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    hotel: Mapped[Hotel | None] = relationship()


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text)
    monthly_price_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_competitors: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_room_types: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    features: Mapped[list | None] = mapped_column(JSONType)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("status IN ('trial','active','past_due','canceled')", name="ck_sub_status"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="trial")
    started_at: Mapped[date] = mapped_column(Date, nullable=False)
    renews_at: Mapped[date | None] = mapped_column(Date)
    canceled_at: Mapped[date | None] = mapped_column(Date)

    hotel: Mapped[Hotel] = relationship(back_populates="subscriptions")
    plan: Mapped[Plan] = relationship()
    invoices: Mapped[list[Invoice]] = relationship(back_populates="subscription", cascade="all, delete-orphan")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (CheckConstraint("status IN ('paid','open','failed','void')", name="ck_inv_status"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    issued_at: Mapped[date] = mapped_column(Date, nullable=False)

    subscription: Mapped[Subscription] = relationship(back_populates="invoices")


class HotelSettings(Base):
    __tablename__ = "hotel_settings"
    __table_args__ = (
        CheckConstraint("strategy IN ('conservative','balanced','aggressive')", name="ck_strategy"),
    )

    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), primary_key=True)
    tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=5)
    strategy: Mapped[str] = mapped_column(Text, nullable=False, default="balanced")
    min_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    floor_below_p25_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=10)
    ceiling_margin_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=5)
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    onboarding_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    hotel: Mapped[Hotel] = relationship(back_populates="settings")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False, default="info")  # info/success/warning
    link: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# --------------------------------------------------------------------------- #
# Operasyon: işler, API kullanımı, ayarlar, uyumluluk, denetim
# --------------------------------------------------------------------------- #
class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")  # running/success/failed
    trigger: Mapped[str] = mapped_column(Text, nullable=False, default="schedule")  # schedule/manual/seed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("day", "provider", "endpoint"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProviderCost(Base):
    __tablename__ = "provider_costs"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    unit_cost_eur: Mapped[Decimal] = mapped_column(Numeric(10, 5), nullable=False, default=0)
    monthly_fee_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    included_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict | list | str | float | int | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ComplianceItem(Base):
    __tablename__ = "compliance_items"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONType)
    ip: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    user: Mapped[User | None] = relationship()
