"""Otel (müşteri) paneli: tüm ekranlar ve tüm işlemler."""
import re
from datetime import date

import pytest
from sqlalchemy import select

from app.models import CompetitorSet, Hotel, Notification, PriceSuggestion, RoomType, User

PAGES = [
    "/panel", "/panel/hos-geldiniz", "/panel/oneriler", "/panel/oneriler?gorunum=takvim", "/panel/oneriler?sadece=onemli&gun=60",
    "/panel/oneriler?kategori=deluxe&gun=14", "/panel/rakipler", "/panel/pazar", "/panel/pazar?veri=oda&gun=30",
    "/panel/talep", "/panel/oda-tipleri", "/panel/performans", "/panel/backtest", "/panel/backtest?gun=30&oncul=3",
    "/panel/raporlar", "/panel/bildirimler", "/panel/ayarlar", "/panel/abonelik", "/panel/hesap",
]


@pytest.mark.parametrize("url", PAGES)
def test_hotel_pages_render(hotel_browser, url):
    r = hotel_browser.get(url)
    assert r.status_code == 200, r.text[:500]
    assert "Demo veri modu" in r.text
    assert "Beklenmeyen bir hata" not in r.text


def test_dashboard_has_recommendation_and_charts(hotel_browser):
    html = hotel_browser.get("/panel").text
    assert "önerilen" in html and "Gerekçeyi incele" in html
    assert html.count('data-chart="') >= 2
    assert 'id="dash-price"' in html


def test_suggestion_detail_and_actions(hotel_browser, db, demo_hotel):
    html = hotel_browser.get("/panel/oneriler").text
    sid = int(re.search(r"/panel/oneriler/(\d+)\"", html).group(1))
    detail = hotel_browser.get(f"/panel/oneriler/{sid}")
    assert detail.status_code == 200 and "Fiyat nasıl oluştu" in detail.text and "Önerilen fiyat" in detail.text
    r = hotel_browser.post(f"/panel/oneriler/{sid}/aksiyon", {"action": "applied", "next": f"/panel/oneriler/{sid}"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(PriceSuggestion, sid).user_action == "applied"
    hotel_browser.post(f"/panel/oneriler/{sid}/aksiyon", {"action": "reset"})
    db.expire_all()
    assert db.get(PriceSuggestion, sid).user_action is None
    assert hotel_browser.post(f"/panel/oneriler/{sid}/aksiyon", {"action": "hack"}).status_code == 400


def test_cannot_access_other_hotels_suggestion(hotel_browser, db, demo_hotel):
    other = db.execute(select(PriceSuggestion).join(RoomType).where(RoomType.hotel_id != demo_hotel.id)).scalars().first()
    assert hotel_browser.get(f"/panel/oneriler/{other.id}").status_code == 404
    assert hotel_browser.post(f"/panel/oneriler/{other.id}/aksiyon", {"action": "applied"}).status_code == 404


def test_regenerate_suggestions(hotel_browser):
    r = hotel_browser.post("/panel/oneriler/yenile")
    assert r.status_code == 303
    assert "yeniden hesaplandı" in hotel_browser.get("/panel/oneriler").text


def test_competitor_management(hotel_browser, db, demo_hotel):
    comps = [c.competitor_hotel_id for c in db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == demo_hotel.id)).scalars()]
    victim = comps[-1]
    assert hotel_browser.post(f"/panel/rakipler/{victim}/geri-bildirim", {"verdict": "rejected"}).status_code == 303
    db.expire_all()
    assert db.get(CompetitorSet, (demo_hotel.id, victim)) is None
    cand = db.execute(select(Hotel).where(Hotel.province == demo_hotel.province, Hotel.id != demo_hotel.id,
                                          Hotel.id.not_in(comps))).scalars().first()
    r = hotel_browser.post("/panel/rakipler/ekle", {"competitor_id": cand.id})
    assert r.status_code == 303
    db.expire_all()
    row = db.get(CompetitorSet, (demo_hotel.id, cand.id))
    assert row and row.is_manual and row.feedback == "confirmed"
    assert hotel_browser.post(f"/panel/rakipler/{cand.id}/cikar").status_code == 303
    assert hotel_browser.post("/panel/rakipler/yeniden-hesapla").status_code == 303
    assert hotel_browser.post(f"/panel/rakipler/{comps[0]}/geri-bildirim", {"verdict": "confirmed"}).status_code == 303
    assert hotel_browser.post(f"/panel/rakipler/{comps[0]}/geri-bildirim", {"verdict": "x"}).status_code == 400
    # başka ilden rakip eklenemez
    far = db.execute(select(Hotel).where(Hotel.province != demo_hotel.province)).scalars().first()
    assert hotel_browser.post("/panel/rakipler/ekle", {"competitor_id": far.id}).status_code == 400


def test_room_type_remap(hotel_browser, db, demo_hotel):
    rt = demo_hotel.room_types[0]
    old = rt.category
    r = hotel_browser.post(f"/panel/oda-tipleri/{rt.id}", {"category": "suite"})
    assert r.status_code == 303
    db.expire_all()
    rt2 = db.get(RoomType, rt.id)
    assert rt2.category == "suite" and rt2.mapped_by == "manual"
    hotel_browser.post(f"/panel/oda-tipleri/{rt.id}", {"category": old})
    assert hotel_browser.post(f"/panel/oda-tipleri/{rt.id}", {"category": "villa"}).status_code == 400


def test_settings_validation_and_save(hotel_browser, db, demo_hotel):
    bad = hotel_browser.post("/panel/ayarlar", {"strategy": "balanced", "tolerance_pct": "40", "min_price_eur": "200",
                                                "max_price_eur": "100", "floor_below_p25_pct": "10", "ceiling_margin_pct": "5"})
    assert bad.status_code == 422 and "Uyum toleransı" in bad.text and "Minimum fiyat" in bad.text
    ok = hotel_browser.post("/panel/ayarlar", {"strategy": "aggressive", "tolerance_pct": "6", "min_price_eur": "",
                                               "max_price_eur": "", "floor_below_p25_pct": "12", "ceiling_margin_pct": "8",
                                               "room_count": "14", "star_rating": "3", "notify_email": "1"})
    assert ok.status_code == 303
    db.expire_all()
    hs = db.get(Hotel, demo_hotel.id).settings
    assert hs.strategy == "aggressive" and float(hs.tolerance_pct) == 6
    hotel_browser.post("/panel/ayarlar", {"strategy": "balanced", "tolerance_pct": "5", "floor_below_p25_pct": "10",
                                          "ceiling_margin_pct": "5"})


def test_csv_reports(hotel_browser):
    for url, header in [("/panel/raporlar/oneriler.csv", "tarih;oda_tipi"), ("/panel/raporlar/pazar.csv", "otel;"),
                        ("/panel/raporlar/uyum.csv", "gozlem_zamani")]:
        r = hotel_browser.get(url)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert header in r.text.lstrip("﻿").splitlines()[0]
    assert len(hotel_browser.get("/panel/raporlar/oneriler.csv?gun=7").text.splitlines()) > 7


def test_notifications_mark_read(hotel_browser, db, demo_hotel):
    db.add(Notification(hotel_id=demo_hotel.id, title="Test", body="Gövde"))
    db.commit()
    assert hotel_browser.post("/panel/bildirimler/okundu").status_code == 303
    db.expire_all()
    assert not db.execute(select(Notification).where(Notification.hotel_id == demo_hotel.id,
                                                     Notification.is_read.is_(False))).first()


def test_account_password_change(hotel_browser, db):
    bad = hotel_browser.post("/panel/hesap", {"full_name": "Ad", "current_password": "yanlis", "new_password": "kisa"})
    assert bad.status_code == 422 and "Mevcut parola hatalı" in bad.text
    ok = hotel_browser.post("/panel/hesap", {"full_name": "Demo Yetkili", "current_password": "Demo1234!",
                                             "new_password": "Demo1234!"})
    assert ok.status_code == 303
    db.expire_all()
    assert db.execute(select(User).where(User.email == "otel@otelradar.local")).scalar_one().full_name == "Demo Yetkili"


def test_plan_change(hotel_browser, db, demo_hotel):
    from app.models import Plan

    plans = list(db.execute(select(Plan).order_by(Plan.sort_order)).scalars())
    sub = demo_hotel.active_subscription
    original = sub.plan_id
    target = next(p for p in plans if p.id != original)
    assert hotel_browser.post("/panel/abonelik/paket", {"plan_id": target.id}).status_code == 303
    db.expire_all()
    assert db.get(Hotel, demo_hotel.id).active_subscription.plan_id == target.id
    hotel_browser.post("/panel/abonelik/paket", {"plan_id": original})


def test_cancel_requires_confirmation(hotel_browser, db, demo_hotel):
    r = hotel_browser.post("/panel/abonelik/iptal", {"confirm": "hayır"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Hotel, demo_hotel.id).active_subscription is not None


def test_cancel_subscription_end_to_end(client, db):
    """Ayrı bir abone (otel2) ile tam iptal akışı."""
    from tests.conftest import Browser, login

    u = db.execute(select(User).where(User.email == "otel2@otelradar.local")).scalar_one()
    assert login(client, "otel2@otelradar.local", "Demo1234!").status_code == 303
    b = Browser(client)
    assert b.post("/panel/abonelik/iptal", {"confirm": "IPTAL"}).status_code == 303
    db.expire_all()
    h = db.get(Hotel, u.hotel_id)
    assert not h.is_subscriber and h.active_subscription is None
    # geri al (diğer testler için)
    from app.models import Subscription

    sub = db.execute(select(Subscription).where(Subscription.hotel_id == h.id)).scalars().first()
    sub.status, sub.canceled_at, h.is_subscriber = "active", None, True
    db.commit()


def test_json_api(hotel_browser):
    rows = hotel_browser.get("/api/v1/suggestions?days=7").json()
    assert rows and {"stay_date", "suggested_price_eur", "rationale"} <= set(rows[0])
    assert date.fromisoformat(rows[0]["stay_date"]) >= date.today()
    m = hotel_browser.get("/api/v1/market?days=7").json()
    assert len(m["dates"]) == 7 and m["hotels"][0]["is_self"]
    d = hotel_browser.get("/api/v1/demand?days=10").json()
    assert len(d) == 10 and 0 <= d[0]["score"] <= 100


def test_no_definitive_revenue_claims_anywhere(hotel_browser):
    """Doküman 6.1(c): kesin gelir ifadeleri kullanılmaz; etki her yerde 'tahmini'."""
    from pathlib import Path

    forbidden = ("ek kâr", "kurtarılan gelir", "kazandırdık", "garanti ediyoruz")
    for f in Path("app/templates").rglob("*.html"):
        text = f.read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            assert phrase not in text, f"{f}: '{phrase}'"
    perf = hotel_browser.get("/panel/performans").text
    assert "tahmini" in perf.lower()
