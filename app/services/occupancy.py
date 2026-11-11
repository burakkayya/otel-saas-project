"""Satış kanalı envanterinden TAHMİNİ doluluk (abone otel ve rakipler).

Bir otelin kesin doluluğu yalnızca kendi PMS / kanal yöneticisi verisindedir; rakipler için kesin
doluluk hiçbir yasal kaynakta yoktur. Burada her taramada görülen "satışa açık oda" sayısından
doluluk tahmin edilir:

    kanal kotası  = otelin bu kanala açtığı oda sayısı (uzak tarihlerde görülen en yüksek açık oda)
    doluluk       = 1 − (şu an açık oda / kanal kotası)

Kanal payı ve toplam oda sayısı oranda sadeleşir. Stop-sell ve başka kanaldan satış ayırt
edilemediği için sonuç her zaman aralık ve güven düzeyiyle verilir.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Hotel, RateSnapshot, RoomType
from app.services.market import end_of_day, latest_observations

HALF_WIDTH = {"high": 0.06, "medium": 0.12, "low": 0.20}
SOLD_OUT_FLOOR = 0.97
CONF_LABELS = {"high": "Yüksek", "medium": "Orta", "low": "Düşük"}


@dataclass
class OccEstimate:
    occ: float            # 0..1 nokta tahmini
    low: float
    high: float
    visible: int          # satışa açık oda (kanal)
    allotment: float      # tahmini kanal kotası
    closed: bool          # tüm oda tipleri satışa kapalı (dolu ya da stop-sell)
    confidence: str       # low / medium / high
    rooms_sold: int | None = None  # toplam oda sayısı biliniyorsa tahmini satılan oda

    @property
    def pct(self) -> int:
        return round(self.occ * 100)


def _quantile(values: list[float], q: float) -> float:
    vals = sorted(values)
    if not vals:
        return 0.0
    pos = (len(vals) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def confidence_for(n_obs: int, allot_dates: int) -> str:
    if n_obs >= 3 and allot_dates >= 20:
        return "high"
    if n_obs >= 2 and allot_dates >= 8:
        return "medium"
    return "low"


def estimate(visible: int, allotment: float, closed: bool, n_obs: int, allot_dates: int,
             room_count: int | None = None) -> OccEstimate | None:
    """Saf hesap: açık oda ve kota → doluluk tahmini."""
    if allotment <= 0:
        return None
    occ = max(0.0, min(1.0, 1 - visible / allotment))
    if closed:
        occ = max(occ, SOLD_OUT_FLOOR)
    conf = confidence_for(n_obs, allot_dates)
    hw = HALF_WIDTH[conf]
    sold = round(occ * room_count) if room_count else None
    return OccEstimate(round(occ, 3), round(max(0.0, occ - hw), 3), round(min(1.0, occ + hw), 3),
                       int(visible), round(allotment, 1), closed, conf, sold)


def hotel_occupancy(db: Session, hotel_ids: list[int], start: date, end: date,
                    as_of: date | None = None) -> dict[int, dict[date, OccEstimate]]:
    """Otel → konaklama tarihi → tahmini doluluk (as_of gününe kadar gözlenen veriyle)."""
    as_of = as_of or date.today()
    if not hotel_ids:
        return {}
    rts = db.execute(select(RoomType.id, RoomType.hotel_id).where(RoomType.hotel_id.in_(hotel_ids))).all()
    rt_hotel = {rt: h for rt, h in rts}
    if not rt_hotel:
        return {}
    room_counts = dict(db.execute(select(Hotel.id, Hotel.room_count).where(Hotel.id.in_(hotel_ids))).all())

    # Kota için daha geniş bir konaklama penceresi: geçmiş 90 gün + ufuk
    lo, hi = min(start, as_of - timedelta(days=90)), max(end, as_of + timedelta(days=90))
    q = select(RateSnapshot.room_type_id, RateSnapshot.stay_date, func.max(RateSnapshot.available_rooms),
               func.count()).where(
        RateSnapshot.room_type_id.in_(list(rt_hotel)), RateSnapshot.stay_date >= lo, RateSnapshot.stay_date <= hi,
        RateSnapshot.observed_at <= end_of_day(as_of),
    ).group_by(RateSnapshot.room_type_id, RateSnapshot.stay_date)
    peak: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    nobs: dict[int, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for rt, stay, mx, cnt in db.execute(q):
        h = rt_hotel[rt]
        peak[h][stay] += float(mx or 0)
        nobs[h][stay] = max(nobs[h][stay], int(cnt))

    # Ay bazında %90'lık dilim (yeterli tarih yoksa otel geneli)
    allot_month: dict[int, dict[tuple[int, int], tuple[float, int]]] = defaultdict(dict)
    allot_all: dict[int, tuple[float, int]] = {}
    for h, days in peak.items():
        vals = [v for v in days.values() if v > 0]
        allot_all[h] = (_quantile(vals, 0.9), len(vals))
        by_m: dict[tuple[int, int], list[float]] = defaultdict(list)
        for d, v in days.items():
            if v > 0:
                by_m[(d.year, d.month)].append(v)
        for m, vs in by_m.items():
            if len(vs) >= 8:
                allot_month[h][m] = (_quantile(vs, 0.9), len(vs))

    latest = latest_observations(db, list(rt_hotel), start, end, as_of)
    vis: dict[int, dict[date, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))  # açık, tip, kapalı
    for (rt, stay), o in latest.items():
        h = rt_hotel[rt]
        cell = vis[h][stay]
        cell[1] += 1
        if o.price_eur is None or not o.available:
            cell[2] += 1
        else:
            cell[0] += int(o.available)

    out: dict[int, dict[date, OccEstimate]] = defaultdict(dict)
    for h, days in vis.items():
        for stay, (open_rooms, n_types, n_closed) in days.items():
            base, n_dates = allot_month[h].get((stay.year, stay.month)) or allot_all.get(h, (0.0, 0))
            allotment = max(base, peak[h].get(stay, 0.0))
            est = estimate(open_rooms, allotment, n_types > 0 and n_closed == n_types,
                           nobs[h].get(stay, 0), n_dates, room_counts.get(h))
            if est:
                out[h][stay] = est
    return out


def median_occ(estimates: list[OccEstimate | None]) -> float | None:
    vals = [e.occ for e in estimates if e is not None]
    return round(statistics.median(vals), 3) if vals else None


def compset_occupancy(db: Session, hotel_id: int, comp_ids: list[int], start: date, end: date,
                      as_of: date | None = None) -> dict[date, dict]:
    """Konaklama tarihi → {own, comp (medyan), own_7d, comp_7d, own_est}: panel ve motor için tek çağrı."""
    as_of = as_of or date.today()
    ids = [hotel_id] + list(comp_ids)
    now = hotel_occupancy(db, ids, start, end, as_of)
    prev = hotel_occupancy(db, ids, start, end, as_of - timedelta(days=7))
    out: dict[date, dict] = {}
    d = start
    while d <= end:
        own = now.get(hotel_id, {}).get(d)
        own_prev = prev.get(hotel_id, {}).get(d)
        comp = median_occ([now.get(c, {}).get(d) for c in comp_ids])
        comp_prev = median_occ([prev.get(c, {}).get(d) for c in comp_ids])
        out[d] = {
            "own": own.occ if own else None,
            "own_est": own,
            "comp": comp,
            "own_7d": round(own.occ - own_prev.occ, 3) if own and own_prev else None,
            "comp_7d": round(comp - comp_prev, 3) if comp is not None and comp_prev is not None else None,
            "comp_n": sum(1 for c in comp_ids if now.get(c, {}).get(d)),
        }
        d += timedelta(days=1)
    return out
