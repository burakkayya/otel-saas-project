"""Backtest: geçmiş konaklama tarihleri için, yalnızca o gün bilinen veriyle
(as_of = konaklama − öncül gün) öneri üretilir ve sonradan gerçekleşen piyasa
fiyatıyla karşılaştırılır. Doküman 6.2 — MVP'nin kanıtı.

Ölçütler:
- Öneri MAPE: önerinin, konaklamadan bir gün önceki (otelin konumlama endeksiyle
  ölçeklenmiş) rakip medyanına uzaklığı
- Saf yöntem MAPE: "bugünkü rakip medyanını (aynı endeksle) kopyala" yaklaşımının hatası
- Yön isabeti: piyasa %2'den fazla hareket ettiğinde önerinin yönü doğru mu
- Bant isabeti: gerçekleşen medyan, [taban, tavan] aralığına düştü mü
- Talep–doluluk korelasyonu: talep skoru ile otelin satış ilerlemesi vekili

Satış ilerlemesi, kalan oda düşüşünden türetilen bir VEKİLDİR; satış kanıtı değildir.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting, Hotel, RoomType, utcnow
from app.services.market import category_price_by_hotel, compset_ids, latest_observations
from app.services.pricing import generate_for_hotel
from app.services.seasonality import monthly_coefficients


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 5:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 3)


def run_backtest(db: Session, hotel: Hotel, days: int = 45, lead: int = 7, today: date | None = None,
                 category: str = "standard", weights: dict | None = None) -> dict:
    today = today or date.today()
    comp_ids = compset_ids(db, hotel.id)
    rts = [r for r in db.execute(select(RoomType).where(RoomType.hotel_id == hotel.id, RoomType.category == category)).scalars()]
    if not rts or not comp_ids:
        return {"rows": [], "summary": None, "category": category, "lead": lead}
    rt = rts[0]
    start, end = today - timedelta(days=days), today - timedelta(days=1)
    coefs = monthly_coefficients(db, hotel.province, hotel.district, today=today)["coef"]
    rows = []
    for i in range((end - start).days + 1):
        stay = start + timedelta(days=i)
        as_of = stay - timedelta(days=lead)
        final_day = stay - timedelta(days=1)
        sugg = [s for s in generate_for_hotel(db, hotel, stay, stay, as_of=as_of, persist=False, coefs=coefs, weights=weights) if s.room_type_id == rt.id]
        if not sugg:
            continue
        s = sugg[0]
        final = category_price_by_hotel(db, comp_ids, category, stay, stay, as_of=final_day)
        final_prices = [final.get(c, {}).get(stay).price_eur for c in comp_ids
                        if final.get(c, {}).get(stay) and final.get(c, {}).get(stay).price_eur]
        if not final_prices:
            continue
        pi = s.rationale.get("position_index", 1.0)
        # Hedef: otelin konumlamasına göre ayarlanmış, konaklamadan bir gün önceki piyasa fiyatı
        m_final = statistics.median(final_prices) * pi
        m_asof = s.rationale["comp_median"] * pi
        own_asof = latest_observations(db, [rt.id], stay, stay, as_of).get((rt.id, stay))
        own_final = latest_observations(db, [rt.id], stay, stay, final_day).get((rt.id, stay))
        sell = None
        if own_asof and own_final and own_asof.available:
            sell = max(0.0, (own_asof.available - (own_final.available or 0)) / own_asof.available)
        rows.append({
            "stay_date": stay.isoformat(),
            "suggested": float(s.suggested_price),
            "floor": float(s.price_floor),
            "ceiling": float(s.price_ceiling),
            "market_asof": round(m_asof, 2),
            "market_final": round(m_final, 2),
            "own_final": own_final.price_eur if own_final else None,
            "demand": s.rationale["demand_score"],
            "sell_through": round(sell, 3) if sell is not None else None,
        })
    if not rows:
        return {"rows": [], "summary": None, "category": category, "lead": lead}

    def mape(key):
        vals = [abs(r[key] - r["market_final"]) / r["market_final"] for r in rows if r[key]]
        return round(statistics.fmean(vals) * 100, 2) if vals else None

    moved = [r for r in rows if abs(r["market_final"] - r["market_asof"]) / r["market_asof"] > 0.02]
    hits = sum(1 for r in moved if (r["suggested"] - r["market_asof"]) * (r["market_final"] - r["market_asof"]) > 0)
    in_band = sum(1 for r in rows if r["floor"] <= r["market_final"] <= r["ceiling"])
    corr_pairs = [(r["demand"], r["sell_through"]) for r in rows if r["sell_through"] is not None]
    summary = {
        "n": len(rows),
        "mape_suggestion": mape("suggested"),
        "mape_naive": mape("market_asof"),
        "mape_own": mape("own_final"),
        "direction_hit_rate": round(hits / len(moved) * 100, 1) if moved else None,
        "direction_n": len(moved),
        "band_hit_rate": round(in_band / len(rows) * 100, 1),
        "demand_sell_corr": _pearson([a for a, _ in corr_pairs], [b for _, b in corr_pairs]),
    }
    if summary["mape_suggestion"] is not None and summary["mape_naive"]:
        summary["improvement_vs_naive_pct"] = round(summary["mape_naive"] - summary["mape_suggestion"], 2)
    return {"rows": rows, "summary": summary, "category": category, "lead": lead, "room_type": rt.raw_name,
            "period": [start.isoformat(), end.isoformat()]}


def store_summary(db: Session, hotel_id: int, result: dict) -> None:
    key = f"backtest:{hotel_id}"
    row = db.get(AppSetting, key)
    payload = {"summary": result.get("summary"), "lead": result.get("lead"), "period": result.get("period"),
               "computed_at": utcnow().isoformat()}
    if row is None:
        db.add(AppSetting(key=key, value=payload))
    else:
        row.value = payload
        row.updated_at = utcnow()
    db.flush()
