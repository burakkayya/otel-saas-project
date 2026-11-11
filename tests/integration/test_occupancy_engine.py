"""Doluluk tahmini, otomatik uygulama tespiti ve sonuçlarla motor ayarı."""
from datetime import date, timedelta

from sqlalchemy import select

from app.models import AppSetting, AuditLog, StayOutcome
from app.services.market import compset_ids
from app.services.occupancy import compset_occupancy, hotel_occupancy
from app.services.outcomes import classify, evaluate_outcomes, outcome_summary, tune_weights


def test_occupancy_estimates_for_subscriber_and_competitors(db, demo_hotel):
    today = date.today()
    comps = compset_ids(db, demo_hotel.id)
    occ = hotel_occupancy(db, [demo_hotel.id] + comps, today, today + timedelta(days=13))
    own = occ.get(demo_hotel.id, {})
    assert len(own) >= 10
    assert all(0 <= e.occ <= 1 and e.low <= e.occ <= e.high for e in own.values())
    assert sum(1 for c in comps if occ.get(c)) >= 2
    near = [own[d].occ for d in sorted(own)[:3]]
    far = [own[d].occ for d in sorted(own)[-3:]]
    assert sum(near) >= sum(far), "yakın tarihler uzak tarihlerden daha dolu olmalı"
    days = compset_occupancy(db, demo_hotel.id, comps, today, today + timedelta(days=6))
    assert days[today]["comp"] is not None and days[today]["comp_n"] >= 2


def test_suggestions_use_occupancy(db, demo_hotel):
    from app.services.analytics import suggestion_rows

    rows = suggestion_rows(db, demo_hotel, date.today(), date.today() + timedelta(days=6))
    assert rows and any(r["comp_occ"] is not None for r in rows)
    assert any("doluluk" in (r["text"] or "") for r in rows)


def test_application_is_detected_automatically(db, demo_hotel):
    assert classify(100, 102, 90, 0.05) == "applied"
    assert classify(100, 96, 90, 0.03) == "partial"
    assert classify(100, 90, 90, 0.05) == "not_applied"
    assert classify(100, 85, 90, 0.05) == "not_applied"  # ters yöne gitti
    assert classify(100, None, 90, 0.05) == "unobserved"
    n = evaluate_outcomes(db, demo_hotel)
    assert n > 0
    rows = list(db.execute(select(StayOutcome).where(StayOutcome.hotel_id == demo_hotel.id)).scalars())
    statuses = {r.status for r in rows}
    assert "applied" in statuses, statuses  # demo verisinde abone önerilerin bir kısmını uyguluyor
    s = outcome_summary(db, demo_hotel.id)
    assert s["observed"] > 0 and s["applied_rate"] is not None


def test_dashboard_and_performance_show_occupancy_and_outcomes(hotel_browser):
    html = hotel_browser.get("/panel").text
    assert "Doluluk: siz ve rakipleriniz" in html and 'id="dash-occ"' in html
    assert "kesin değer değildir" in html
    assert "Uyguladım" not in html
    perf = hotel_browser.get("/panel/performans").text
    assert "Uygulanan öneri (tespit)" in perf and "RevPAR endeksiniz" in perf
    assert "Uyguladım işaretleri" not in perf


def test_weights_shrink_when_applied_increases_lose_share(db, demo_hotel):
    rt = demo_hotel.room_types[0]
    base = date(2020, 3, 1)
    for i in range(40):
        db.add(StayOutcome(hotel_id=demo_hotel.id, room_type_id=rt.id, stay_date=base + timedelta(days=i),
                           status="applied", suggested_price=120, price_before=100, observed_price=120,
                           own_occ_start=0.5, own_occ_end=0.55, comp_occ_start=0.5, comp_occ_end=0.8, is_final=True))
    db.flush()
    before = (db.get(AppSetting, "pricing_weights").value or {}) if db.get(AppSetting, "pricing_weights") else {}
    res = tune_weights(db, today=date(2020, 5, 1))
    assert res["n_up"] == 40 and "max_up" in res["changed"]
    old, new = res["changed"]["max_up"]
    assert new < old
    w = db.get(AppSetting, "pricing_weights").value
    assert w["max_up"] == new and w != before
    assert db.execute(select(AuditLog).where(AuditLog.action == "weights_tuned")).scalars().first() is not None
