"""ACIK_KONULAR §4b: alan bazlı hatalar, veri hattı yoklaması, Türkçe etiketler, ilk kurulum, tüm oda tipleri, tablo semantiği."""
import re
from pathlib import Path


def test_settings_error_keeps_input_and_marks_field(hotel_browser):
    """Hatalı gönderimde girilen değerler korunur; hatalı alan aria-invalid ve altında Türkçe mesaj taşır."""
    r = hotel_browser.post("/panel/ayarlar", {"strategy": "balanced", "tolerance_pct": "40", "min_price_eur": "90",
                                              "max_price_eur": "80", "floor_below_p25_pct": "10", "ceiling_margin_pct": "5"})
    assert r.status_code == 422
    html = r.text
    tol = re.search(r'<input[^>]*id="tolerance_pct"[^>]*>', html).group(0)
    assert 'value="40"' in tol and 'aria-invalid="true"' in tol and 'aria-describedby="tolerance_pct-err"' in tol
    assert 'id="tolerance_pct-err"' in html and "%1 ile %25" in html
    mn = re.search(r'<input[^>]*id="min_price_eur"[^>]*>', html).group(0)
    assert 'value="90"' in mn and 'aria-invalid="true"' in mn


def test_account_error_keeps_name_and_marks_password(hotel_browser):
    r = hotel_browser.post("/panel/hesap", {"full_name": "Yeni Ad Soyad", "current_password": "yanlis", "new_password": "Parola123"})
    assert r.status_code == 422
    name = re.search(r'<input[^>]*id="full_name"[^>]*>', r.text).group(0)
    assert 'value="Yeni Ad Soyad"' in name
    cur = re.search(r'<input[^>]*id="current_password"[^>]*>', r.text).group(0)
    assert 'aria-invalid="true"' in cur


def test_pipeline_polls_without_full_reload(admin_browser):
    """Veri hattı sayfası tam yenileme yerine canlı bölgeyi yoklar; odak ve kaydırma korunur."""
    html = admin_browser.get("/admin/veri-hatti").text
    assert 'id="hat-canli"' in html and 'aria-live="polite"' in html
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert "location.reload" not in js


def test_audit_and_event_labels_are_turkish(admin_browser):
    from app.web import AUDIT_LABELS, EVENT_CATEGORY_LABELS

    assert AUDIT_LABELS["impersonate_hotel"] and EVENT_CATEGORY_LABELS["festivals"] == "Festival"
    audit = admin_browser.get("/admin/denetim").text
    assert "<code>login</code>" not in audit and "Giriş" in audit
    demand = admin_browser.get("/admin/talep").text
    assert ">festivals<" not in demand and ">Festival<" in demand


def test_welcome_steps_follow_real_actions(hotel_browser, db, demo_hotel):
    """İlk kurulum adımları gerçek işaretlere bağlıdır: rakip onayı, oda tipi kontrolü, fiyat sınırı."""
    from app.models import CompetitorSet

    db.query(CompetitorSet).filter(CompetitorSet.hotel_id == demo_hotel.id).update({"feedback": None, "is_manual": False})
    db.commit()
    html = hotel_browser.get("/panel/hos-geldiniz").text
    before = html.count('class="done"')
    assert f"{before} / 4" in html
    assert re.search(r'<li class="">\s*<div><b>Rakip setinizi onaylayın', html), "rakip adımı onay olmadan tamam sayılmamalı"
    comp = db.query(CompetitorSet).filter(CompetitorSet.hotel_id == demo_hotel.id).first()
    hotel_browser.post(f"/panel/rakipler/{comp.competitor_hotel_id}/geri-bildirim", {"verdict": "confirmed"})
    html = hotel_browser.get("/panel/hos-geldiniz").text
    assert html.count('class="done"') == before + 1


def test_dashboard_tonight_for_all_room_types(hotel_browser, demo_hotel):
    """Birden çok oda kategorisi olan otelde panel, bu gecenin önerisini her kategori için gösterir."""
    cats = {rt.category for rt in demo_hotel.room_types}
    html = hotel_browser.get("/panel").text
    if len(cats) > 1:
        assert 'class="tonight-strip"' in html
        assert html.count('class="tonight-item') >= len(cats)


def test_market_grid_row_headers(hotel_browser):
    html = hotel_browser.get("/panel/pazar").text
    assert re.search(r'<th scope="row" class="hname"', html)
    assert "<caption" in html
