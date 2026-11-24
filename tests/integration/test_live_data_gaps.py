"""Canlı veri testinden (24 Kasım 2026, LiteAPI sandbox) çıkan veri boşluğu kuralları."""
from datetime import date, timedelta

from app.models import Hotel, RoomType
from app.services.pricing import generate_for_hotel


def test_no_suggestion_when_neither_competitor_nor_own_price(db, demo_hotel):
    # Rakibi ve gözlenmiş kendi fiyatı olmayan otel (canlı testte kışın kapalı rakipler, €73 bulgusu)
    h = Hotel(source_id="test-yalniz", name="Yalnız Otel", province="İzmir", district="Çeşme", lat=38.3, lng=26.3)
    db.add(h)
    db.flush()
    db.add(RoomType(hotel_id=h.id, raw_name="Standart Oda", category="standard", mapped_by="rule",
                    confidence=1.0, reviewed=True))
    db.flush()
    start = date.today()
    assert generate_for_hotel(db, h, start, start + timedelta(days=6), persist=False) == []
    # Verisi olan otel etkilenmez
    assert generate_for_hotel(db, demo_hotel, start, start + timedelta(days=6), persist=False)


def test_no_competitor_price_is_said_plainly():
    """Rakip fiyatı yokken 'Rakip medyanı €X' ya da 'benzer oteller €X civarında' denmez."""
    from app.services.pricing import PricingInputs, compute

    res = compute(PricingInputs(comp_prices=[], own_price=114.0, demand_score=50, season_coef=1.0))
    r = res.rationale
    assert r["comp_count"] == 0 and r["comp_median"] is None and r["comp_p90"] is None
    assert r["change_vs_median_pct"] is None
    assert "rakip fiyatı yok" in r["text"] and "benzer oteller" not in r["headline"]
    assert "Rakip medyan fiyat" not in r["text"]
