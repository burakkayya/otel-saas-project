"""Tanıtım sayfasındaki ürün görüntülerini çalışan uygulamadan üretir (demo veri, açık tema).

Kullanım (sunucu çalışırken):  python scripts/make_product_shots.py --base http://127.0.0.1:8020
Çıktı: app/static/img/shots/{panel,pazar,talep,oneri}.jpg ve her birinin piksel boyutu.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "app" / "static" / "img" / "shots"
SCALE = 1.5


def clip_of(page, selector: str, max_h: int | None = None, pad: int = 0) -> dict:
    box = page.locator(selector).first.bounding_box()
    h = min(box["height"], max_h) if max_h else box["height"]
    return {"x": box["x"] - pad, "y": box["y"] - pad, "width": box["width"] + 2 * pad, "height": h + 2 * pad}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=SCALE, color_scheme="light",
                                  locale="tr-TR", reduced_motion="reduce")
        ctx.add_init_script("try{localStorage.setItem('or-theme','light');localStorage.setItem('or-view','ayrinti')}catch(e){}")
        page = ctx.new_page()
        page.goto(a.base + "/giris")
        page.fill("input[name=email]", "otel@otelradar.local")
        page.fill("input[name=password]", "Demo1234!")
        page.click("form button[type=submit]")
        page.wait_for_load_state("networkidle")

        def shoot(name: str, url: str, selector: str, max_h: int | None = None, full: bool = True):
            page.goto(a.base + url)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(400)
            clip = clip_of(page, selector, max_h)
            page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=84, clip=clip, full_page=full)
            print(f"{name}.jpg {round(clip['width'] * SCALE)}x{round(clip['height'] * SCALE)}")

        shoot("panel", "/panel", "main.content", 860)
        shoot("pazar", "/panel/pazar", ".panel:has(.rate-grid)", 560)
        shoot("talep", "/panel/talep", ".panel:has(.heat-cal)", 560)
        page.goto(a.base + "/panel/oneriler")
        href = page.eval_on_selector("a[href^='/panel/oneriler/']:not([href*='yenile'])", "a => a.getAttribute('href')")
        shoot("oneri", href, ".panel:has(.waterfall)", 560)
        browser.close()


if __name__ == "__main__":
    main()
