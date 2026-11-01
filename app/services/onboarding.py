"""Kayıt ve ilk kurulum: otel adı + adres -> OTA kaydıyla eşleştirme -> otomatik profil,
compset ve ilk öneriler. Doküman bölüm 3, adım 1-3."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Hotel, Notification, Plan, RoomType, Subscription, User
from app.security import hash_password
from app.services.compset import build_compset
from app.services.pipeline import ensure_hotel_settings, get_setting
from app.services.pricing import generate_for_hotel
from app.services.providers import get_providers
from app.services.room_mapping import normalize


@dataclass
class MatchCandidate:
    hotel: Hotel
    score: float


def find_candidates(db: Session, name: str, province: str, district: str | None, limit: int = 5) -> list[MatchCandidate]:
    q = select(Hotel).where(Hotel.province == province, Hotel.is_subscriber.is_(False), Hotel.source_id.is_not(None))
    target = normalize(name)
    out = []
    for h in db.execute(q).scalars():
        score = difflib.SequenceMatcher(None, target, normalize(h.name)).ratio()
        if district and h.district and normalize(h.district) == normalize(district):
            score += 0.25
        out.append(MatchCandidate(h, round(score, 3)))
    out.sort(key=lambda c: c.score, reverse=True)
    return out[:limit]


def complete_registration(
    db: Session, *, full_name: str, email: str, password: str, plan_code: str, hotel_id: int | None,
    hotel_name: str, address: str, province: str, district: str | None, star_rating: int | None,
    today: date | None = None,
) -> tuple[User, Hotel]:
    today = today or date.today()
    plan = db.execute(select(Plan).where(Plan.code == plan_code)).scalar_one()
    if hotel_id:
        hotel = db.get(Hotel, hotel_id)
        if hotel is None or hotel.is_subscriber:
            raise ValueError("Seçilen otel kaydı kullanılamıyor.")
        hotel.address = address or hotel.address
    else:
        providers = get_providers()
        place = providers.places.lookup(hotel_name, address, province, district)
        hotel = Hotel(name=hotel_name, province=province, district=district, address=address,
                      star_rating=star_rating, lat=place.lat, lng=place.lng, place_id=place.place_id,
                      hotel_type="boutique")
        db.add(hotel)
        db.flush()
        for raw, cat in (("Standart Oda", "standard"), ("Deluxe Oda", "deluxe")):
            db.add(RoomType(hotel_id=hotel.id, raw_name=raw, category=cat, mapped_by="manual", confidence=1, reviewed=True))
        db.add(Notification(hotel_id=hotel.id, title="Oteliniz OTA kaynaklarında bulunamadı",
                            body="Kendi fiyatlarınız izlenemediği için öneriler rakip dağılımına göre üretilir. "
                                 "Oda tiplerinizi Oda Tipleri ekranından düzenleyebilirsiniz.", level="warning",
                            link="/panel/oda-tipleri"))
    hotel.is_subscriber = True
    hs = ensure_hotel_settings(db, hotel)
    hs.onboarding_done = False
    user = User(email=email.lower().strip(), password_hash=hash_password(password), full_name=full_name,
                role="hotel", hotel_id=hotel.id)
    db.add(user)
    db.add(Subscription(hotel_id=hotel.id, plan_id=plan.id, status="trial", started_at=today,
                        renews_at=today + timedelta(days=14)))
    db.flush()
    build_compset(db, hotel, size=settings.compset_size, today=today)
    horizon = min(int(get_setting(db, "horizon_days", settings.horizon_days)), plan.horizon_days)
    generate_for_hotel(db, hotel, today, today + timedelta(days=horizon), as_of=today)
    db.add(Notification(hotel_id=hotel.id, title="Hoş geldiniz!",
                        body="Rakip setiniz ve ilk fiyat önerileriniz hazır. 14 günlük deneme süreniz başladı.",
                        level="success", link="/panel"))
    db.flush()
    return user, hotel
