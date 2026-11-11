"""Önerinin uygulanıp uygulanmadığını otomatik tespit eder, sonucunu ölçer ve motoru besler.

- Tespit: abone otelin satış kanalında gözlenen fiyatı önerilen fiyatla karşılaştırılır
  (otel elle işaretlemez).
- Sonuç: karar anı ile konaklama günü arasındaki tahmini doluluk değişimi (abone ve rakip medyanı)
  ve RevPAR endeksi (abone RevPAR / rakip RevPAR). Tümü TAHMİNDİR.
- Geri besleme: uygulanan artış ve indirimlerin rakiplere göre pay etkisinden ağırlıklar haftalık
  olarak sınırlı adımlarla ayarlanır.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting, AuditLog, Hotel, PriceSuggestion, RoomType, StayOutcome, utcnow
from app.services.market import _aware, all_observations, category_price_by_hotel, compset_ids
from app.services.occupancy import hotel_occupancy, median_occ

STATUS_LABELS = {
    "applied": "Uygulandı",
    "partial": "Kısmen uygulandı",
    "not_applied": "Uygulanmadı",
    "unobserved": "Fiyatınız henüz gözlenmedi",
}
MIN_TUNE_SAMPLE = 30
TUNE_STEP = 0.10


def classify(sugg: float, observed: float | None, before: float | None, tol: float) -> str:
    """Gözlenen fiyat öneriye göre: applied / partial / not_applied / unobserved."""
    if observed is None:
        return "unobserved"
    if abs(observed - sugg) / sugg <= tol:
        return "applied"
    if before is not None and abs(before - sugg) > 0 and abs(observed - before) > 0.005 * before:
        if abs(observed - sugg) <= 0.5 * abs(before - sugg) and (observed - before) * (sugg - before) > 0:
            return "partial"
    return "not_applied"


def evaluate_outcomes(db: Session, hotel: Hotel, today: date | None = None, lookback_days: int = 45,
                      horizon_days: int = 60) -> int:
    today = today or date.today()
    tol = float(hotel.settings.tolerance_pct) / 100 if hotel.settings else 0.05
    rts = list(db.execute(select(RoomType).where(RoomType.hotel_id == hotel.id)).scalars())
    if not rts:
        return 0
    rt_ids = [r.id for r in rts]
    rt_cat = {r.id: r.category or "other" for r in rts}
    start, end = today - timedelta(days=lookback_days), today + timedelta(days=horizon_days)
    comp_ids = compset_ids(db, hotel.id)

    sugg: dict[tuple[int, date], list[tuple[datetime, int, float]]] = defaultdict(list)
    for sid, rt, stay, created, price in db.execute(
        select(PriceSuggestion.id, PriceSuggestion.room_type_id, PriceSuggestion.stay_date,
               PriceSuggestion.created_at, PriceSuggestion.suggested_price)
        .where(PriceSuggestion.room_type_id.in_(rt_ids), PriceSuggestion.stay_date >= start,
               PriceSuggestion.stay_date <= end)
    ):
        sugg[(rt, stay)].append((_aware(created), sid, float(price)))
    if not sugg:
        return 0
    for v in sugg.values():
        v.sort()
    own_obs = all_observations(db, rt_ids, start, end)
    existing = {(o.room_type_id, o.stay_date): o for o in db.execute(
        select(StayOutcome).where(StayOutcome.room_type_id.in_(rt_ids), StayOutcome.stay_date >= start,
                                  StayOutcome.stay_date <= end)).scalars()}

    occ_cache: dict[date, dict[int, dict]] = {}

    def occ_at(as_of: date) -> dict[int, dict]:
        if as_of not in occ_cache:
            occ_cache[as_of] = hotel_occupancy(db, [hotel.id] + comp_ids, start, end, as_of)
        return occ_cache[as_of]

    comp_prices: dict[str, dict[int, dict]] = {}
    n = 0
    for (rt, stay), lst in sugg.items():
        first_at, _, _ = lst[0]
        obs = [o for o in own_obs.get((rt, stay), []) if o.price_eur]
        before = [o for o in obs if o.observed_at < first_at]
        after = [o for o in obs if o.observed_at >= first_at + timedelta(hours=1)]
        latest = after[-1] if after else None
        # gözlem anından önceki son öneri
        ref = lst[-1]
        if latest is not None:
            prior = [s for s in lst if s[0] <= latest.observed_at - timedelta(hours=1)]
            ref = prior[-1] if prior else lst[0]
        _, ref_id, ref_price = ref
        price_before = before[-1].price_eur if before else None
        status = classify(ref_price, latest.price_eur if latest else None, price_before, tol)
        applied_at = None
        if status == "applied":
            applied_at = next((o.observed_at for o in after
                               if abs(o.price_eur - ref_price) / ref_price <= tol), latest.observed_at)
        decision_day = (applied_at or first_at).date()
        end_day = min(stay, today)
        o_start, o_end = occ_at(min(decision_day, end_day)), occ_at(end_day)
        own_s, own_e = o_start.get(hotel.id, {}).get(stay), o_end.get(hotel.id, {}).get(stay)
        comp_s = median_occ([o_start.get(c, {}).get(stay) for c in comp_ids])
        comp_e = median_occ([o_end.get(c, {}).get(stay) for c in comp_ids])
        cat = rt_cat[rt]
        if cat not in comp_prices:
            comp_prices[cat] = category_price_by_hotel(db, comp_ids, cat, start, end, today)
        cp = [comp_prices[cat].get(c, {}).get(stay) for c in comp_ids]
        cp_vals = [o.price_eur for o in cp if o and o.price_eur]
        comp_price = statistics.median(cp_vals) if cp_vals else None
        idx = None
        if latest and own_e and comp_e and comp_price:
            idx = round((latest.price_eur * own_e.occ) / (comp_price * comp_e), 3)

        row = existing.get((rt, stay))
        if row is None:
            row = StayOutcome(hotel_id=hotel.id, room_type_id=rt, stay_date=stay)
            db.add(row)
        row.suggestion_id, row.status, row.first_suggested_at, row.applied_at = ref_id, status, first_at, applied_at
        row.suggested_price, row.price_before = ref_price, price_before
        row.observed_price = latest.price_eur if latest else None
        row.own_occ_start, row.own_occ_end = (own_s.occ if own_s else None), (own_e.occ if own_e else None)
        row.comp_occ_start, row.comp_occ_end = comp_s, comp_e
        row.comp_price, row.revpar_index = comp_price, idx
        row.is_final = stay < today
        row.evaluated_at = utcnow()
        n += 1
    db.flush()
    return n


def status_map(db: Session, room_type_ids: list[int], start: date, end: date) -> dict[tuple[int, date], StayOutcome]:
    if not room_type_ids:
        return {}
    return {(o.room_type_id, o.stay_date): o for o in db.execute(
        select(StayOutcome).where(StayOutcome.room_type_id.in_(room_type_ids), StayOutcome.stay_date >= start,
                                  StayOutcome.stay_date <= end)).scalars()}


def _conf(n_a: int, n_b: int) -> str:
    m = min(n_a, n_b)
    return "high" if m >= 30 else "medium" if m >= 10 else "low"


def outcome_summary(db: Session, hotel_id: int, days: int = 60, today: date | None = None) -> dict:
    """Panel için: tespit edilen uygulama oranı ve uygulanan/uygulanmayan günlerin RevPAR endeksi."""
    today = today or date.today()
    rows = list(db.execute(select(StayOutcome).where(
        StayOutcome.hotel_id == hotel_id, StayOutcome.stay_date >= today - timedelta(days=days),
        StayOutcome.stay_date <= today + timedelta(days=60))).scalars())
    counts = {k: 0 for k in STATUS_LABELS}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    observed = counts["applied"] + counts["partial"] + counts["not_applied"]
    final = [r for r in rows if r.is_final and r.revpar_index is not None]
    applied = [float(r.revpar_index) for r in final if r.status in ("applied", "partial")]
    other = [float(r.revpar_index) for r in final if r.status == "not_applied"]
    rp_a = [r.relative_pickup for r in final if r.status in ("applied", "partial") and r.relative_pickup is not None]
    rp_o = [r.relative_pickup for r in final if r.status == "not_applied" and r.relative_pickup is not None]
    idx_a = round(statistics.fmean(applied), 3) if applied else None
    idx_o = round(statistics.fmean(other), 3) if other else None
    return {
        "counts": counts,
        "observed": observed,
        "applied_rate": round((counts["applied"] + counts["partial"]) / observed * 100, 1) if observed else None,
        "index_applied": idx_a, "index_other": idx_o,
        "n_applied": len(applied), "n_other": len(other),
        "pickup_applied": round(statistics.fmean(rp_a) * 100, 1) if rp_a else None,
        "pickup_other": round(statistics.fmean(rp_o) * 100, 1) if rp_o else None,
        "uplift_pct": round((idx_a / idx_o - 1) * 100, 1) if idx_a and idx_o else None,
        "confidence": _conf(len(applied), len(other)),
    }


def tune_weights(db: Session, today: date | None = None, lookback_days: int = 90) -> dict:
    """Uygulanan önerilerin sonuçlarına göre motor ağırlıklarını sınırlı adımlarla ayarlar."""
    from app.services.pricing import DEFAULT_WEIGHTS, load_weights

    today = today or date.today()
    rows = list(db.execute(select(StayOutcome).where(
        StayOutcome.is_final.is_(True), StayOutcome.status.in_(("applied", "partial")),
        StayOutcome.stay_date >= today - timedelta(days=lookback_days), StayOutcome.stay_date < today)).scalars())
    ups, downs = [], []
    for r in rows:
        rp = r.relative_pickup
        if rp is None or r.price_before is None or r.suggested_price is None:
            continue
        before, sugg = float(r.price_before), float(r.suggested_price)
        if sugg > before * 1.01:
            ups.append((rp, float(r.comp_occ_end or 0)))
        elif sugg < before * 0.99:
            downs.append(rp)
    w = load_weights(db)
    new = dict(w)

    def scale(keys: tuple[str, ...], factor: float) -> None:
        for k in keys:
            base = DEFAULT_WEIGHTS[k]
            new[k] = round(max(base * 0.5, min(base * 1.5, new[k] * factor)), 4)

    reasons = []
    if len(ups) >= MIN_TUNE_SAMPLE:
        m = statistics.fmean(rp for rp, _ in ups)
        market = statistics.fmean(c for _, c in ups)
        if m < -0.08:
            scale(("demand", "occupancy", "compression", "max_up"), 1 - TUNE_STEP)
            reasons.append(f"Artışlar uygulanan günlerde rakiplere göre doluluk {m * 100:.1f} puan geriledi")
        elif m > -0.02 and market >= 0.7:
            scale(("demand", "occupancy", "compression", "max_up"), 1 + TUNE_STEP)
            reasons.append("Artışlar pay kaybettirmedi ve pazar dolu")
    if len(downs) >= MIN_TUNE_SAMPLE:
        m = statistics.fmean(downs)
        if m <= 0:
            scale(("max_down",), 1 - TUNE_STEP)
            reasons.append("İndirimler rakiplere göre ek doluluk getirmedi")
        elif m > 0.05:
            scale(("max_down",), 1 + TUNE_STEP)
            reasons.append(f"İndirimler rakiplere göre {m * 100:.1f} puan ek doluluk getirdi")
    changed = {k: (w[k], new[k]) for k in DEFAULT_WEIGHTS if new.get(k) != w.get(k)}
    if changed:
        row = db.get(AppSetting, "pricing_weights")
        if row is None:
            row = AppSetting(key="pricing_weights", value={})
            db.add(row)
        row.value = {k: new[k] for k in DEFAULT_WEIGHTS}
        row.updated_at = utcnow()
        db.add(AuditLog(action="weights_tuned", entity="pricing_weights",
                        details={"changes": changed, "reasons": reasons, "n_up": len(ups), "n_down": len(downs)}))
        db.flush()
    return {"changed": changed, "reasons": reasons, "n_up": len(ups), "n_down": len(downs)}
