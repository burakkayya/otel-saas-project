"""Servis katmanı testleri (tohumlanmış veritabanı üzerinde)."""
from datetime import date, timedelta

from sqlalchemy import func, select

from app.models import (
    ApiUsage,
    AppliedObservation,
    CompetitorSet,
    Hotel,
    JobRun,
    PriceSuggestion,
    RateSnapshot,
    RoiEstimate,
    RoomType,
)
from app.services import analytics
from app.services.backtest import run_backtest
from app.services.compset import add_manual_competitor, build_compset, compset_accuracy, set_feedback
from app.services.costs import EconomicsInput, measured_usage, unit_economics
from app.services.market import compset_ids
from app.services.pipeline import run_job
from app.services.pricing import generate_for_hotel, position_index
from app.services.roi import estimate_did, select_control_group
from app.services.seasonality import monthly_coefficients
from app.services.uptake import uptake_stats


def test_seed_created_full_dataset(db, seeded_database):
    assert seeded_database["subscribers"] >= 3
    assert db.execute(select(func.count(RateSnapshot.id))).scalar() > 10000
    assert db.execute(select(func.count(PriceSuggestion.id))).scalar() > 500
    assert db.execute(select(func.count(AppliedObservation.id))).scalar() > 0
    assert db.execute(select(func.count(ApiUsage.id))).scalar() > 0
    # her abonenin rakip seti var ve en fazla 5
    for h in db.execute(select(Hotel).where(Hotel.is_subscriber.is_(True))).scalars():
        ids = compset_ids(db, h.id)
        assert 1 <= len(ids) <= 5 and h.id not in ids


def test_compset_respects_manual_and_rejected(db, demo_hotel):
    ids = compset_ids(db, demo_hotel.id)
    rejected = ids[-1]
    set_feedback(db, demo_hotel.id, rejected, "rejected")
    others = [h for h in db.execute(select(Hotel).where(Hotel.province == demo_hotel.province, Hotel.id != demo_hotel.id)).scalars()
              if h.id not in ids]
    manual = others[0]
    add_manual_competitor(db, demo_hotel, manual)
    rows = build_compset(db, demo_hotel, size=5)
    new_ids = [r.competitor_hotel_id for r in rows]
    assert manual.id in new_ids and rejected not in new_ids
    assert rows[0].is_manual  # elle eklenen en üstte
    assert [r.rank for r in rows] == list(range(1, len(rows) + 1))
    acc = compset_accuracy(db, demo_hotel.id)
    assert acc["rated"] >= 2 and acc["confirmed"] >= 1
    db.rollback()


def test_generate_suggestions_respects_bounds(db, demo_hotel):
    today = date.today()
    sugg = generate_for_hotel(db, demo_hotel, today, today + timedelta(days=6), persist=False)
    assert sugg
    for s in sugg:
        assert s.price_floor <= s.suggested_price <= s.price_ceiling
        assert s.rationale["text"]
        assert s.model_version
    db.rollback()


def test_hotel_min_price_rule_applied(db, demo_hotel):
    demo_hotel.settings.min_price_eur = 999
    sugg = generate_for_hotel(db, demo_hotel, date.today(), date.today() + timedelta(days=2), persist=False)
    assert all(float(s.suggested_price) >= 999 for s in sugg)
    db.rollback()


def test_position_index_reasonable(db, demo_hotel):
    pi = position_index(db, demo_hotel.id, compset_ids(db, demo_hotel.id), "standard", date.today())
    assert 0.3 < pi < 3


def test_season_coefficients(db, demo_hotel):
    res = monthly_coefficients(db, demo_hotel.province, demo_hotel.district)
    assert len(res["coef"]) == 12 and all(c > 0 for c in res["coef"])
    assert max(res["coef"][5:8]) > min(res["coef"][0:2])  # yaz > kış


def test_backtest_produces_metrics(db, demo_hotel):
    res = run_backtest(db, demo_hotel, days=20, lead=7)
    sm = res["summary"]
    assert sm and sm["n"] > 10
    assert 0 <= sm["mape_suggestion"] < 60 and 0 <= sm["band_hit_rate"] <= 100
    row = res["rows"][0]
    assert {"suggested", "market_final", "market_asof", "floor", "ceiling"} <= set(row)


def test_uptake_and_roi(db, demo_hotel):
    st = uptake_stats(db, demo_hotel.id)
    assert st["total"] > 0 and 0 <= st["rate"] <= 100
    controls = select_control_group(db, demo_hotel)
    assert all(not c.is_subscriber for c in controls)
    res = estimate_did(db, demo_hotel, demo_hotel.active_subscription.started_at, persist=False)
    assert res["status"] in ("ok", "no_control", "insufficient_data")
    if res["status"] == "ok":
        assert res["confidence"] in ("low", "medium", "high")
        assert res["control_group_size"] < 10 or res["confidence"] != "low" or not res["significant"]
    assert db.execute(select(RoiEstimate).where(RoiEstimate.is_estimate.is_(False))).first() is None


def test_did_insufficient_post_period(db, demo_hotel):
    res = estimate_did(db, demo_hotel, date.today() - timedelta(days=2), persist=False)
    assert res["status"] == "insufficient_post"


def test_dashboard_aggregation(db, demo_hotel):
    data = analytics.hotel_dashboard(db, demo_hotel)
    assert len(data["chart"]["labels"]) == 60
    assert data["today_row"] is not None
    ov = analytics.admin_overview(db)
    assert ov["active"] + ov["trial"] >= 3 and len(ov["mrr_series"]) == 6


def test_unit_economics(db):
    econ = unit_economics(db, EconomicsInput(subscribers=20))
    assert econ["total"] > 0 and econ["plans"]
    assert all(p["cost_per_sub"] == econ["per_subscriber"] for p in econ["plans"])
    assert measured_usage(db)["by_provider"].get("rapidapi", 0) > 0


def test_daily_pipeline_job(db):
    before = db.execute(select(func.count(RateSnapshot.id))).scalar()
    run = run_job(db, "daily_pipeline", trigger="manual")
    assert run.status == "success", run.message
    assert run.records > 0
    assert db.execute(select(func.count(RateSnapshot.id))).scalar() > before


def test_all_jobs_succeed(db):
    for name in ("demand_refresh", "suggestions", "uptake", "roi_did", "backtest", "compset_rebuild"):
        run = run_job(db, name, trigger="manual")
        assert run.status == "success", (name, run.message)


def test_job_failure_is_recorded(db, monkeypatch):
    from app.services import pipeline

    def boom(*a, **k):
        raise RuntimeError("test hatası")

    monkeypatch.setitem(pipeline.JOBS, "uptake", ("Uyum", boom))
    run = run_job(db, "uptake")
    assert run.status == "failed" and "test hatası" in run.message
    assert db.get(JobRun, run.id).finished_at is not None


def test_room_types_all_categorized(db):
    assert db.execute(select(func.count(RoomType.id)).where(RoomType.category.is_(None))).scalar() == 0
    assert db.execute(select(func.count(CompetitorSet.hotel_id))).scalar() > 0


def test_daily_pipeline_is_idempotent(db):
    run_job(db, "daily_pipeline")
    first = db.execute(select(func.count(RateSnapshot.id))).scalar()
    run_job(db, "daily_pipeline")
    assert db.execute(select(func.count(RateSnapshot.id))).scalar() == first
