"""Compset (rakip seti) belirleme. Doküman 5.1.

Puan = 0.40·mesafe + 0.25·yıldız + 0.15·oda tipi benzerliği + 0.20·fiyat bandı yakınlığı
Yakın rakip yoksa (izole otel) yarıçap kademeli olarak genişletilir.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CompetitorSet, CompsetFeedback, Hotel, utcnow
from app.services.market import category_price_by_hotel, room_types_by_category

WEIGHTS = {"distance": 0.40, "star": 0.25, "room_types": 0.15, "price_band": 0.20}
RADII_KM = (5.0, 12.0, 30.0, 80.0)


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    if None in (lat1, lng1, lat2, lng2):
        return 999.0
    lat1, lng1, lat2, lng2 = map(lambda v: math.radians(float(v)), (lat1, lng1, lat2, lng2))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


@dataclass
class Candidate:
    hotel: Hotel
    distance_km: float
    score: float
    components: dict = field(default_factory=dict)


def _score(base: Hotel, cand: Hotel, dist: float, radius: float, base_cats: set, cand_cats: set,
           base_price: float | None, cand_price: float | None) -> tuple[float, dict]:
    d_score = math.exp(-dist / radius)
    if base.star_rating and cand.star_rating:
        s_score = max(0.0, 1 - abs(base.star_rating - cand.star_rating) / 3)
    else:
        s_score = 0.5
    union = base_cats | cand_cats
    r_score = len(base_cats & cand_cats) / len(union) if union else 0.5
    if base_price and cand_price:
        p_score = max(0.0, 1 - abs(base_price - cand_price) / base_price)
    else:
        p_score = 0.5
    comps = {"distance": round(d_score, 3), "star": round(s_score, 3),
             "room_types": round(r_score, 3), "price_band": round(p_score, 3)}
    total = sum(WEIGHTS[k] * v for k, v in comps.items())
    return round(total, 3), comps


def _median_price(obs_by_date) -> float | None:
    vals = [o.price_eur for o in obs_by_date.values() if o.price_eur]
    return statistics.median(vals) if vals else None


def rank_candidates(db: Session, hotel: Hotel, today: date | None = None, limit: int = 30) -> tuple[list[Candidate], float]:
    today = today or date.today()
    others = list(
        db.execute(
            select(Hotel).where(Hotel.province == hotel.province, Hotel.id != hotel.id, Hotel.is_active.is_(True))
        ).scalars()
    )
    if not others:
        return [], RADII_KM[0]
    dists = {o.id: haversine_km(hotel.lat, hotel.lng, o.lat, o.lng) for o in others}
    radius = RADII_KM[-1]
    for r in RADII_KM:
        if sum(1 for d in dists.values() if d <= r) >= 5:
            radius = r
            break
    ids = [hotel.id] + [o.id for o in others]
    cats = room_types_by_category(db, ids)
    prices = category_price_by_hotel(db, ids, "standard", today - timedelta(days=21), today + timedelta(days=30), as_of=today)
    base_price = _median_price(prices.get(hotel.id, {}))
    base_cats = set(cats.get(hotel.id, {}).keys())
    cands = []
    for o in others:
        if dists[o.id] > radius * 2.5:
            continue
        score, comps = _score(hotel, o, dists[o.id], radius, base_cats, set(cats.get(o.id, {}).keys()),
                              base_price, _median_price(prices.get(o.id, {})))
        cands.append(Candidate(o, round(dists[o.id], 2), score, comps))
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands[:limit], radius


def build_compset(db: Session, hotel: Hotel, size: int = 5, today: date | None = None, keep_manual: bool = True) -> list[CompetitorSet]:
    """Rakip setini (yeniden) oluşturur. Otelin elle eklediği rakipler korunur."""
    existing = list(db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == hotel.id)).scalars())
    manual = [c for c in existing if c.is_manual and keep_manual]
    rejected = set(db.execute(
        select(CompsetFeedback.competitor_hotel_id).where(
            CompsetFeedback.hotel_id == hotel.id, CompsetFeedback.verdict == "rejected")
    ).scalars())
    confirmed = set(db.execute(
        select(CompsetFeedback.competitor_hotel_id).where(
            CompsetFeedback.hotel_id == hotel.id, CompsetFeedback.verdict == "confirmed")
    ).scalars())
    db.execute(delete(CompetitorSet).where(CompetitorSet.hotel_id == hotel.id, CompetitorSet.is_manual.is_(False)))
    cands, radius = rank_candidates(db, hotel, today)
    taken = {c.competitor_hotel_id for c in manual}
    rows = list(manual)
    for c in cands:
        if len(rows) >= size:
            break
        if c.hotel.id in taken or c.hotel.id in rejected:
            continue
        comps = dict(c.components)
        comps["radius_km"] = radius
        row = CompetitorSet(
            hotel_id=hotel.id, competitor_hotel_id=c.hotel.id, rank=0, similarity_score=c.score,
            distance_km=c.distance_km, components=comps, is_manual=False, updated_at=utcnow(),
            feedback="confirmed" if c.hotel.id in confirmed else None,
        )
        db.add(row)
        rows.append(row)
        taken.add(c.hotel.id)
    rows.sort(key=lambda r: (not r.is_manual, -(float(r.similarity_score or 0))))
    for i, r in enumerate(rows, start=1):
        r.rank = i
    db.flush()
    return rows


def add_manual_competitor(db: Session, hotel: Hotel, competitor: Hotel) -> CompetitorSet:
    row = db.get(CompetitorSet, (hotel.id, competitor.id))
    dist = haversine_km(hotel.lat, hotel.lng, competitor.lat, competitor.lng)
    if row is None:
        count = len(list(db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == hotel.id)).scalars()))
        row = CompetitorSet(hotel_id=hotel.id, competitor_hotel_id=competitor.id, rank=count + 1,
                            similarity_score=None, distance_km=round(dist, 2), is_manual=True,
                            components={"note": "Otel tarafından elle eklendi"})
        db.add(row)
    else:
        row.is_manual = True
    row.feedback = "confirmed"
    row.updated_at = utcnow()
    set_feedback(db, hotel.id, competitor.id, "confirmed")
    db.flush()
    return row


def set_feedback(db: Session, hotel_id: int, competitor_id: int, verdict: str) -> None:
    if verdict not in ("confirmed", "rejected"):
        raise ValueError("verdict")
    fb = db.execute(select(CompsetFeedback).where(
        CompsetFeedback.hotel_id == hotel_id, CompsetFeedback.competitor_hotel_id == competitor_id)).scalar_one_or_none()
    if fb is None:
        db.add(CompsetFeedback(hotel_id=hotel_id, competitor_hotel_id=competitor_id, verdict=verdict))
    else:
        fb.verdict = verdict
        fb.created_at = utcnow()
    row = db.get(CompetitorSet, (hotel_id, competitor_id))
    if row is not None:
        if verdict == "rejected":
            remove_competitor(db, db.get(Hotel, hotel_id), competitor_id)
        else:
            row.feedback = "confirmed"
    db.flush()


def remove_competitor(db: Session, hotel: Hotel, competitor_id: int) -> None:
    row = db.get(CompetitorSet, (hotel.id, competitor_id))
    if row:
        db.delete(row)
        db.flush()
        rows = list(db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == hotel.id).order_by(CompetitorSet.rank)).scalars())
        for i, r in enumerate(rows, start=1):
            r.rank = i


def compset_accuracy(db: Session, hotel_id: int | None = None) -> dict:
    """Compset isabeti: geri bildirim verilen rakiplerden 'onaylanan' oranı."""
    q = select(CompsetFeedback.verdict)
    if hotel_id:
        q = q.where(CompsetFeedback.hotel_id == hotel_id)
    fb = list(db.execute(q).scalars())
    confirmed = sum(1 for f in fb if f == "confirmed")
    return {"rated": len(fb), "confirmed": confirmed, "rate": round(confirmed / len(fb) * 100, 1) if fb else None}
