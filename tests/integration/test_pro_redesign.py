"""Profesyonel arayüz turu: tanıtım akışı, iddialı ama doğru metin, panel görünüm seçimi, marka varlıkları."""
from pathlib import Path


def test_landing_start_form_prefills_registration(client):
    """Tanıtımdaki 'otelinizin adı' kutusu kayıt formunu önceden doldurur."""
    html = client.get("/").text
    assert 'action="/kayit"' in html and 'name="otel"' in html
    reg = client.get("/kayit", params={"otel": "  Mavi Koy Butik Otel  "}).text
    assert 'value="Mavi Koy Butik Otel"' in reg
    long = client.get("/kayit", params={"otel": "x" * 400}).text
    assert 'value="' + "x" * 120 + '"' in long
    assert "<script>alert(1)</script>" not in client.get("/kayit", params={"otel": "<script>alert(1)</script>"}).text


def test_landing_has_no_unbacked_claims(client):
    """İddialı ama doğru: uydurma müşteri sayısı, referans ya da kesin gelir artışı vaadi yok."""
    html = client.get("/").text.lower()
    for phrase in ("gelirinizi artır", "garanti", "müşterimiz", "daha fazla gelir", "ek kâr", "kurtarılan gelir"):
        assert phrase not in html
    assert "ölçülür" in html and "güven düzeyi" in html


def test_landing_sample_is_labelled(client):
    """Açılıştaki kurgusal öneri 'örnek' olarak etiketlidir."""
    assert "Örnek öneri" in client.get("/").text


def test_dashboard_has_view_toggle(hotel_browser):
    html = hotel_browser.get("/panel").text
    assert 'data-density="sade"' in html and 'data-density="ayrinti"' in html
    assert html.count("detail-only") >= 3


def test_product_shots_exist_and_are_local(client):
    """Tanıtımdaki ürün görüntüleri yerel dosyalardır ve gerçekten vardır."""
    import re

    html = client.get("/").text
    srcs = re.findall(r'<img src="(/static/img/shots/[^"?]+)', html)
    assert len(srcs) >= 4
    for s in srcs:
        assert Path("app" + s).exists(), s
        assert client.get(s).status_code == 200


def test_logo_mark_is_shared(client, hotel_browser):
    """Yeni logo işareti (radar halkası + tarama dilimi) her düzende aynı makrodan gelir; favicon günceldir."""
    for html in (client.get("/").text, client.get("/giris").text, hotel_browser.get("/panel").text):
        assert 'class="bm-sweep"' in html
    assert "bm" not in Path("app/static/img/favicon.svg").read_text(encoding="utf-8")
    assert client.get("/static/img/favicon.svg").status_code == 200


def test_all_landing_samples_are_labelled(client):
    """Kurgusal veri gösteren her görsel (canlı panel ve ürün görüntüleri) 'Örnek veri' etiketi taşır."""
    html = client.get("/").text
    assert html.count("Örnek veri") >= 5


def test_public_copy_avoids_outcome_promises(client):
    """Tanıtım ve paket metinleri kesin sonuç vaat etmez, tutarlıdır ve pilot kapsamını söyler."""
    landing, pricing = client.get("/").text, client.get("/fiyatlar").text
    for phrase in ("rakiplerinizden önce", "doğru fiyat.", "kaldıramayacağı", "Ertesi sabah", "Rakiplerimi göster"):
        assert phrase not in landing and phrase not in pricing, phrase
    assert "Pilot dönemde" in pricing and "OTA" in pricing


def test_reveal_hidden_state_requires_running_js():
    """Ürün görüntülerinin gizli başlangıcı yalnızca app.js gözlemciyi kurduğunda geçerlidir (JS hatasında içerik görünür)."""
    css = Path("app/static/css/site.css").read_text(encoding="utf-8")
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert ".reveal-ready .reveal" in css and ".js-motion .reveal" not in css
    assert 'classList.add("reveal-ready")' in js and "@media print { .reveal" in css


def test_hero_shows_detected_status_instead_of_manual_button(hotel_browser):
    """Kahraman alanda elle 'Uyguladım' yok; sistemin tespit ettiği durum rozeti var."""
    html = hotel_browser.get("/panel").text
    hero = html.split('class="hero-rec"', 1)[1].split("</section>", 1)[0]
    assert "/aksiyon" not in hero and "Uyguladım" not in hero
    assert any(s in hero for s in ("Uygulandı", "Kısmen uygulandı", "Uygulanmadı", "Henüz gözlenmedi"))
