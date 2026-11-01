"""Kontrol grubu karşılaştırması (fark-içinde-fark, DiD). Doküman 6.1(b).

Abone otelin ADR ve doluluk vekili, aynı bölgedeki abone olmayan benzer otellerle
abonelik öncesi ve sonrası karşılaştırılır. Tüm sonuçlar TAHMİNİ etkidir
(is_estimate = TRUE). Bölge başına 10-15'ten az kontrol oteli varsa güven 'düşük'.

Doluluk vekili OTA'daki kalan oda değişiminden türetilir; oda kapatma/başka kanal
satışı ayırt edilemediğinden kesin doluluk değildir.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hotel, RoiEstimate, RoomType
from app.services.market import all_observations

MIN_CONTROL = 10
PRE_DAYS = 56


def _hotel_daily(db: Session, hotel_ids: list[int], start: date, end: date) -> dict[int, dict[date, tuple[float, float]]]:
    """Otel -> gün -> (son fiyat, doluluk vekili) — standard kategori."""
    rts = db.execute(select(RoomType.id, RoomType.hotel_id).where(
        RoomType.hotel_id.in_(hotel_ids), RoomType.category == "standard")).all()
    rt_hotel = {rt: h for rt, h in rts}
    obs = all_observations(db, list(rt_hotel), start, end)
    out: dict[int, dict[date, tuple[float, float]]] = defaultdict(dict)
    for (rt, stay), lst in obs.items():
        avails = [o.available for o in lst if o.available is not None]
        prices = [o.price_eur for o in lst if o.price_eur]
        if not avails or not prices:
            continue
        cap = max(avails)
        if cap <= 0:
            continue
        occ = 1 - (lst[-1].available or 0) / cap
        out[rt_hotel[rt]][stay] = (prices[-1], max(0.0, min(1.0, occ)))
    return out


def _window_metrics(daily: dict[date, tuple[float, float]], start: date, end: date) -> dict | None:
    vals = [v for d, v in daily.items() if start <= d <= end]
    if len(vals) < 7:
        return None
    adr = statistics.fmean(p for p, _ in vals)
    occ = statistics.fmean(o for _, o in vals)
    return {"adr": adr, "occ": occ, "revpar": adr * occ, "n": len(vals)}


def select_control_group(db: Session, hotel: Hotel, max_size: int = 20) -> list[Hotel]:
    cands = list(db.execute(select(Hotel).where(
        Hotel.province == hotel.province, Hotel.is_subscriber.is_(False), Hotel.is_active.is_(True), Hotel.id != hotel.id
    )).scalars())

    def dist(h: Hotel) -> tuple:
        star_gap = abs((h.star_rating or 3) - (hotel.star_rating or 3))
        same_type = 0 if h.hotel_type == hotel.hotel_type else 1
        same_district = 0 if h.district == hotel.district else 1
        return (star_gap, same_type, same_district)

    cands = [h for h in cands if abs((h.star_rating or 3) - (hotel.star_rating or 3)) <= 1]
    cands.sort(key=dist)
    return cands[:max_size]


def estimate_did(db: Session, hotel: Hotel, start_date: date, today: date | None = None, persist: bool = True) -> dict:
    today = today or date.today()
    pre_start, pre_end = start_date - timedelta(days=PRE_DAYS), start_date - timedelta(days=1)
    post_start, post_end = start_date, min(today - timedelta(days=1), start_date + timedelta(days=90))
    controls = select_control_group(db, hotel)
    if post_end < post_start + timedelta(days=6):
        return {"status": "insufficient_post", "message": "Abonelik sonrası en az 7 günlük veri gerekli."}
    ids = [hotel.id] + [c.id for c in controls]
    daily = _hotel_daily(db, ids, pre_start, post_end)
    h_pre = _window_metrics(daily.get(hotel.id, {}), pre_start, pre_end)
    h_post = _window_metrics(daily.get(hotel.id, {}), post_start, post_end)
    if not h_pre or not h_post:
        return {"status": "insufficient_data", "message": "Abone otelin öncesi/sonrası için yeterli fiyat gözlemi yok."}
    c_changes = {"adr": [], "occ": [], "revpar": []}
    used_controls = 0
    for c in controls:
        pre = _window_metrics(daily.get(c.id, {}), pre_start, pre_end)
        post = _window_metrics(daily.get(c.id, {}), post_start, post_end)
        if pre and post:
            used_controls += 1
            for k in c_changes:
                c_changes[k].append(post[k] - pre[k])
    if used_controls == 0:
        return {"status": "no_control", "message": "Karşılaştırılabilir kontrol oteli bulunamadı."}
    did = {}
    for k in ("adr", "occ", "revpar"):
        cm = statistics.fmean(c_changes[k])
        se = statistics.stdev(c_changes[k]) / math.sqrt(len(c_changes[k])) if len(c_changes[k]) > 1 else None
        did[k] = {"subscriber_change": h_post[k] - h_pre[k], "control_change": cm,
                  "did": (h_post[k] - h_pre[k]) - cm, "se": se}
    rev = did["revpar"]
    significant = bool(rev["se"]) and abs(rev["did"]) > 2 * rev["se"]
    post_days = (post_end - post_start).days + 1
    if used_controls < MIN_CONTROL or not significant:
        confidence = "low"
    elif used_controls < 15 or post_days < 28:
        confidence = "medium"
    else:
        confidence = "high"
    rooms = hotel.room_count or 20
    delta = round(rev["did"] * rooms * post_days, 2)

    # haftalık seri (grafik)
    weekly: dict[date, dict[str, list[float]]] = defaultdict(lambda: {"h": [], "c": []})
    for hid, days in daily.items():
        for d, (p, o) in days.items():
            wk = d - timedelta(days=d.weekday())
            weekly[wk]["h" if hid == hotel.id else "c"].append(p * o)
    series = [{"week": k.isoformat(), "subscriber": round(statistics.fmean(v["h"]), 2) if v["h"] else None,
               "control": round(statistics.fmean(v["c"]), 2) if v["c"] else None} for k, v in sorted(weekly.items())]

    result = {
        "status": "ok",
        "pre": [pre_start.isoformat(), pre_end.isoformat()],
        "post": [post_start.isoformat(), post_end.isoformat()],
        "subscriber_pre": h_pre, "subscriber_post": h_post,
        "did": did, "control_group_size": used_controls, "significant": significant,
        "confidence": confidence, "estimated_revenue_delta": delta, "post_days": post_days,
        "series": series,
        "note": "Tahmini etki. Doluluk, OTA kalan oda değişiminden türetilen vekil bir ölçüdür.",
    }
    if persist:
        db.add(RoiEstimate(
            hotel_id=hotel.id, period_start=post_start, period_end=post_end, method="control_group_did",
            estimated_revenue_delta=delta, control_group_size=used_controls, confidence=confidence,
            details={k: v for k, v in result.items() if k != "series"} | {"series": series}, is_estimate=True,
        ))
        db.flush()
    return result


def record_uptake_estimate(db: Session, hotel: Hotel, stats: dict, start: date, end: date) -> None:
    """Öneriye uyum oranını roi_estimates tablosuna 'suggestion_uptake' yöntemiyle yazar (gelir değeri yok)."""
    db.add(RoiEstimate(
        hotel_id=hotel.id, period_start=start, period_end=end, method="suggestion_uptake",
        estimated_revenue_delta=None, control_group_size=None,
        confidence="medium" if stats.get("total", 0) >= 50 else "low",
        details={"uptake_rate": stats.get("rate"), "total": stats.get("total"), "within": stats.get("within")},
        is_estimate=True,
    ))
    db.flush()
