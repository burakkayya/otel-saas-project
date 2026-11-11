"""Netlik turu: tek fiil, ana neden başlığı, öncelik listesi ve rezervasyon hızı (pace)."""
from datetime import date, timedelta

from app.services.analytics import hotel_dashboard, suggestion_rows
from app.services.occupancy import expected_occupancy, pace_curve


def test_pace_curve_is_learned_from_own_history(db, demo_hotel):
    curves, days = pace_curve(db, demo_hotel.id, date.today())
    assert curves and len(days) >= 20
    near = expected_occupancy(curves, date.today() + timedelta(days=2), 1)
    far = expected_occupancy(curves, date.today() + timedelta(days=40), 30)
    assert near is not None and far is not None and near > far, "yakın tarihte beklenen doluluk daha yüksek olmalı"


def test_every_suggestion_has_one_action_and_one_headline(db, demo_hotel):
    rows = suggestion_rows(db, demo_hotel, date.today(), date.today() + timedelta(days=20))
    assert rows
    assert all(r["action"] in ("raise", "lower", "hold", "set") for r in rows)
    assert all(r["headline"] for r in rows)
    assert any(r["expected_occ"] is not None for r in rows)
    for r in rows:
        if r["action"] == "hold":
            assert abs(r["change"]) < 3


def test_focus_list_is_short_and_actionable(db, demo_hotel):
    data = hotel_dashboard(db, demo_hotel)
    assert len(data["focus"]) <= 5
    assert all(r["action"] in ("raise", "lower") for r in data["focus"])
    assert [r["date"] for r in data["focus"]] == sorted(r["date"] for r in data["focus"])
    assert sum(data["action_counts"].values()) > 0


def test_dashboard_leads_with_what_to_do(hotel_browser):
    html = hotel_browser.get("/panel").text
    assert "Önce bunlara bakın" in html and 'class="hero-headline"' in html
    assert "Normalde beklenen" in html
    hero_end = html.index("</section>", html.index('class="hero-rec"'))
    assert html.index("Önce bunlara bakın") > hero_end
    assert html.index("Önce bunlara bakın") < html.index("Doluluk: siz ve rakipleriniz")


def test_suggestion_list_says_what_to_do_and_why(hotel_browser):
    html = hotel_browser.get("/panel/oneriler").text
    assert "<th>Ne yapmalı</th>" in html and "<th>Neden</th>" in html
    assert "Rakip medyanı</th>" not in html  # sadeleşti: medyan bant üzerinde gösteriliyor
    assert any(s in html for s in ("Yükselt", "İndir", "Koru"))
    assert 'class="why-cell"' in html
    only = hotel_browser.get("/panel/oneriler?sadece=onemli").text
    assert "badge good act" not in only  # 'Koru' satırları süzülür


def test_detail_shows_action_and_expected_occupancy(hotel_browser):
    import re

    html = hotel_browser.get("/panel/oneriler").text
    sid = re.search(r"/panel/oneriler/(\d+)\"", html).group(1)
    detail = hotel_browser.get(f"/panel/oneriler/{sid}").text
    assert 'class="hero-headline"' in detail and "badge" in detail
    assert "Bu tarihte beklenen" in detail
