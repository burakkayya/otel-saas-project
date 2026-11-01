"""Öneriye uyum takibi (davranış ölçümü — gelir iddiası DEĞİL). Doküman 6.1(a).

Otelin OTA'da gözlenen fiyatı, gözlem anından önceki son önerinin ±%tolerans
bandında mı? Bu, sistemin kullanım oranını gösterir.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppliedObservation, Hotel, PriceSuggestion, RateSnapshot, RoomType
from app.services.market import _aware, end_of_day


def record_uptake(db: Session, hotel: Hotel, since: datetime | None = None, until: date | None = None) -> int:
    tol = float(hotel.settings.tolerance_pct) / 100 if hotel.settings else 0.05
    rt_ids = list(db.execute(select(RoomType.id).where(RoomType.hotel_id == hotel.id)).scalars())
    if not rt_ids:
        return 0
    sq = select(PriceSuggestion.id, PriceSuggestion.room_type_id, PriceSuggestion.stay_date,
                PriceSuggestion.created_at, PriceSuggestion.suggested_price).where(PriceSuggestion.room_type_id.in_(rt_ids))
    sugg: dict[tuple[int, date], list[tuple[datetime, int, float]]] = defaultdict(list)
    for sid, rt, stay, created, price in db.execute(sq):
        sugg[(rt, stay)].append((_aware(created), sid, float(price)))
    for v in sugg.values():
        v.sort()
    oq = select(RateSnapshot.room_type_id, RateSnapshot.stay_date, RateSnapshot.observed_at, RateSnapshot.price_eur).where(
        RateSnapshot.room_type_id.in_(rt_ids), RateSnapshot.price_eur.is_not(None))
    if since is not None:
        oq = oq.where(RateSnapshot.observed_at >= since)
    if until is not None:
        oq = oq.where(RateSnapshot.observed_at <= end_of_day(until))
    existing = set(db.execute(
        select(AppliedObservation.room_type_id, AppliedObservation.stay_date, AppliedObservation.observed_at)
        .where(AppliedObservation.room_type_id.in_(rt_ids))
    ).all())
    existing = {(a, b, _aware(c)) for a, b, c in existing}
    new_rows = []
    for rt, stay, obs_at, price in db.execute(oq):
        obs_at = _aware(obs_at)
        lst = sugg.get((rt, stay))
        if not lst:
            continue
        # gözlemden en az 1 saat önce oluşturulan son öneri (otelin uygulayabilmesi için)
        cutoff = obs_at - timedelta(hours=1)
        idx = bisect.bisect_right([c for c, _, _ in lst], cutoff) - 1
        if idx < 0:
            continue
        _, sid, sp = lst[idx]
        if (rt, stay, obs_at) in existing:
            continue
        within = abs(float(price) - sp) / sp <= tol
        new_rows.append(AppliedObservation(room_type_id=rt, stay_date=stay, observed_at=obs_at,
                                           observed_price=price, suggestion_id=sid, within_tolerance=within))
        existing.add((rt, stay, obs_at))
    db.add_all(new_rows)
    db.flush()
    return len(new_rows)


def uptake_stats(db: Session, hotel_id: int, days: int = 60, today: date | None = None) -> dict:
    today = today or date.today()
    rt_ids = list(db.execute(select(RoomType.id).where(RoomType.hotel_id == hotel_id)).scalars())
    if not rt_ids:
        return {"total": 0, "within": 0, "rate": None, "weekly": []}
    rows = db.execute(
        select(AppliedObservation.observed_at, AppliedObservation.within_tolerance)
        .where(AppliedObservation.room_type_id.in_(rt_ids),
               AppliedObservation.observed_at >= end_of_day(today - timedelta(days=days)))
    ).all()
    weekly: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for obs_at, within in rows:
        d = _aware(obs_at).date()
        wk = d - timedelta(days=d.weekday())
        weekly[wk][0] += 1
        weekly[wk][1] += 1 if within else 0
    total = sum(v[0] for v in weekly.values())
    within = sum(v[1] for v in weekly.values())
    return {
        "total": total,
        "within": within,
        "rate": round(within / total * 100, 1) if total else None,
        "weekly": [{"week": k.isoformat(), "total": v[0], "within": v[1],
                    "rate": round(v[1] / v[0] * 100, 1) if v[0] else None} for k, v in sorted(weekly.items())],
    }
