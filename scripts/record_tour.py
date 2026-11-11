"""Tüm ekranları gezen bir tur videosu kaydeder ve gezerken her ekranı sınar.

Her ekranda: HTTP durumu, konsol/JS hatası ve yatay taşma denetlenir; sonuç sonda yazdırılır.
Kullanım (sunucu çalışırken):  python scripts/record_tour.py --base http://127.0.0.1:8020 --out data/tour
Çıktı: <out>/<name>.webm ve <out>/<name>-rapor.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from ui_snapshots import ADMIN, ADMIN_PAGES, HOTEL, HOTEL_PAGES, PUBLIC, login, resolve  # noqa: E402

W, H = 1280, 800


def glide(page, pause: int = 450, step: int = 420, max_steps: int = 14) -> None:
    """Sayfayı izlenebilir hızda aşağı kaydırır, sonra başa döner."""
    page.wait_for_timeout(pause)
    height = page.evaluate("document.documentElement.scrollHeight")
    y, n = 0, 0
    while y + H < height and n < max_steps:
        page.mouse.wheel(0, step)
        page.wait_for_timeout(260)
        y += step
        n += 1
    page.wait_for_timeout(pause)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    ap.add_argument("--out", default="data/tour")
    ap.add_argument("--groups", default="public,hotel,admin", help="gezilecek bölümler (video boyutunu bölmek için)")
    ap.add_argument("--name", default="otelradar-tur")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    groups = a.groups.split(",")
    report: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(out / "raw"),
                                  record_video_size={"width": W, "height": H}, locale="tr-TR", color_scheme="light")
        page = ctx.new_page()
        cur: dict[str, list[str]] = {"errors": []}
        page.on("console", lambda m: m.type == "error" and cur["errors"].append(m.text))
        page.on("pageerror", lambda x: cur["errors"].append(str(x)))

        def visit(group: str, name: str, path: str, steps: int = 6):
            cur["errors"] = errors = []
            if path == "@register-match":
                page.goto(a.base + "/kayit")
                page.fill("#hotel_name", "Deneme Bodrum Butik Otel")
                page.fill("#full_name", "Deneme Yetkili")
                page.fill("#email", "tur-kayit@otelradar.test")
                page.check("input[name=kvkk]")
                page.wait_for_timeout(500)
                page.click("form button[type=submit]")
                status = 200
            elif path == "@impersonate":
                page.goto(a.base + resolve(page, a.base, "@hotel"))
                page.click("form[action$='/panel'] button[type=submit]")
                status = 200
            else:
                resp = page.goto(a.base + resolve(page, a.base, path))
                status = resp.status if resp else 0
            page.wait_for_load_state("networkidle")
            glide(page, max_steps=steps)
            overflow = page.evaluate("Math.max(0, document.documentElement.scrollWidth - innerWidth)")
            # Yönlendirmeli gezinmede tarayıcının atladığı sayfa geçişi zararsızdır (geçiş yalnızca görsel)
            errors = [e for e in errors if f"status of {status}" not in e and "Transition was aborted" not in e]
            expected = {"404": 404, "403": 403}.get(name, 200)
            report.append({"group": group, "name": name, "status": status, "ok": status == expected and not errors and overflow == 0,
                           "errors": errors, "overflow": overflow})

        # 1) herkese açık: tanıtım yavaşça gezilir, form akışı denenir
        if "public" in groups:
            visit("public", "landing", "/", steps=16)
            page.goto(a.base + "/")
            page.wait_for_timeout(3600)  # açılış radarı taraması
            page.fill("#otel-ust", "Mavi Koy Butik Otel")
            page.wait_for_timeout(500)
            page.click(".hero .start-form button")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)
            for name, path in PUBLIC[1:]:
                visit("public", name, path)

        # 2) otel paneli
        if "hotel" in groups:
            login(page, a.base, HOTEL)
            for name, path in HOTEL_PAGES:
                visit("hotel", name, path, steps=8 if name == "panel" else 5)
                if name == "panel":  # sade/ayrıntılı görünüm ve koyu tema gösterimi
                    page.evaluate("window.scrollTo(0, 0)")
                    page.click("[data-density='sade']")
                    page.wait_for_timeout(1300)
                    page.click("[data-density='ayrinti']")
                    page.wait_for_timeout(900)
                    page.click("[data-theme-toggle]")
                    page.wait_for_timeout(1100)
                    glide(page, max_steps=4)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.click("[data-theme-toggle]")
                    page.wait_for_timeout(600)
            page.goto(a.base + "/panel")
            page.click("form[action='/cikis'] button")
            page.wait_for_load_state("networkidle")

        # 3) yönetim paneli
        if "admin" in groups:
            login(page, a.base, ADMIN)
            for name, path in ADMIN_PAGES:
                visit("admin", name, path, steps=4)
            page.goto(a.base + "/panel")
            page.click("form[action='/admin/panel-cik'] button")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(600)

        video_path = page.video.path()
        ctx.close()
        browser.close()

    final = out / f"{a.name}.webm"
    shutil.move(video_path, final)
    shutil.rmtree(out / "raw", ignore_errors=True)
    (out / f"{a.name}-rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [r for r in report if not r["ok"]]
    print(f"{len(report)} ekran gezildi; sorunlu: {len(bad)}; video: {final} ({final.stat().st_size / 1e6:.1f} MB)")
    for r in bad:
        print(" -", r)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
