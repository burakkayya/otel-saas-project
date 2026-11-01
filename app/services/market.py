"""Fiyat gözlemlerine erişim yardımcıları (rate shopping verisi)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompetitorSet, Hotel, RateSnapshot, RoomType


@dataclass
class Obs:
    price_eur: float | None
    available: int | None
    observed_at: datetime


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def latest_observations(
    db: Session, room_type_ids: list[int], start: date, end: date, as_of: date | None = None
) -> dict[tuple[int, date], Obs]:
    """(oda tipi, konaklama tarihi) başına as_of gününe kadar gözlenen en son kayıt."""
    if not room_type_ids:
        return {}
    q = select(
        RateSnapshot.room_type_id, RateSnapshot.stay_date, RateSnapshot.observed_at,
        RateSnapshot.price_eur, RateSnapshot.available_rooms,
    ).where(
        RateSnapshot.room_type_id.in_(room_type_ids),
        RateSnapshot.stay_date >= start,
        RateSnapshot.stay_date <= end,
    )
    if as_of is not None:
        q = q.where(RateSnapshot.observed_at <= end_of_day(as_of))
    out: dict[tuple[int, date], Obs] = {}
    for rt, stay, obs_at, price, avail in db.execute(q):
        obs_at = _aware(obs_at)
        key = (rt, stay)
        cur = out.get(key)
        if cur is None or obs_at > cur.observed_at:
            out[key] = Obs(float(price) if price is not None else None, avail, obs_at)
    return out


def all_observations(db: Session, room_type_ids: list[int], start: date, end: date) -> dict[tuple[int, date], list[Obs]]:
    if not room_type_ids:
        return {}
    q = select(
        RateSnapshot.room_type_id, RateSnapshot.stay_date, RateSnapshot.observed_at,
        RateSnapshot.price_eur, RateSnapshot.available_rooms,
    ).where(
        RateSnapshot.room_type_id.in_(room_type_ids),
        RateSnapshot.stay_date >= start,
        RateSnapshot.stay_date <= end,
    ).order_by(RateSnapshot.observed_at)
    out: dict[tuple[int, date], list[Obs]] = defaultdict(list)
    for rt, stay, obs_at, price, avail in db.execute(q):
        out[(rt, stay)].append(Obs(float(price) if price is not None else None, avail, _aware(obs_at)))
    return out


def room_types_by_category(db: Session, hotel_ids: list[int]) -> dict[int, dict[str, list[int]]]:
    out: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    if not hotel_ids:
        return out
    for rt in db.execute(select(RoomType).where(RoomType.hotel_id.in_(hotel_ids))).scalars():
        out[rt.hotel_id][rt.category or "other"].append(rt.id)
    return out


def compset_ids(db: Session, hotel_id: int) -> list[int]:
    rows = db.execute(
        select(CompetitorSet.competitor_hotel_id).where(CompetitorSet.hotel_id == hotel_id).order_by(CompetitorSet.rank)
    ).scalars()
    return list(rows)


def category_price_by_hotel(
    db: Session, hotel_ids: list[int], category: str, start: date, end: date, as_of: date | None = None
) -> dict[int, dict[date, Obs]]:
    """Otel başına, kategorideki en ucuz satılabilir oda fiyatı (rate shopping mantığı)."""
    rts = room_types_by_category(db, hotel_ids)
    rt_to_hotel = {}
    for hid in hotel_ids:
        for rt in rts.get(hid, {}).get(category, []):
            rt_to_hotel[rt] = hid
    latest = latest_observations(db, list(rt_to_hotel), start, end, as_of)
    out: dict[int, dict[date, Obs]] = defaultdict(dict)
    for (rt, stay), obs in latest.items():
        hid = rt_to_hotel[rt]
        cur = out[hid].get(stay)
        if cur is None:
            out[hid][stay] = Obs(obs.price_eur, obs.available, obs.observed_at)
        else:
            # en düşük fiyat, envanter toplamı
            prices = [p for p in (cur.price_eur, obs.price_eur) if p is not None]
            avail = (cur.available or 0) + (obs.available or 0) if (cur.available is not None or obs.available is not None) else None
            out[hid][stay] = Obs(min(prices) if prices else None, avail, max(cur.observed_at, obs.observed_at))
    return out


def subscriber_hotels(db: Session) -> list[Hotel]:
    return list(db.execute(select(Hotel).where(Hotel.is_subscriber.is_(True), Hotel.is_active.is_(True))).scalars())
