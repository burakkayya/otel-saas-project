"""Arayüz kalite kuralları: demo uyarısı, form etiketleri, yerel varlıklar, Türkçe biçim.

Impeccable iyileştirme turunda eklendi; tasarım sisteminin değişmez kurallarını (docs/UI_AUDIT.md) korur.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.integration.test_web_admin import PAGES as ADMIN_PAGES
from tests.integration.test_web_hotel import PAGES as HOTEL_PAGES

PUBLIC_PAGES = ["/", "/fiyatlar", "/giris", "/kayit", "/sifremi-unuttum", "/yasal/kvkk", "/yasal/gizlilik",
                "/yasal/kullanim-kosullari"]


class _Fields(HTMLParser):
    """Görünür form alanlarını ve etiket ilişkilerini toplar."""

    def __init__(self):
        super().__init__()
        self.fields: list[dict] = []
        self.label_for: set[str] = set()
        self._label_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag in ("input", "select", "textarea"):
            if tag == "input" and a.get("type") in ("hidden", "submit", "button", "reset"):
                return
            self.fields.append({"tag": tag, "attrs": a, "wrapped": self._label_depth > 0})

    def handle_endtag(self, tag):
        if tag == "label" and self._label_depth:
            self._label_depth -= 1


def unlabeled_fields(html: str) -> list[str]:
    p = _Fields()
    p.feed(html)
    bad = []
    for f in p.fields:
        a = f["attrs"]
        if f["wrapped"] or a.get("aria-label") or a.get("aria-labelledby") or a.get("title"):
            continue
        if a.get("id") and a["id"] in p.label_for:
            continue
        bad.append(f"<{f['tag']} name={a.get('name')!r}>")
    return bad


@pytest.mark.parametrize("url", PUBLIC_PAGES)
def test_demo_banner_on_public_pages(client, url):
    """Demo veri uyarısı her ekranda kalır (herkese açık sayfalar dahil)."""
    assert "Demo veri modu" in client.get(url).text


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_demo_banner_on_admin_pages(admin_browser, url):
    assert "Demo veri modu" in admin_browser.get(url).text


def test_demo_banner_on_error_pages(client, hotel_browser):
    assert "Demo veri modu" in client.get("/olmayan-sayfa").text
    assert "Demo veri modu" in hotel_browser.get("/admin").text


@pytest.mark.parametrize("url", PUBLIC_PAGES)
def test_public_form_fields_are_labelled(client, url):
    assert unlabeled_fields(client.get(url).text) == []


@pytest.mark.parametrize("url", HOTEL_PAGES)
def test_hotel_form_fields_are_labelled(hotel_browser, url):
    assert unlabeled_fields(hotel_browser.get(url).text) == []


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_admin_form_fields_are_labelled(admin_browser, url):
    assert unlabeled_fields(admin_browser.get(url).text) == []


def test_admin_hotel_detail_fields_are_labelled(admin_browser):
    html = admin_browser.get("/admin/oteller").text
    href = re.search(r'href="(/admin/oteller/\d+)"', html).group(1)
    assert unlabeled_fields(admin_browser.get(href).text) == []


def test_no_external_assets():
    """Harici CDN yok: şablon ve statik dosyalarda dış kaynaklı betik, stil veya yazı tipi bağlantısı bulunmaz."""
    pattern = re.compile(r"""(?:src|href)\s*=\s*["']https?://|@import\s+url\(\s*["']?https?://|url\(\s*["']?https?://""")
    roots = [Path("app/templates"), Path("app/static/css"), Path("app/static/js")]
    for root in roots:
        for f in root.rglob("*"):
            if f.suffix in (".html", ".css", ".js") and "vendor" not in f.parts:
                assert not pattern.search(f.read_text(encoding="utf-8")), f"{f}: harici kaynak"


def test_money_uses_true_minus_sign(hotel_browser):
    """Negatif para ve yüzde değerleri tire (-) yerine eksi işaretiyle (−) yazılır."""
    for url in ("/panel", "/panel/performans", "/panel/oneriler"):
        text = re.sub(r"<script.*?</script>", "", hotel_browser.get(url).text, flags=re.S)
        assert not re.search(r"(?<![\w\-])-(?:€|%)\s?\d", text), url


def test_forbidden_page_offers_way_back_for_signed_in_user(hotel_browser):
    """403 sayfası oturum açmış kullanıcıya kayıt çağrısı değil, kendi paneline dönüş yolu gösterir."""
    html = hotel_browser.get("/admin").text
    assert 'href="/panel"' in html and "Panele dön" in html
    assert "14 gün ücretsiz dene" not in html
    assert "javascript:history.back()" not in html


def test_forbidden_page_for_admin_on_hotel_panel(admin_browser):
    """Yönetici, otel seçmeden /panel açarsa 'yalnızca yönetici' değil, otel seçmesi gerektiğini görür."""
    r = admin_browser.get("/panel")
    assert r.status_code == 403
    assert "otel seçin" in r.text and "yalnızca yönetici" not in r.text
    assert 'href="/admin/oteller"' in r.text


def test_error_page_survives_database_outage(hotel_browser, monkeypatch):
    """Veritabanına ulaşılamasa da markalı hata sayfası çizilir (oturum kullanıcısı bilinmeden)."""
    import app.main as main

    def boom():
        raise RuntimeError("veritabanı kapalı")

    monkeypatch.setattr(main, "SessionLocal", boom)
    r = hotel_browser.get("/admin")
    assert r.status_code == 403 and "OtelRadar" in r.text


def test_register_match_badge_uses_name_similarity(client):
    html = _start_registration(client, "Deneme Bodrum Butik Otel", "Bodrum", "rozet-aday@test.local")
    assert "%100 benzerlik" not in html


def test_not_found_page_for_visitor_links_home(client):
    html = client.get("/olmayan-sayfa").text
    assert 'href="/"' in html and "javascript:" not in html


def _start_registration(client, hotel_name, district, email):
    from tests.conftest import csrf_from

    token = csrf_from(client, "/kayit")
    r = client.post("/kayit", data={"csrf_token": token, "hotel_name": hotel_name, "province": "Muğla", "district": district,
                                    "address": "", "star_rating": "", "full_name": "Deneme Yetkili", "email": email,
                                    "plan_code": "profesyonel", "kvkk": "1"}, follow_redirects=False)
    assert r.status_code == 303
    return client.get("/kayit/eslestir").text


def test_register_match_does_not_preselect_weak_candidate(client):
    """Zayıf ya da başka ilçedeki aday önceden seçilmez; kullanıcı bilinçli seçim yapar."""
    html = _start_registration(client, "Deneme Bodrum Butik Otel", "Bodrum", "zayif-aday@test.local")
    assert re.search(r'name="hotel_choice" value="\d+"[^>]*checked', html) is None
    assert re.search(r'name="hotel_choice"[^>]*required', html)


def test_register_kvkk_wording_is_acknowledgement(client):
    html = client.get("/kayit").text
    assert "bilgilendirildim" in html and "kabul ediyorum" not in html


def test_backtest_does_not_call_inventory_drop_sales(hotel_browser):
    """Kalan oda düşüşü satış olarak sunulmaz (doküman 6)."""
    html = hotel_browser.get("/panel/backtest").text
    for phrase in ("Satış ilerlemesi", "Talep–satış", "satış korelasyonu"):
        assert phrase not in html
    assert "Kalan oda düşüşü" in html


def test_plan_features_match_limits(db):
    """Paket özellik maddeleri sınırlarla çelişmez; olmayan e-posta altyapısı vaat edilmez."""
    from sqlalchemy import select

    from app.models import Plan

    for plan in db.execute(select(Plan)).scalars():
        text = " ".join(plan.features or []).lower()
        if plan.max_room_types:
            assert "sınırsız oda" not in text, plan.code
        if "e-posta" in text:
            assert "yakında" in text, plan.code
        assert "compset" not in text, plan.code


def test_old_default_plan_features_are_migrated(db):
    """Önceki sürümün değiştirilmemiş varsayılan maddeleri güncel metne taşınır; yöneticinin özel metnine dokunulmaz."""
    from sqlalchemy import select

    from app.models import Plan
    from app.seed import _OLD_DEFAULT_FEATURES, PLANS, ensure_base

    resort = db.execute(select(Plan).where(Plan.code == "resort")).scalar_one()
    pro = db.execute(select(Plan).where(Plan.code == "profesyonel")).scalar_one()
    resort.features = list(_OLD_DEFAULT_FEATURES["resort"])
    pro.features = ["Özel madde"]
    db.commit()
    ensure_base(db)
    db.commit()
    db.refresh(resort)
    db.refresh(pro)
    assert resort.features == next(p["features"] for p in PLANS if p["code"] == "resort")
    assert pro.features == ["Özel madde"]
    pro.features = next(p["features"] for p in PLANS if p["code"] == "profesyonel")
    db.commit()


def test_signed_number_filter():
    from app.web import fmt_signed

    assert fmt_signed(-5.73, 1) == "−5,7"
    assert fmt_signed(2.04, 1) == "+2,0"
    assert fmt_signed(-0.01, 1) == "0,0"
    assert fmt_signed(None) == "—"


def test_rationale_drivers_plain_language():
    """Gerekçe en etkili 3 etkene, jargonsuz Türkçe ile ayrılır; en güçlü etken başta gelir."""
    from app.web import rationale_drivers

    r = {"position_index": 0.6, "comp_median_change_7d_pct": 1.0, "demand_score": 17, "demand_level": "Çok düşük",
         "inventory_pressure": 0.02, "season_label": "Ölü sezon", "season_coef": 0.7,
         "adjustments_pct": {"demand": -3.1, "inventory": 0.2, "season": -2.0, "total": -4.9}}
    d = rationale_drivers(r)
    assert 1 <= len(d) <= 3
    assert d[0]["text"].startswith("Fiyat konumunuz") and "%60" in d[0]["text"]
    assert all("endeks" not in x["text"].lower() for x in d)
    assert {"text", "dir"} <= set(d[0])
    assert rationale_drivers(None) == []


def test_dashboard_hero_shows_confidence_and_drivers(hotel_browser):
    html = hotel_browser.get("/panel").text
    hero = html.split('class="hero-rec"', 1)[1].split("</section>", 1)[0]
    assert "güven" in hero.lower()
    assert 'class="drivers"' in hero


def test_radar_outlier_does_not_crush_near_competitors():
    """Çok uzak tek bir rakip, yakın rakipleri merkeze sıkıştırmaz; kenara 'uzak' işaretiyle yerleşir."""
    from types import SimpleNamespace as NS

    from app.services.analytics import radar_layout

    me = NS(lat=37.03, lng=27.43)

    def comp(rank, dlat, dlng):
        return NS(competitor=NS(id=rank, lat=37.03 + dlat, lng=27.43 + dlng, name=f"R{rank}", star_rating=4),
                  rank=rank, is_manual=False, similarity_score=0.7)

    comps = [comp(1, 0.01, 0), comp(2, 0, 0.02), comp(3, -0.02, 0), comp(4, 0, -0.03), comp(5, 0.85, 0)]  # 5: ~94 km
    lay = radar_layout(me, comps)
    near = [p for p in lay["points"] if p["rank"] != 5]
    far = next(p for p in lay["points"] if p["rank"] == 5)
    assert far["outlier"] is True and abs(far["y"] - 50) > 40
    assert max(((p["x"] - 50) ** 2 + (p["y"] - 50) ** 2) ** 0.5 for p in near) > 15
    assert lay["max_km"] > 90


def test_admin_destructive_forms_confirm(admin_browser):
    """Geri dönüşü zor yönetim işlemleri sonucu açıklayan bir onay ister; yönetici kendini devre dışı bırakamaz."""
    for url, action in (("/admin/aboneler", "/admin/aboneler/"), ("/admin/faturalar", "/admin/faturalar/"),
                        ("/admin/kullanicilar", "/durum")):
        html = admin_browser.get(url).text
        forms = re.findall(r"<form[^>]*>", html)
        target = [f for f in forms if action in f and 'method="post"' in f]
        assert target, url
        assert all("data-confirm" in f for f in target), url
    users = admin_browser.get("/admin/kullanicilar").text
    me_row = next(r for r in users.split("<tr>") if "admin@otelradar.local" in r)
    assert "/durum" not in me_row
    bulk = admin_browser.get("/admin/oda-eslemeleri").text
    assert re.search(r'<form[^>]*id="bulk"[^>]*data-confirm', bulk)


def test_pipeline_has_single_primary_action(admin_browser):
    html = admin_browser.get("/admin/veri-hatti").text
    assert html.count("btn sm primary") <= 1
    assert "daily_pipeline</td>" not in html  # iş adları Türkçe etiketle gösterilir


def test_settings_email_option_is_honest(hotel_browser):
    html = hotel_browser.get("/panel/ayarlar").text
    assert "e-posta" in html.lower() and "yakında" in html.lower()


def test_error_toasts_are_not_auto_dismissed():
    """Hata ve uyarı bildirimleri kullanıcı kapatana kadar ekranda kalır (WCAG 2.2.1)."""
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert "alert.success" in js or "data-toast-auto" in js
