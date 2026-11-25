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


def _isolated_market(db):
    """İzmir'de yalıtılmış küçük pazar: pansiyon (standart €100, deluxe €180), 3 rakip standart €50,
    yalnızca 1 rakipte deluxe €45 (canlı testteki Dinc Pansiyon / Kale Hotel durumu)."""
    from datetime import datetime, time, timezone

    from app.models import CompetitorSet, RateSnapshot

    today = date.today()
    obs = datetime.combine(today, time(6, 0), tzinfo=timezone.utc)
    own = Hotel(source_id="t-own", name="Test Pansiyon", province="İzmir", district="Çeşme", lat=38.3, lng=26.3)
    comps = [Hotel(source_id=f"t-c{i}", name=f"Rakip {i}", province="İzmir", district="Çeşme", lat=38.3, lng=26.3 + i / 1000)
             for i in range(3)]
    db.add_all([own, *comps])
    db.flush()

    def rt(h, name, cat):
        r = RoomType(hotel_id=h.id, raw_name=name, category=cat, mapped_by="rule", confidence=1.0, reviewed=True)
        db.add(r)
        db.flush()
        return r

    rows = [(rt(own, "Standart", "standard"), 100.0), (rt(own, "Deluxe", "deluxe"), 180.0)]
    for i, c in enumerate(comps):
        rows.append((rt(c, "Standart", "standard"), 50.0))
        if i == 0:
            rows.append((rt(c, "Deluxe", "deluxe"), 45.0))
        db.add(CompetitorSet(hotel_id=own.id, competitor_hotel_id=c.id, rank=i + 1, similarity_score=0.8,
                             distance_km=0.1, is_manual=False))
    for r, p in rows:
        for k in range(10):
            db.add(RateSnapshot(room_type_id=r.id, stay_date=today + timedelta(days=k), observed_at=obs,
                                price_original=p, currency="EUR", price_eur=p, available_rooms=2, source="test"))
    db.flush()
    return own, rows[1][0]


def test_single_competitor_is_not_a_market_and_positioning_falls_back(db):
    own, deluxe = _isolated_market(db)
    out = generate_for_hotel(db, own, date.today(), date.today() + timedelta(days=6), persist=False)
    dlx = [s for s in out if s.room_type_id == deluxe.id]
    assert dlx
    for s in dlx:
        r = s.rationale
        assert r["comp_count"] == 0, "tek rakip piyasa sayılmamalı"
        assert r["position_index"] > 1.5, "deluxe için standart odadaki konumlama (≈2) kullanılmalı"
        assert float(s.suggested_price) > 120, "pansiyonun €180'lik odasına tek ucuz rakibin €45'i önerilmemeli"


def test_room_types_keep_their_premium_within_category(db):
    """Canlı test: €68 ve €96'lık iki standart odaya aynı fiyat öneriliyordu."""
    from datetime import datetime, time, timezone

    from app.models import RateSnapshot

    own, _ = _isolated_market(db)
    pricey = RoomType(hotel_id=own.id, raw_name="Standart Deniz Manzaralı", category="standard", mapped_by="rule",
                      confidence=1.0, reviewed=True)
    db.add(pricey)
    db.flush()
    obs = datetime.combine(date.today(), time(6, 0), tzinfo=timezone.utc)
    for k in range(10):
        db.add(RateSnapshot(room_type_id=pricey.id, stay_date=date.today() + timedelta(days=k), observed_at=obs,
                            price_original=140, currency="EUR", price_eur=140, available_rooms=1, source="test"))
    db.flush()
    out = generate_for_hotel(db, own, date.today(), date.today() + timedelta(days=3), persist=False)
    base = {s.stay_date: float(s.suggested_price) for s in out
            if s.room_type_id != pricey.id and s.rationale.get("room_premium") == 1.0 and s.rationale["comp_count"] == 3}
    top = {s.stay_date: (float(s.suggested_price), s.rationale["room_premium"]) for s in out if s.room_type_id == pricey.id}
    assert top and base
    for d, (p, prem) in top.items():
        assert prem == 1.4 and p > base[d] * 1.2, "pahalı oda tipi primini korumalı"
