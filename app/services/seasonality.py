"""Mevsimsel katsayı. Doküman 5.3.

MVP yaklaşımı: geçmiş fiyat verisinden aylık ortalama / yıllık ortalama.
Veri az olan aylarda bölgesel ön bilgi (prior) ile harmanlanır. Veri biriktikçe
gözlem ağırlığı artar.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hotel, RateSnapshot, RoomType

# Bölgesel ön bilgi (Ocak..Aralık). Bodrum yaz yoğun, Antalya uzun sezon, Kapadokya dönemsel.
REGION_PRIORS = {
    "summer": [0.55, 0.55, 0.62, 0.78, 0.98, 1.32, 1.62, 1.66, 1.26, 0.86, 0.60, 0.56],
    "long": [0.62, 0.62, 0.72, 0.90, 1.06, 1.28, 1.48, 1.52, 1.28, 1.02, 0.70, 0.64],
    "antalya": [0.66, 0.66, 0.76, 0.92, 1.08, 1.26, 1.42, 1.46, 1.28, 1.08, 0.76, 0.68],
    "kapadokya": [0.70, 0.72, 0.90, 1.20, 1.25, 1.05, 0.95, 0.98, 1.15, 1.25, 0.95, 0.90],
}
DISTRICT_PROFILE = {
    "Bodrum": "summer", "Marmaris": "summer", "Datça": "summer",
    "Fethiye": "long", "Dalyan": "long", "Köyceğiz": "long", "Kaş": "long",
}
MIN_OBS_PER_MONTH = 15

MONTHS_TR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def profile_for(province: str, district: str | None) -> str:
    if district and district in DISTRICT_PROFILE:
        return DISTRICT_PROFILE[district]
    if province == "Antalya":
        return "antalya"
    if province == "Nevşehir":
        return "kapadokya"
    return "summer"


def season_label(coef: float) -> str:
    if coef < 0.8:
        return "Ölü sezon"
    if coef < 1.1:
        return "Omuz sezon"
    return "Yüksek sezon"


def monthly_coefficients(db: Session, province: str, district: str | None = None, lookback_days: int = 400,
                         today: date | None = None) -> dict:
    """{'coef': [12], 'observed': [12 or None], 'prior': [12], 'n': [12]}"""
    today = today or date.today()
    prior = REGION_PRIORS[profile_for(province, district)]
    q = (
        select(RateSnapshot.stay_date, RateSnapshot.price_eur, RateSnapshot.room_type_id)
        .join(RoomType, RoomType.id == RateSnapshot.room_type_id)
        .join(Hotel, Hotel.id == RoomType.hotel_id)
        .where(
            Hotel.province == province,
            RoomType.category == "standard",
            RateSnapshot.price_eur.is_not(None),
            RateSnapshot.stay_date >= today - timedelta(days=lookback_days),
            RateSnapshot.stay_date <= today + timedelta(days=120),
        )
    )
    if district:
        q = q.where(Hotel.district == district)
    # oda tipi başına ortalama fiyata göre normalize et (otel kompozisyonu farkını gidermek için)
    by_rt: dict[int, list[tuple[date, float]]] = defaultdict(list)
    for stay, price, rt in db.execute(q):
        by_rt[rt].append((stay, float(price)))
    month_ratios: dict[int, list[float]] = defaultdict(list)
    for rows in by_rt.values():
        mean = statistics.fmean(p for _, p in rows)
        if mean <= 0:
            continue
        for stay, p in rows:
            month_ratios[stay.month - 1].append(p / mean)
    observed: list[float | None] = []
    n: list[int] = []
    for m in range(12):
        vals = month_ratios.get(m, [])
        n.append(len(vals))
        observed.append(statistics.fmean(vals) if vals else None)
    # Gözlenen oranlar, gözlenen ayların prior ortalamasına göre ölçeklenir
    obs_months = [m for m in range(12) if observed[m] is not None and n[m] >= MIN_OBS_PER_MONTH]
    coef = list(prior)
    if obs_months:
        prior_mean = statistics.fmean(prior[m] for m in obs_months)
        for m in obs_months:
            w = min(1.0, n[m] / (MIN_OBS_PER_MONTH * 20))  # veri arttıkça gözleme güven
            coef[m] = round((1 - w) * prior[m] + w * observed[m] * prior_mean, 3)
    return {"coef": coef, "observed": observed, "prior": prior, "n": n, "profile": profile_for(province, district)}


def coefficient_for(coefs: list[float], d: date) -> float:
    return coefs[d.month - 1]
