"""Herkese açık sayfalar, kimlik doğrulama, yetki ve kayıt akışı."""
import re

import pytest
from sqlalchemy import select

from app.models import Hotel, Subscription, User
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, HOTEL_EMAIL, HOTEL_PASSWORD, Browser, csrf_from, login


@pytest.mark.parametrize("url", ["/", "/fiyatlar", "/yasal/kvkk", "/yasal/gizlilik", "/yasal/kullanim-kosullari",
                                 "/giris", "/kayit", "/sifremi-unuttum", "/health", "/api/docs"])
def test_public_pages(client, url):
    r = client.get(url)
    assert r.status_code == 200
    if url != "/health" and url != "/api/docs":
        assert "<html" in r.text and "OtelRadar" in r.text


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_404_page(client):
    r = client.get("/olmayan-sayfa")
    assert r.status_code == 404 and "Sayfa bulunamadı" in r.text
    assert client.get("/yasal/olmayan").status_code == 404
    assert client.get("/api/v1/olmayan").json()["detail"]


@pytest.mark.parametrize("url", ["/panel", "/panel/oneriler", "/admin", "/admin/oteller"])
def test_protected_pages_redirect_to_login(client, url):
    r = client.get(url, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/giris?next=")


def test_api_requires_session(client):
    assert client.get("/api/v1/me").status_code == 401


def test_login_logout(client):
    r = login(client, HOTEL_EMAIL, HOTEL_PASSWORD)
    assert r.status_code == 303 and r.headers["location"] == "/panel"
    assert client.get("/api/v1/me").json()["email"] == HOTEL_EMAIL
    # giriş yapmışken /giris panele yönlendirir
    assert client.get("/giris", follow_redirects=False).headers["location"] == "/panel"
    tok = csrf_from(client, "/fiyatlar")
    r = client.post("/cikis", data={"csrf_token": tok}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/api/v1/me").status_code == 401


def test_login_next_and_open_redirect_guard(client):
    tok = csrf_from(client)
    r = client.post("/giris", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "csrf_token": tok,
                                    "next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/admin"


def test_wrong_password_and_rate_limit(client):
    for _ in range(5):
        r = login(client, "kilit@test.local", "yanlis")
        assert r.status_code == 401 and "hatalı" in r.text
    assert login(client, "kilit@test.local", "yanlis").status_code == 429


def test_csrf_required(client):
    r = client.post("/giris", data={"email": HOTEL_EMAIL, "password": HOTEL_PASSWORD})
    assert r.status_code == 400 and "doğrulaması" in r.text


def test_role_separation(hotel_browser, admin_browser):
    assert hotel_browser.get("/admin").status_code == 403
    assert hotel_browser.get("/api/v1/admin/overview").status_code == 403
    # yönetici, otel seçmeden otel paneline giremez
    assert admin_browser.get("/panel").status_code == 403


def test_inactive_user_cannot_login(client, db):
    u = db.execute(select(User).where(User.email == "otel3@otelradar.local")).scalar_one_or_none()
    if u is None:
        pytest.skip("üçüncü demo kullanıcısı yok")
    u.is_active = False
    db.commit()
    try:
        assert login(client, "otel3@otelradar.local", "Demo1234!").status_code == 401
    finally:
        u.is_active = True
        db.commit()


def _register(b: Browser, **over):
    data = {"hotel_name": "Test Lavanta Butik Otel", "address": "Gümbet Mah. 1", "province": "Muğla",
            "district": "Bodrum", "star_rating": "4", "full_name": "Test Yetkili", "email": "yeni@test.local",
            "plan_code": "profesyonel", "kvkk": "1"}
    data.update(over)
    return b.post("/kayit", data)


def test_registration_validation(client):
    b = Browser(client)
    r = _register(b, email="gecersiz", kvkk="", province="İzmir", hotel_name="ab")
    assert r.status_code == 422
    for msg in ("Geçerli bir e-posta", "KVKK", "Muğla ve Antalya", "en az 3"):
        assert msg in r.text
    r = _register(b, email=HOTEL_EMAIL)
    assert "zaten" in r.text


def test_registration_flow_match_existing(client, db):
    b = Browser(client)
    r = _register(b, email="eslesen@test.local")
    assert r.status_code == 303 and r.headers["location"] == "/kayit/eslestir"
    page = client.get("/kayit/eslestir")
    assert page.status_code == 200 and "Bu otel siz misiniz" in page.text
    choice = re.search(r'name="hotel_choice" value="(\d+)"', page.text).group(1)
    # parola uyuşmazlığı
    r = b.post("/kayit/tamamla", {"hotel_choice": choice, "password": "Parola123", "password2": "Parola124"})
    assert r.status_code == 422 and "eşleşmiyor" in r.text
    r = b.post("/kayit/tamamla", {"hotel_choice": choice, "password": "Parola123", "password2": "Parola123"})
    assert r.status_code == 303 and r.headers["location"] == "/panel/hos-geldiniz"
    welcome = client.get("/panel/hos-geldiniz")
    assert welcome.status_code == 200 and "İlk önerileriniz hazır" in welcome.text
    user = db.execute(select(User).where(User.email == "eslesen@test.local")).scalar_one()
    hotel = db.get(Hotel, user.hotel_id)
    assert hotel.id == int(choice) and hotel.is_subscriber
    sub = db.execute(select(Subscription).where(Subscription.hotel_id == hotel.id)).scalar_one()
    assert sub.status == "trial"
    assert client.get("/panel/oneriler").status_code == 200
    # kurulum tamamlama
    r = Browser(client).post("/panel/hos-geldiniz")
    assert r.status_code == 303


def test_registration_flow_new_hotel(client, db):
    b = Browser(client)
    _register(b, email="yeniotel@test.local", hotel_name="Tamamen Farklı Bir İsim Otel", province="Antalya", district="Kaş")
    r = b.post("/kayit/tamamla", {"hotel_choice": "new", "password": "Parola123", "password2": "Parola123"})
    assert r.status_code == 303
    user = db.execute(select(User).where(User.email == "yeniotel@test.local")).scalar_one()
    hotel = db.get(Hotel, user.hotel_id)
    assert hotel.source_id is None and hotel.lat is not None
    assert {rt.category for rt in hotel.room_types} == {"standard", "deluxe"}
    dash = client.get("/panel")
    assert dash.status_code == 200 and "OTA kaynaklarında bulunamadı" in client.get("/panel/bildirimler").text


def test_match_without_pending_redirects(client):
    assert client.get("/kayit/eslestir", follow_redirects=False).headers["location"] == "/kayit"


def test_forgot_password_does_not_leak(client):
    b = Browser(client)
    r1 = b.post("/sifremi-unuttum", {"email": HOTEL_EMAIL})
    r2 = b.post("/sifremi-unuttum", {"email": "yok@yok.local"})
    assert r1.status_code == r2.status_code == 200
    assert "talebiniz alındı" in r1.text and "talebiniz alındı" in r2.text
