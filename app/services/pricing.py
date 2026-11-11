"""Fiyat öneri motoru. Doküman 5.4.

Girdiler: rakip medyanı ve dağılımı, abone ve rakiplerin tahmini doluluğu, kalan oda hızı,
talep skoru, mevsim katsayısı.
Çıktılar: önerilen fiyat, taban, tavan, gerekçe (JSON). Öneri taban/tavan dışına çıkamaz.

"Maksimum kâr" hedefi, ödeme istekliliği üst sınırı tahmini olarak uygulanır. Bu üst
sınır yalnızca rakip fiyat dağılımından (P90) türetilir; dönüşüm verisi olmadığı için
gerçek ödeme istekliliği ölçülmez. Bu durum panelde açıkça belirtilir.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting, Hotel, HotelSettings, PriceSuggestion, RoomType
from app.services.compset import build_compset
from app.services.demand import demand_level, demand_map
from app.services.market import category_price_by_hotel, compset_ids, latest_observations
from app.services.occupancy import compset_occupancy
from app.services.seasonality import coefficient_for, monthly_coefficients, season_label

MODEL_VERSION = "v1.0-rules"

DEFAULT_WEIGHTS = {
    "demand": 0.05,      # talep skoru 100 iken +%5, 0 iken -%5
    "inventory": 0.06,   # rakiplerin hızla dolması
    "season": 0.04,      # medyanın ötesindeki mevsim etkisi (küçük; medyan zaten mevsimi yansıtır)
    "occupancy": 0.08,   # abone rakiplerden 25 puan daha doluysa +%8, geride ise -%8
    "compression": 0.05, # pazar sıkışması (rakipler %85+ dolu) ya da son dakika boşluğu
    "max_up": 0.30,
    "max_down": 0.25,
}
STRATEGY_MULT = {"conservative": 0.6, "balanced": 1.0, "aggressive": 1.4}
STRATEGY_LABEL = {"conservative": "Temkinli", "balanced": "Dengeli", "aggressive": "Agresif"}


@dataclass
class PricingInputs:
    comp_prices: list[float]
    comp_prices_prev: list[float] = field(default_factory=list)
    comp_pairs: list[tuple[float, float]] = field(default_factory=list)  # (şimdi, 7 gün önce) aynı rakip
    comp_avail_now: list[int] = field(default_factory=list)
    comp_avail_prev: list[int] = field(default_factory=list)
    comp_closed: int = 0
    demand_score: float = 50.0
    season_coef: float = 1.0
    own_price: float | None = None
    lead_days: int = 0
    strategy: str = "balanced"
    min_price: float | None = None
    max_price: float | None = None
    floor_below_p25_pct: float = 10.0
    ceiling_margin_pct: float = 5.0
    fallback_price: float | None = None  # rakip verisi yoksa (bölge medyanı)
    position_index: float = 1.0  # otelin tarihsel fiyatı / rakip medyanı (konumlama)
    own_occ: float | None = None   # abone otelin tahmini doluluğu (0..1)
    comp_occ: float | None = None  # rakiplerin medyan tahmini doluluğu (0..1)
    own_occ_7d: float | None = None
    comp_occ_7d: float | None = None


def occupancy_adjustment(own: float | None, comp: float | None, lead_days: int, w_occ: float,
                         w_comp: float) -> tuple[float, float]:
    """(göreli doluluk ayarı, sıkışma ayarı). Veri yoksa (0, 0)."""
    adj_rel = 0.0
    if own is not None and comp is not None:
        adj_rel = w_occ * max(-1.0, min(1.0, (own - comp) / 0.25))
    adj_comp = 0.0
    if comp is not None:
        if comp >= 0.85:
            adj_comp = w_comp * min(1.0, (comp - 0.85) / 0.15)
        elif comp < 0.35 and lead_days <= 14:
            adj_comp = -w_comp * (0.35 - comp) / 0.35
    return adj_rel, adj_comp


@dataclass
class PricingResult:
    price: float
    floor: float
    ceiling: float
    rationale: dict


def _quantile(values: list[float], q: float) -> float:
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def inventory_pressure(now: list[int], prev: list[int], closed: int = 0, total: int | None = None) -> float:
    """[-1, 1]: rakiplerin kalan odası hızla azalıyorsa pozitif, artıyorsa negatif.
    NOT: Kalan oda düşüşü satış kanıtı değildir (stop-sell, başka kanal vb.);
    yalnızca yön sinyali olarak kullanılır."""
    pairs = [(n, p) for n, p in zip(now, prev) if p and p > 0 and n is not None]
    if not pairs:
        base = 0.0
    else:
        base = statistics.fmean((p - n) / p for n, p in pairs)
    total = total or (len(now) + closed) or 1
    base += 0.3 * closed / total
    return round(max(-1.0, min(1.0, base * 1.5)), 3)


def compute(inp: PricingInputs, weights: dict | None = None) -> PricingResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    prices = [p for p in inp.comp_prices if p and p > 0]
    confidence = "high" if len(prices) >= 4 else "medium" if len(prices) >= 2 else "low"
    pi = max(0.5, min(1.8, inp.position_index or 1.0))
    if prices:
        # Rakip dağılımı otelin konumlama endeksiyle ölçeklenir (ör. pansiyon ile resort aynı fiyatlanmaz)
        median = statistics.median(prices) * pi
        p25, p75, p90 = (_quantile(prices, q) * pi for q in (0.25, 0.75, 0.9))
    else:
        median = inp.fallback_price or inp.own_price or 80.0
        p25, p75, p90 = median * 0.85, median * 1.15, median * 1.3

    if inp.comp_pairs:
        pairs = [(a, b) for a, b in inp.comp_pairs if a and b]
        median_change = round((statistics.median(a for a, _ in pairs) / statistics.median(b for _, b in pairs) - 1) * 100, 1) if pairs else None
    else:
        prev = [p for p in inp.comp_prices_prev if p and p > 0]
        median_change = round((statistics.median(prices) / statistics.median(prev) - 1) * 100, 1) if prev and prices else None

    pressure = inventory_pressure(inp.comp_avail_now, inp.comp_avail_prev, inp.comp_closed)
    mult = STRATEGY_MULT.get(inp.strategy, 1.0)
    adj_demand = w["demand"] * (inp.demand_score - 50) / 50
    adj_inv = w["inventory"] * pressure
    adj_season = w["season"] * (inp.season_coef - 1)
    adj_occ, adj_compress = occupancy_adjustment(inp.own_occ, inp.comp_occ, inp.lead_days,
                                                 w.get("occupancy", 0.0), w.get("compression", 0.0))
    total = max(-w["max_down"], min(w["max_up"], mult * (adj_demand + adj_inv + adj_season + adj_occ + adj_compress)))
    raw = median * (1 + total)

    floor = p25 * (1 - inp.floor_below_p25_pct / 100)
    dead_season = inp.season_coef < 0.8
    if dead_season:
        raw = raw - (raw - floor) * 0.25  # ölü sezonda tabana yaklaş
    margin = inp.ceiling_margin_pct / 100 + max(0.0, inp.season_coef - 1) * 0.20  # yüksek sezonda marj artar
    wtp_upper = p90
    ceiling = wtp_upper * (1 + margin)
    if inp.min_price:
        floor = max(floor, inp.min_price)
    if inp.max_price:
        ceiling = min(ceiling, inp.max_price)
    if ceiling < floor:
        ceiling = floor
    price = round(max(floor, min(ceiling, raw)))
    floor, ceiling = round(floor), round(ceiling)
    price = max(floor, min(ceiling, price))
    clamped = "floor" if price == floor and raw < floor else "ceiling" if price == ceiling and raw > ceiling else None

    change_vs_own = round((price / inp.own_price - 1) * 100, 1) if inp.own_price else None
    change_vs_median = round((price / (median / pi) - 1) * 100, 1)

    parts = []
    if median_change is not None and abs(median_change) >= 1:
        parts.append(f"Rakip medyan fiyat son 7 günde %{abs(median_change):.0f} {'arttı' if median_change > 0 else 'azaldı'}")
    else:
        parts.append("Rakip medyan fiyat son 7 günde yatay")
    if inp.comp_occ is not None and inp.own_occ is not None:
        parts.append(f"tahmini doluluk sizde %{inp.own_occ * 100:.0f}, rakiplerde %{inp.comp_occ * 100:.0f}")
    elif inp.comp_occ is not None:
        parts.append(f"rakiplerin tahmini doluluğu %{inp.comp_occ * 100:.0f}")
    if inp.comp_occ is not None and inp.comp_occ >= 0.85:
        parts.append("pazar sıkışıyor")
    parts.append(f"talep skoru {demand_level(inp.demand_score).lower()} ({inp.demand_score:.0f})")
    if abs(pressure) >= 0.15:
        parts.append("rakiplerde kalan oda hızla azalıyor" if pressure > 0 else "rakiplerde kalan oda artıyor")
    parts.append(season_label(inp.season_coef).lower())
    if abs(pi - 1) >= 0.05:
        parts.append(f"konumlama endeksi {pi:.2f} (fiyatınız tarihsel olarak rakip medyanının %{pi * 100:.0f} düzeyinde)".replace(".", ",", 1))
    if change_vs_own is not None:
        parts.append(f"öneri mevcut fiyatınıza göre {'+' if change_vs_own >= 0 else '−'}\u2060%{abs(change_vs_own):.0f}")
    else:
        parts.append(f"öneri rakip medyanına göre {'+' if change_vs_median >= 0 else '−'}\u2060%{abs(change_vs_median):.0f}")
    parts.append(f"taban €{floor:.0f}, tavan €{ceiling:.0f}")
    text = ", ".join(parts) + "."
    text = text[0].upper() + text[1:]

    rationale = {
        "text": text,
        "comp_count": len(prices),
        "comp_median": round(median / pi, 2),
        "anchor_price": round(median, 2),
        "position_index": round(pi, 3),
        "comp_p25": round(p25 / pi, 2),
        "comp_p75": round(p75 / pi, 2),
        "comp_p90": round(p90 / pi, 2),
        "comp_min": round(min(prices), 2) if prices else None,
        "comp_max": round(max(prices), 2) if prices else None,
        "comp_median_change_7d_pct": median_change,
        "demand_score": round(inp.demand_score, 1),
        "demand_level": demand_level(inp.demand_score),
        "season_coef": round(inp.season_coef, 3),
        "season_label": season_label(inp.season_coef),
        "inventory_pressure": pressure,
        "comp_closed": inp.comp_closed,
        "adjustments_pct": {
            "demand": round(mult * adj_demand * 100, 2),
            "inventory": round(mult * adj_inv * 100, 2),
            "season": round(mult * adj_season * 100, 2),
            "occupancy": round(mult * adj_occ * 100, 2),
            "compression": round(mult * adj_compress * 100, 2),
            "total": round(total * 100, 2),
        },
        "own_occ": inp.own_occ,
        "comp_occ": inp.comp_occ,
        "own_occ_7d": inp.own_occ_7d,
        "comp_occ_7d": inp.comp_occ_7d,
        "occ_note": "Doluluk satış kanalındaki açık oda sayısından tahmin edilir; kesin değer değildir.",
        "strategy": inp.strategy,
        "own_price": inp.own_price,
        "change_vs_own_pct": change_vs_own,
        "change_vs_median_pct": change_vs_median,
        "wtp_upper_estimate": round(wtp_upper, 2),
        "wtp_note": "Ödeme istekliliği üst sınırı yalnızca rakip fiyat dağılımından (P90) tahmin edilir; dönüşüm verisi yoktur.",
        "clamped": clamped,
        "confidence": confidence,
        "lead_days": inp.lead_days,
    }
    return PricingResult(float(price), float(floor), float(ceiling), rationale)


def position_index(db: Session, hotel_id: int, comp_ids: list[int], category: str, as_of: date,
                   lookback: int = 60) -> float:
    """Otelin son 60 gündeki fiyatının aynı tarihlerdeki rakip medyanına oranı (medyan).
    Abonelik sonrası önerilere uyum bu endeksi zamanla öneriye yaklaştırır; bu yüzden
    yalnızca as_of öncesi gözlenen veri kullanılır."""
    start, end = as_of - timedelta(days=lookback), as_of + timedelta(days=30)
    own = category_price_by_hotel(db, [hotel_id], category, start, end, as_of).get(hotel_id, {})
    if not own:
        return 1.0
    comps = category_price_by_hotel(db, comp_ids, category, start, end, as_of)
    ratios = []
    for d, o in own.items():
        if not o.price_eur:
            continue
        cp = [comps[c][d].price_eur for c in comp_ids if d in comps.get(c, {}) and comps[c][d].price_eur]
        if len(cp) >= 2:
            ratios.append(o.price_eur / statistics.median(cp))
    if len(ratios) < 5:
        return 1.0
    return round(statistics.median(ratios), 3)


def load_weights(db: Session) -> dict:
    row = db.get(AppSetting, "pricing_weights")
    return {**DEFAULT_WEIGHTS, **(row.value if row and isinstance(row.value, dict) else {})}


def current_model_version(db: Session) -> str:
    row = db.get(AppSetting, "model_version")
    return str(row.value) if row and row.value else MODEL_VERSION


def generate_for_hotel(
    db: Session, hotel: Hotel, start: date, end: date, as_of: date | None = None, persist: bool = True,
    created_at=None, coefs: list[float] | None = None, weights: dict | None = None,
) -> list[PriceSuggestion]:
    as_of = as_of or date.today()
    comp_ids = compset_ids(db, hotel.id)
    if not comp_ids:
        build_compset(db, hotel, today=as_of)
        comp_ids = compset_ids(db, hotel.id)
    hs: HotelSettings | None = hotel.settings
    weights = weights or load_weights(db)
    version = current_model_version(db)
    demand = demand_map(db, hotel.province, start, end)
    if coefs is None:
        coefs = monthly_coefficients(db, hotel.province, hotel.district, today=as_of)["coef"]
    own_rts = list(db.execute(select(RoomType).where(RoomType.hotel_id == hotel.id)).scalars())
    own_latest = latest_observations(db, [r.id for r in own_rts], start, end, as_of)
    occ = compset_occupancy(db, hotel.id, comp_ids, start, end, as_of)

    cache: dict[str, tuple] = {}
    pi_cache: dict[str, float] = {}
    out: list[PriceSuggestion] = []
    for rt in own_rts:
        cat = rt.category or "other"
        if cat not in cache:
            now = category_price_by_hotel(db, comp_ids, cat, start, end, as_of)
            prev = category_price_by_hotel(db, comp_ids, cat, start, end, as_of - timedelta(days=7))
            cache[cat] = (now, prev)
        now, prev = cache[cat]
        if cat not in pi_cache:
            pi_cache[cat] = position_index(db, hotel.id, comp_ids, cat, as_of)
        if not any(now.get(c) for c in comp_ids) and cat == "other":
            continue  # 'diğer' kategoride kıyaslanacak rakip yoksa öneri üretme
        d = start
        while d <= end:
            comp_now = [now.get(c, {}).get(d) for c in comp_ids]
            comp_prev = [prev.get(c, {}).get(d) for c in comp_ids]
            closed = sum(1 for o in comp_now if o is not None and o.price_eur is None)
            own = own_latest.get((rt.id, d))
            ds = demand.get(d)
            inp = PricingInputs(
                comp_prices=[o.price_eur for o in comp_now if o and o.price_eur],
                comp_prices_prev=[o.price_eur for o in comp_prev if o and o.price_eur],
                comp_pairs=[(o.price_eur, p.price_eur) for o, p in zip(comp_now, comp_prev)
                            if o and p and o.price_eur and p.price_eur],
                comp_avail_now=[o.available for o, p in zip(comp_now, comp_prev) if o and p and o.available is not None],
                comp_avail_prev=[p.available for o, p in zip(comp_now, comp_prev) if o and p and o.available is not None],
                comp_closed=closed,
                demand_score=float(ds.demand_score) if ds else 50.0,
                season_coef=coefficient_for(coefs, d),
                own_price=own.price_eur if own else None,
                lead_days=(d - as_of).days,
                strategy=hs.strategy if hs else "balanced",
                min_price=float(hs.min_price_eur) if hs and hs.min_price_eur else None,
                max_price=float(hs.max_price_eur) if hs and hs.max_price_eur else None,
                floor_below_p25_pct=float(hs.floor_below_p25_pct) if hs else 10.0,
                ceiling_margin_pct=float(hs.ceiling_margin_pct) if hs else 5.0,
                position_index=pi_cache[cat],
                own_occ=(occ.get(d) or {}).get("own"),
                comp_occ=(occ.get(d) or {}).get("comp"),
                own_occ_7d=(occ.get(d) or {}).get("own_7d"),
                comp_occ_7d=(occ.get(d) or {}).get("comp_7d"),
            )
            res = compute(inp, weights)
            res.rationale["as_of"] = as_of.isoformat()
            res.rationale["demand_components"] = ds.components if ds else None
            s = PriceSuggestion(
                room_type_id=rt.id, stay_date=d, suggested_price=res.price, price_floor=res.floor,
                price_ceiling=res.ceiling, rationale=res.rationale, model_version=version,
            )
            if created_at is not None:
                s.created_at = created_at
            out.append(s)
            d += timedelta(days=1)
    if persist:
        db.add_all(out)
        db.flush()
    return out
