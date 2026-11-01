"""Gerçek tarayıcıyla uçtan uca testler.

Çalıştırma:  pytest -m e2e tests/e2e
Gereksinim:  pip install playwright && python -m playwright install chromium
             (ya da sistemdeki Chrome için CHROME_PATH=/yol/chrome)
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e
playwright_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    tmp = Path(tempfile.mkdtemp(prefix="otelradar-e2e-"))
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp / 'e2e.db').as_posix()}", "PASSWORD_ITERATIONS": "1000",
           "DATA_PROVIDER": "demo", "ADMIN_EMAIL": "admin@otelradar.local", "ADMIN_PASSWORD": "Admin123!",
           "PYTHONPATH": str(ROOT)}
    subprocess.run([sys.executable, "-m", "app.cli", "seed", "--scale", "0.3", "--history", "45", "--horizon", "30"],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            import httpx

            if httpx.get(base + "/health", timeout=1).status_code == 200:
                break
        except Exception:  # noqa: BLE001 - sunucu henüz açılmadı
            time.sleep(0.5)
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        kw = {"args": ["--no-sandbox"]}
        if os.environ.get("CHROME_PATH"):
            kw["executable_path"] = os.environ["CHROME_PATH"]
        try:
            b = p.chromium.launch(**kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium başlatılamadı: {exc}")
        yield b
        b.close()


class Page:
    def __init__(self, page, base):
        self.page, self.base, self.errors = page, base, []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" and "ERR_" not in m.text else None)

    def go(self, path):
        resp = self.page.goto(self.base + path)
        self.page.wait_for_load_state("networkidle")
        return resp

    def login(self, email, password):
        self.go("/giris")
        self.page.fill("#email", email)
        self.page.fill("#password", password)
        self.page.click("form[action='/giris'] button[type=submit]")
        self.page.wait_for_load_state("networkidle")


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    p = Page(ctx.new_page(), server)
    yield p
    ctx.close()


def charts_drawn(page) -> int:
    return page.evaluate("""() => [...document.querySelectorAll('canvas[data-chart]')]
        .filter(c => window.Chart && Chart.getChart(c) && c.width > 0).length""")


def test_landing_and_pricing(page):
    page.go("/")
    assert "gerekçesiyle" in page.page.inner_text("h1")
    page.page.click("text=Paketler")
    page.page.wait_for_load_state("networkidle")
    assert page.page.locator(".plan").count() >= 3
    assert not page.errors


def test_hotel_navigation_and_charts(page):
    page.login("otel@otelradar.local", "Demo1234!")
    assert page.page.url.endswith("/panel")
    assert charts_drawn(page.page) >= 2
    links = page.page.eval_on_selector_all(".sidebar .nav a", "els => els.map(e => e.getAttribute('href'))")
    assert len(links) >= 12
    for href in links:
        resp = page.go(href)
        assert resp.status == 200, href
        expected = page.page.locator("canvas[data-chart]").count()
        assert charts_drawn(page.page) == expected, href
    assert not page.errors, page.errors


def test_apply_suggestion_from_list(page):
    page.login("otel@otelradar.local", "Demo1234!")
    page.go("/panel/oneriler")
    btn = page.page.locator("button:has-text('Uyguladım')").first
    btn.click()
    page.page.wait_for_load_state("networkidle")
    assert page.page.locator(".alert.success").count() == 1
    assert page.page.locator("text=Uygulandı").count() >= 1


def test_theme_toggle_persists(page):
    page.login("otel@otelradar.local", "Demo1234!")
    before = page.page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.page.click(".sidebar [data-theme-toggle]")
    after = page.page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert after in ("dark", "light") and after != before
    page.go("/panel/pazar")
    assert page.page.evaluate("document.documentElement.getAttribute('data-theme')") == after
    assert charts_drawn(page.page) >= 1


def test_mobile_menu(browser, server):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    p = Page(ctx.new_page(), server)
    p.login("otel@otelradar.local", "Demo1234!")
    sidebar_x = lambda: p.page.evaluate("document.querySelector('.sidebar').getBoundingClientRect().x")  # noqa: E731
    assert sidebar_x() < 0
    p.page.click("[data-menu]")
    p.page.wait_for_timeout(350)
    assert sidebar_x() >= 0
    width = p.page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390 + 1, "mobilde yatay kaydırma olmamalı"
    ctx.close()


def test_registration_in_browser(page):
    page.go("/kayit")
    page.page.fill("#hotel_name", "Tarayıcı Test Oteli")
    page.page.select_option("#province", "Antalya")
    options = page.page.eval_on_selector_all("#district option", "els => els.map(e => e.textContent)")
    assert "Belek" in options
    page.page.select_option("#district", "Belek")
    page.page.fill("#full_name", "Tarayıcı Testçi")
    page.page.fill("#email", "tarayici@test.local")
    page.page.check("input[name=kvkk]")
    page.page.click("button:has-text('otelimi bul')")
    page.page.wait_for_load_state("networkidle")
    assert "/kayit/eslestir" in page.page.url
    page.page.check("input[value=new]")
    page.page.fill("#password", "Parola123")
    page.page.fill("#password2", "Parola123")
    page.page.click("button:has-text('Hesabımı oluştur')")
    page.page.wait_for_load_state("networkidle")
    assert page.page.url.endswith("/panel/hos-geldiniz")


def test_admin_job_and_impersonation(page):
    page.login("admin@otelradar.local", "Admin123!")
    assert page.page.url.endswith("/admin")
    assert charts_drawn(page.page) >= 2
    page.go("/admin/veri-hatti")
    page.page.locator("form:has(input[value=uptake]) button").click()
    page.page.wait_for_load_state("networkidle")
    assert "başlatıldı" in page.page.inner_text(".flashes")
    page.go("/admin")
    page.page.locator("button[title='Otel panelini görüntüle']").first.click()
    page.page.wait_for_load_state("networkidle")
    assert "Yönetici görünümü" in page.page.inner_text("body")
    page.page.click("button:has-text('Yönetime dön')")
    page.page.wait_for_load_state("networkidle")
    assert "/admin" in page.page.url
    for path in ("/admin/api-maliyet", "/admin/model", "/admin/talep", "/admin/oteller/1"):
        assert page.go(path).status == 200
    assert not page.errors, page.errors
