"""Güvenlik, biçimlendirme, maliyet ve demo sağlayıcı birim testleri."""
from datetime import date, datetime, timezone

from app.security import (
    LoginRateLimiter,
    csrf_valid,
    get_csrf_token,
    hash_password,
    password_problems,
    verify_password,
)
from app.services.costs import EconomicsInput, estimate_monthly_requests, provider_cost
from app.services.pipeline import classify_inventory
from app.services.providers import UsageTracker, _Counting
from app.services.providers.demo import DemoProvider, season_multiplier
from app.web import ago, fmt_date, fmt_eur, fmt_number, fmt_pct, paginate, to_json


def test_password_hash_roundtrip():
    h = hash_password("Gizli123", iterations=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert verify_password("Gizli123", h)
    assert not verify_password("gizli123", h)
    assert not verify_password("x", "bozuk")
    assert hash_password("a", iterations=1000) != hash_password("a", iterations=1000)  # tuz


def test_password_rules():
    assert password_problems("Abcdef12") == []
    assert len(password_problems("abc")) == 2
    assert password_problems("abcdefgh") == ["Parola en az bir rakam içermeli."]


def test_csrf():
    session = {}
    tok = get_csrf_token(session)
    assert get_csrf_token(session) == tok
    assert csrf_valid(session, tok)
    assert not csrf_valid(session, "yanlis")
    assert not csrf_valid({}, tok)


def test_rate_limiter():
    rl = LoginRateLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        assert not rl.is_blocked("k")
        rl.register_failure("k")
    assert rl.is_blocked("k")
    rl.reset("k")
    assert not rl.is_blocked("k")


def test_turkish_formatting():
    assert fmt_number(1234567.891, 2) == "1.234.567,89"
    assert fmt_eur(1499) == "€1.499"
    assert fmt_eur(None) == "—"
    assert fmt_eur(-17.6, 1) == "−€17,6"
    assert fmt_eur(-0.01) == "€0"
    assert fmt_pct(12.345, 1, True).replace("\u2060", "") == "+%12,3"
    assert fmt_pct(-4, 0).replace("\u2060", "") == "−%4"
    assert fmt_date(date(2026, 11, 1), "day") == "1 Kas Paz"
    assert fmt_date("2026-06-14", "long") == "14 Haziran 2026"
    assert fmt_date(datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc), "datetime") == "1 Kas 2026 09:00"
    assert ago(None) == "—"
    assert ago(datetime.now(timezone.utc)) == "az önce"


def test_json_is_script_safe():
    out = str(to_json({"x": "</script><b>", "d": date(2026, 1, 2)}))
    assert "</script>" not in out and "2026-01-02" in out


def test_paginate():
    pg = paginate(101, 3, 25)
    assert pg["pages"] == 5 and pg["offset"] == 50 and pg["has_prev"] and pg["has_next"]
    assert paginate(0, 9, 25)["page"] == 1


def test_inventory_event_classification():
    assert classify_inventory(5, 3) == "drop"
    assert classify_inventory(5, 0) == "closed"
    assert classify_inventory(0, 2) == "reopen"
    assert classify_inventory(3, 3) == "unchanged"
    assert classify_inventory(None, 3) is None


def test_unit_economics_scaling():
    small = estimate_monthly_requests(EconomicsInput(subscribers=10))
    big = estimate_monthly_requests(EconomicsInput(subscribers=100))
    assert big["rapidapi"] == small["rapidapi"] * 10
    batched = estimate_monthly_requests(EconomicsInput(subscribers=10, dates_per_request=30))
    assert batched["rapidapi"] == small["rapidapi"] // 30


def test_provider_cost_with_included_quota():
    class PC:
        unit_cost_eur, monthly_fee_eur, included_requests = 0.01, 5, 100

    assert provider_cost(PC, 50) == 5
    assert provider_cost(PC, 300) == 7


def test_demo_provider_is_deterministic_and_realistic():
    a, b = DemoProvider(), DemoProvider()
    ha, hb = a.list_hotels("Muğla"), b.list_hotels("Muğla")
    assert [h.name for h in ha] == [h.name for h in hb]
    assert len({h.name for h in ha}) == len(ha)
    h = ha[0]
    summer = a.get_rates(h, date(2026, 8, 10), date(2026, 7, 20))
    winter = a.get_rates(h, date(2026, 1, 20), date(2026, 1, 1))
    eur = a.rates(date(2026, 1, 1))
    s = [r.price / eur[r.currency] for r in summer if r.price]
    w = [r.price / eur[r.currency] for r in winter if r.price]
    if s and w:
        assert sum(s) / len(s) > sum(w) / len(w)
    assert season_multiplier("summer", date(2026, 8, 1)) > season_multiplier("summer", date(2026, 1, 15))
    assert all(r.available_rooms is not None for r in summer)


def test_usage_tracker_counts_demo_calls():
    tracker = UsageTracker()
    prov = _Counting(DemoProvider(scale=0.2), tracker)
    prov.list_hotels("Antalya")
    prov.rates(date(2026, 1, 1))
    assert tracker.counts[("rapidapi", "city")][0] == 1
    assert tracker.counts[("fixer", "historical")][0] == 1
