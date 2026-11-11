"""Satış kanalı envanterinden doluluk tahmini (saf hesap)."""
from app.services.occupancy import confidence_for, estimate, median_occ


def test_occupancy_is_share_of_allotment_sold():
    e = estimate(visible=6, allotment=20, closed=False, n_obs=4, allot_dates=30, room_count=60)
    assert e.occ == 0.7
    assert e.confidence == "high" and (e.low, e.high) == (0.64, 0.76)
    assert e.rooms_sold == 42  # 0,7 × 60 oda


def test_closed_inventory_reads_as_full_but_flagged():
    e = estimate(visible=0, allotment=12, closed=True, n_obs=1, allot_dates=3)
    assert e.closed and e.occ >= 0.97
    assert e.confidence == "low" and e.high == 1.0


def test_visible_above_allotment_is_clamped_to_zero():
    e = estimate(visible=30, allotment=20, closed=False, n_obs=2, allot_dates=10)
    assert e.occ == 0.0 and e.low == 0.0 and e.confidence == "medium"


def test_no_allotment_means_no_estimate():
    assert estimate(visible=3, allotment=0, closed=False, n_obs=5, allot_dates=0) is None


def test_confidence_levels_and_median():
    assert confidence_for(3, 20) == "high"
    assert confidence_for(2, 8) == "medium"
    assert confidence_for(1, 40) == "low"
    a = estimate(5, 10, False, 3, 20)
    b = estimate(2, 10, False, 3, 20)
    assert median_occ([a, None, b]) == 0.65
    assert median_occ([None]) is None


def test_engine_raises_when_ahead_of_market_and_lowers_when_behind():
    from app.services.pricing import PricingInputs, compute, occupancy_adjustment

    rel, comp = occupancy_adjustment(0.9, 0.65, 30, 0.08, 0.05)
    assert rel == 0.08 and comp == 0.0
    rel, comp = occupancy_adjustment(0.4, 0.65, 30, 0.08, 0.05)
    assert rel == -0.08
    base = dict(comp_prices=[100, 110, 120, 130], demand_score=50, lead_days=20)
    ahead = compute(PricingInputs(**base, own_occ=0.9, comp_occ=0.65))
    behind = compute(PricingInputs(**base, own_occ=0.4, comp_occ=0.65))
    neutral = compute(PricingInputs(**base))
    assert ahead.price > neutral.price > behind.price
    assert "rakiplerde %65" in ahead.rationale["text"]
    assert ahead.rationale["adjustments_pct"]["occupancy"] > 0


def test_compression_and_last_minute_slack():
    from app.services.pricing import occupancy_adjustment

    _, up = occupancy_adjustment(None, 0.95, 40, 0.08, 0.05)
    assert up > 0.03
    _, down = occupancy_adjustment(None, 0.2, 5, 0.08, 0.05)
    assert down < 0
    _, far = occupancy_adjustment(None, 0.2, 40, 0.08, 0.05)
    assert far == 0.0
