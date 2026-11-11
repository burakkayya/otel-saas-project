"""Rezervasyon hızı (pace), benzerlik ağırlıklı rakip dağılımı, eylem ve senaryo başlığı."""
from datetime import date, timedelta

from app.services.occupancy import build_pace_curve, expected_occupancy
from app.services.pricing import PricingInputs, compute, decide_action, pace_adjustment, weighted_quantile


def _history():
    """60 gün: kalan gün azaldıkça dolan otel (30 gün kala %20, 14: %40, 7: %60, 1: %80)."""
    pts = []
    for i in range(60):
        stay = date(2026, 9, 1) + timedelta(days=i)
        for lead, occ in ((30, 0.2), (14, 0.4), (7, 0.6), (1, 0.8)):
            pts.append((stay, lead, occ + (0.1 if stay.weekday() in (4, 5) else 0.0)))
    return pts


def test_pace_curve_gives_expected_occupancy_by_lead_time():
    curves = build_pace_curve(_history())
    wed, sat = date(2026, 11, 18), date(2026, 11, 21)
    assert expected_occupancy(curves, wed, 30) == 0.2
    assert expected_occupancy(curves, wed, 1) == 0.8
    assert 0.4 < expected_occupancy(curves, wed, 10) < 0.6  # ara değer
    assert expected_occupancy(curves, sat, 7) == 0.7  # hafta sonu ayrı eğri
    assert expected_occupancy(curves, wed, 7, season_ratio=0.5) == 0.3  # sezon düzeltmesi
    assert expected_occupancy({}, wed, 7) is None
    assert build_pace_curve(_history()[:5]) == {}


def test_pace_moves_price_and_names_the_reason():
    assert pace_adjustment(0.78, 0.55, 0.07) == 0.07
    assert round(pace_adjustment(0.45, 0.55, 0.07), 4) == -0.035
    assert pace_adjustment(None, 0.5, 0.07) == 0.0
    base = dict(comp_prices=[100, 110, 120, 130], demand_score=50, lead_days=10, own_price=115)
    ahead = compute(PricingInputs(**base, own_occ=0.78, expected_occ=0.55))
    behind = compute(PricingInputs(**base, own_occ=0.35, expected_occ=0.58))
    flat = compute(PricingInputs(**base, own_occ=0.55, expected_occ=0.55))
    assert ahead.price > flat.price > behind.price
    assert ahead.rationale["scenario"] == "ahead" and "Beklenenden hızlı doluyorsunuz: %78" in ahead.rationale["headline"]
    assert behind.rationale["scenario"] == "behind" and "beklenen %58" in behind.rationale["headline"]
    assert flat.rationale["scenario"] == "on_track"
    assert ahead.rationale["adjustments_pct"]["pace"] > 0 and ahead.rationale["pace_gap"] == 0.23


def test_action_has_a_hold_band():
    assert decide_action(100, 98) == "hold"
    assert decide_action(104, 100) == "raise"
    assert decide_action(96, 100) == "lower"
    assert decide_action(100, None) == "set"
    r = compute(PricingInputs(comp_prices=[100, 110, 120, 130], own_price=114))
    assert r.rationale["action"] == "hold"


def test_own_limit_holding_the_price_is_reported():
    r = compute(PricingInputs(comp_prices=[100, 105, 110, 115], own_price=140, min_price=140))
    assert r.price == 140 and r.rationale["limited_by"] == "min_price"
    assert r.rationale["scenario"] == "limit_min" and "Minimum fiyatınız öneriyi tutuyor" in r.rationale["headline"]
    assert r.rationale["unconstrained_price"] < 140
    r = compute(PricingInputs(comp_prices=[200, 210, 220, 230], own_price=150, max_price=150))
    assert r.rationale["limited_by"] == "max_price" and r.rationale["scenario"] == "limit_max"


def test_similar_competitors_weigh_more():
    prices = [80, 100, 120, 200]
    assert weighted_quantile(prices, [], 0.5) == 110
    heavy_low = weighted_quantile(prices, [3, 3, 1, 0.2], 0.5)
    heavy_high = weighted_quantile(prices, [0.2, 1, 3, 3], 0.5)
    assert heavy_low < 110 < heavy_high
    assert weighted_quantile([90], [2], 0.5) == 90
    a = compute(PricingInputs(comp_prices=prices, comp_weights=[3, 3, 1, 0.2]))
    b = compute(PricingInputs(comp_prices=prices))
    assert a.price < b.price and a.rationale["weighted_comps"] and not b.rationale["weighted_comps"]


def test_compression_outranks_other_reasons():
    r = compute(PricingInputs(comp_prices=[100, 110, 120, 130], own_price=110, own_occ=0.9, comp_occ=0.9,
                              expected_occ=0.5))
    assert r.rationale["scenario"] == "compression" and "Pazar doluyor" in r.rationale["headline"]
