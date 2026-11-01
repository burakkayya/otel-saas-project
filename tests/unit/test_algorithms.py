"""Algoritma birim testleri: oda eşleme, fiyat motoru, compset, talep, sezon."""
from datetime import date

import pytest

from app.services import calendar_tr, demand, seasonality
from app.services.compset import haversine_km
from app.services.pricing import PricingInputs, compute, inventory_pressure
from app.services.room_mapping import REVIEW_THRESHOLD, map_by_rules, map_room, normalize


# --------------------------------------------------------------------------- oda eşleme
@pytest.mark.parametrize("raw,cat", [
    ("Standart Oda", "standard"),
    ("Standard Double Room", "standard"),
    ("Klasik Çift Kişilik", "standard"),
    ("Deluxe Deniz Manzaralı", "deluxe"),
    ("Delüks Oda", "deluxe"),
    ("Superior Room Sea View", "deluxe"),
    ("Junior Suite", "suite"),
    ("Süit Oda", "suite"),
    ("Aile Odası", "family"),
    ("Family Room (2+2)", "family"),
    ("Connecting Family Room", "family"),
])
def test_rule_mapping(raw, cat):
    res = map_room(raw, use_llm=False)
    assert res.category == cat
    assert res.mapped_by == "rule"


def test_ambiguous_room_goes_to_review():
    res = map_room("Penthouse Loft", use_llm=False)
    assert res.category == "other"
    assert res.confidence < REVIEW_THRESHOLD


def test_family_beats_deluxe_when_both_present():
    assert map_by_rules("Deluxe Family Room").category == "family"


def test_normalize_turkish():
    assert normalize("ÇİFT KİŞİLİK Süit!") == "cift kisilik suit"


def test_llm_not_called_without_key(monkeypatch):
    from app.services import room_mapping

    called = []
    monkeypatch.setattr(room_mapping.httpx, "post", lambda *a, **k: called.append(1))
    assert room_mapping.map_by_llm("Taş Ev") is None
    assert not called


def test_llm_mapping_with_key(monkeypatch):
    from app.services import room_mapping

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"text": 'Sonuç: {"category": "suite", "confidence": 0.81}'}]}

    monkeypatch.setattr(room_mapping.settings, "llm_api_key", "x")
    monkeypatch.setattr(room_mapping.httpx, "post", lambda *a, **k: Resp())
    res = room_mapping.map_room("Taş Ev")
    assert (res.category, res.mapped_by, res.confidence) == ("suite", "llm", 0.81)


def test_llm_failure_falls_back(monkeypatch):
    from app.services import room_mapping

    def boom(*a, **k):
        raise RuntimeError("ağ hatası")

    monkeypatch.setattr(room_mapping.settings, "llm_api_key", "x")
    monkeypatch.setattr(room_mapping.httpx, "post", boom)
    assert room_mapping.map_room("Garden Villa").category == "other"


# --------------------------------------------------------------------------- fiyat motoru
def _inp(**kw):
    base = dict(comp_prices=[100, 110, 120, 130, 140], demand_score=50, season_coef=1.0)
    base.update(kw)
    return PricingInputs(**base)


def test_neutral_inputs_return_median():
    res = compute(_inp())
    assert res.price == 120
    assert res.floor <= res.price <= res.ceiling
    assert res.rationale["comp_count"] == 5
    assert res.rationale["confidence"] == "high"


def test_high_demand_raises_price():
    assert compute(_inp(demand_score=95)).price > compute(_inp(demand_score=50)).price


def test_low_demand_lowers_price():
    assert compute(_inp(demand_score=5)).price < compute(_inp(demand_score=50)).price


def test_strategy_scales_adjustment():
    agg = compute(_inp(demand_score=90, strategy="aggressive")).price
    bal = compute(_inp(demand_score=90, strategy="balanced")).price
    con = compute(_inp(demand_score=90, strategy="conservative")).price
    assert agg >= bal >= con


def test_price_never_leaves_hotel_bounds():
    res = compute(_inp(demand_score=100, max_price=105))
    assert res.price <= 105 and res.ceiling == 105
    res = compute(_inp(demand_score=0, min_price=150, comp_prices=[80, 90, 100]))
    assert res.price >= 150 and res.floor == 150


def test_floor_and_ceiling_derived_from_distribution():
    res = compute(_inp(floor_below_p25_pct=10, ceiling_margin_pct=5))
    assert res.floor == round(110 * 0.9)
    assert res.ceiling == round(res.rationale["comp_p90"] * 1.05)


def test_high_season_widens_ceiling():
    low = compute(_inp(season_coef=1.0)).ceiling
    high = compute(_inp(season_coef=1.5)).ceiling
    assert high > low


def test_dead_season_moves_towards_floor():
    normal = compute(_inp(season_coef=0.85)).price
    dead = compute(_inp(season_coef=0.6)).price
    assert dead < normal


def test_no_competitors_uses_fallback_with_low_confidence():
    res = compute(PricingInputs(comp_prices=[], own_price=90))
    assert res.rationale["confidence"] == "low"
    assert 70 <= res.price <= 110


def test_position_index_scales_anchor():
    res = compute(_inp(position_index=0.5))
    assert res.price == 60
    assert res.rationale["comp_median"] == 120
    assert res.rationale["anchor_price"] == 60
    assert "konumlama endeksi 0,50" in res.rationale["text"]


def test_median_change_uses_same_competitors():
    res = compute(_inp(comp_pairs=[(110, 100), (132, 120), (99, 90)]))
    assert res.rationale["comp_median_change_7d_pct"] == pytest.approx(10.0, abs=0.1)


def test_rationale_text_is_turkish_and_complete():
    res = compute(_inp(own_price=100, demand_score=80))
    t = res.rationale["text"]
    assert "talep skoru" in t and "taban €" in t and "tavan €" in t
    assert "mevcut fiyatınıza göre +\u2060%" in t
    assert res.rationale["wtp_note"].startswith("Ödeme istekliliği")


def test_inventory_pressure_bounds():
    assert inventory_pressure([2, 2], [10, 10]) == 1.0
    assert inventory_pressure([10, 10], [10, 10]) == 0.0
    assert inventory_pressure([], []) == 0.0
    assert inventory_pressure([], [], closed=2, total=4) > 0
    assert -1 <= inventory_pressure([20], [5]) <= 0


def test_max_up_cap():
    res = compute(_inp(demand_score=100, strategy="aggressive"), weights={"demand": 0.9, "max_up": 0.1})
    assert res.rationale["adjustments_pct"]["total"] == pytest.approx(10.0)


# --------------------------------------------------------------------------- compset, takvim, sezon
def test_haversine_known_distance():
    # Bodrum merkez - Marmaris merkez ~ 77 km
    assert 70 < haversine_km(37.0344, 27.4305, 36.855, 28.274) < 85
    assert haversine_km(None, None, 1, 1) == 999.0


def test_holidays():
    assert calendar_tr.holiday_name(date(2026, 10, 29)) == "Cumhuriyet Bayramı"
    assert calendar_tr.holiday_score(date(2026, 5, 28)) >= 70  # Kurban Bayramı
    assert calendar_tr.holiday_score(date(2026, 11, 4)) == 0  # sıradan çarşamba
    assert calendar_tr.is_school_break(date(2026, 7, 15))
    assert len(calendar_tr.holidays_between(date(2026, 1, 1), date(2026, 12, 31))) >= 12


def test_demand_combine_and_levels():
    assert demand.combine(100, 100, 100) == 100
    assert demand.combine(0, 0, 0) == 0
    assert demand.combine(50, 50, 50) == 50
    assert demand.demand_level(75) == "Çok yüksek"
    assert demand.demand_level(10) == "Çok düşük"


def test_season_helpers():
    assert seasonality.profile_for("Muğla", "Bodrum") == "summer"
    assert seasonality.profile_for("Antalya", None) == "antalya"
    assert seasonality.profile_for("Nevşehir", None) == "kapadokya"
    assert seasonality.season_label(0.6) == "Ölü sezon"
    assert seasonality.season_label(1.0) == "Omuz sezon"
    assert seasonality.season_label(1.4) == "Yüksek sezon"
