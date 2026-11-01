"""Tüm ekranların görüntüsünü alır ve temel arayüz denetimlerini yapar.

Her ekran için açık/koyu tema ve masaüstü/mobil genişlikte:
  - tam sayfa ekran görüntüsü (JPEG),
  - konsol hataları ve yakalanmamış JS hataları,
  - yatay taşma (sayfa genişliği > pencere genişliği),
  - WCAG AA metin kontrastı ihlalleri (örneklenmiş),
  - erişilebilir adı olmayan düğme/bağlantı ve etiketsiz form alanları.

Kullanım (sunucu çalışırken):
    python scripts/ui_snapshots.py --base http://127.0.0.1:8020 --out docs/screenshots/after
    python scripts/ui_snapshots.py --base ... --out ... --html-out /tmp/html   # detektör için HTML dökümü
Sonuç özeti <out>/report.json dosyasına yazılır; çıkış kodu, hata/taşma varsa 1'dir.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HOTEL = ("otel@otelradar.local", "Demo1234!")
ADMIN = ("admin@otelradar.local", "Admin123!")

PUBLIC = [
    ("landing", "/"), ("pricing", "/fiyatlar"), ("login", "/giris"), ("register", "/kayit"),
    ("forgot", "/sifremi-unuttum"), ("kvkk", "/yasal/kvkk"), ("privacy", "/yasal/gizlilik"),
    ("terms", "/yasal/kullanim-kosullari"), ("404", "/olmayan-bir-sayfa"), ("register-match", "@register-match"),
]
HOTEL_PAGES = [
    ("panel", "/panel"), ("welcome", "/panel/hos-geldiniz"), ("suggestions", "/panel/oneriler"),
    ("suggestions-cal", "/panel/oneriler?gorunum=takvim"), ("suggestion-detail", "@suggestion"),
    ("market", "/panel/pazar"), ("market-rooms", "/panel/pazar?veri=oda"), ("competitors", "/panel/rakipler"),
    ("demand", "/panel/talep"), ("room-types", "/panel/oda-tipleri"), ("performance", "/panel/performans"),
    ("backtest", "/panel/backtest"), ("reports", "/panel/raporlar"), ("notifications", "/panel/bildirimler"),
    ("settings", "/panel/ayarlar"), ("subscription", "/panel/abonelik"), ("account", "/panel/hesap"),
    ("403", "/admin"),
]
ADMIN_PAGES = [
    ("admin", "/admin"), ("hotels", "/admin/oteller"), ("hotel-detail", "@hotel"), ("subscriptions", "/admin/aboneler"),
    ("plans", "/admin/paketler"), ("invoices", "/admin/faturalar"), ("users", "/admin/kullanicilar"),
    ("pipeline", "/admin/veri-hatti"), ("costs", "/admin/api-maliyet"), ("mappings", "/admin/oda-eslemeleri"),
    ("model", "/admin/model"), ("impact", "/admin/etki"), ("admin-demand", "/admin/talep"),
    ("compliance", "/admin/uyumluluk"), ("audit", "/admin/denetim"), ("system", "/admin/sistem"),
    ("impersonate", "@impersonate"),
]

AUDIT_JS = r"""
() => {
  const out = {overflow: 0, contrast: [], unnamed: [], unlabeled: []};
  const doc = document.scrollingElement || document.documentElement;
  out.overflow = Math.max(0, doc.scrollWidth - window.innerWidth);
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const bgOf = el => { let stack = [];
    for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none' && !s.backgroundImage.startsWith('linear-gradient(rgb')) return null;
      const c = parse(s.backgroundColor); if (c && c[3] > 0) { stack.push(c); if (c[3] >= 1) break; } }
    let base = [255, 255, 255];
    for (let i = stack.length - 1; i >= 0; i--) { const c = stack[i]; base = base.map((v, k) => c[k] * c[3] + v * (1 - c[3])); }
    return base; };
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (out.contrast.length >= 25) break;
    if (['SCRIPT', 'STYLE', 'SVG', 'PATH', 'CANVAS', 'OPTION'].includes(el.tagName.toUpperCase())) continue;
    const txt = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
    if (!txt) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || +s.opacity === 0) continue;
    const fg = parse(s.color); const bg = bgOf(el); if (!fg || !bg) continue;
    let o = 1; for (let e = el; e; e = e.parentElement) o *= +getComputedStyle(e).opacity;
    const f = fg.map((v, k) => k < 3 ? v * fg[3] * o + bg[k] * (1 - fg[3] * o) : v);
    const L1 = lum(f), L2 = lum(bg); const ratio = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
    const size = parseFloat(s.fontSize), weight = +s.fontWeight || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3 : 4.5;
    if (ratio < need) { const key = el.className + '|' + s.color;
      if (seen.has(key)) continue; seen.add(key);
      out.contrast.push({text: txt.slice(0, 40), ratio: Math.round(ratio * 100) / 100, need, cls: String(el.className).slice(0, 40), tag: el.tagName}); }
  }
  for (const el of document.querySelectorAll('a[href], button, [role=button]')) {
    const name = (el.getAttribute('aria-label') || el.textContent || el.title || '').trim();
    if (!name && el.getClientRects().length) out.unnamed.push(el.outerHTML.slice(0, 90));
  }
  for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=submit]), select, textarea')) {
    if (!el.getClientRects().length) continue;
    const id = el.id; const lab = (id && document.querySelector(`label[for="${id}"]`)) || el.closest('label');
    if (!lab && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !el.title) out.unlabeled.push(el.outerHTML.slice(0, 90));
  }
  return out;
}
"""


def login(page, base, creds):
    page.goto(base + "/giris")
    page.fill("input[name=email]", creds[0])
    page.fill("input[name=password]", creds[1])
    page.click("form button[type=submit]")
    page.wait_for_load_state("networkidle")


def resolve(page, base, path):
    if path == "@suggestion":
        page.goto(base + "/panel/oneriler")
        href = page.eval_on_selector("a[href^='/panel/oneriler/']:not([href*='yenile'])", "a => a.getAttribute('href')")
        return href
    if path == "@hotel":
        page.goto(base + "/admin/oteller")
        return page.eval_on_selector("a[href^='/admin/oteller/']", "a => a.getAttribute('href')")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    ap.add_argument("--out", required=True)
    ap.add_argument("--html-out")
    ap.add_argument("--widths", default="1440,390")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--only", help="yalnızca adı bu düzenli ifadeye uyan ekranlar")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    html_out = Path(a.html_out) if a.html_out else None
    if html_out:
        html_out.mkdir(parents=True, exist_ok=True)
    widths = [int(w) for w in a.widths.split(",")]
    themes = a.themes.split(",")
    only = re.compile(a.only) if a.only else None
    report: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for group, pages, creds in (("public", PUBLIC, None), ("hotel", HOTEL_PAGES, HOTEL), ("admin", ADMIN_PAGES, ADMIN)):
            for theme in themes:
                for width in widths:
                    ctx = browser.new_context(viewport={"width": width, "height": 900 if width > 600 else 844},
                                              color_scheme=theme, device_scale_factor=1, locale="tr-TR",
                                              reduced_motion="reduce")
                    ctx.add_init_script(f"try{{localStorage.setItem('or-theme','{theme}')}}catch(e){{}}")
                    page = ctx.new_page()
                    cur: dict[str, list[str]] = {"errors": []}
                    page.on("console", lambda m: m.type == "error" and cur["errors"].append(m.text))
                    page.on("pageerror", lambda x: cur["errors"].append(str(x)))
                    if creds:
                        login(page, a.base, creds)
                    for name, path in pages:
                        if only and not only.search(name):
                            continue
                        cur["errors"] = errors = []
                        if path == "@register-match":
                            page.goto(a.base + "/kayit")
                            page.fill("#hotel_name", "Deneme Bodrum Butik Otel")
                            page.fill("#full_name", "Deneme Yetkili")
                            page.fill("#email", "deneme-kayit@otelradar.test")
                            page.check("input[name=kvkk]")
                            page.click("form button[type=submit]")
                            page.wait_for_load_state("networkidle")
                            status = 200
                        elif path == "@impersonate":
                            page.goto(a.base + resolve(page, a.base, "@hotel"))
                            page.click("form[action$='/panel'] button[type=submit]")
                            page.wait_for_load_state("networkidle")
                            status = 200
                        else:
                            url = resolve(page, a.base, path)
                            resp = page.goto(a.base + url)
                            page.wait_for_load_state("networkidle")
                            status = resp.status if resp else 0
                        page.wait_for_timeout(250)
                        res = page.evaluate(AUDIT_JS)
                        fname = f"{group}-{name}-{width}-{theme}.jpg"
                        page.screenshot(path=str(out / fname), full_page=True, type="jpeg", quality=62)
                        if html_out and theme == themes[0] and width == widths[0]:
                            (html_out / f"{group}-{name}.html").write_text(page.content(), encoding="utf-8")
                        report.append({"group": group, "name": name, "path": page.url.replace(a.base, ""), "status": status,
                                       "width": width, "theme": theme, "errors": errors, **res, "shot": fname})
                        if creds and path == "@impersonate":
                            page.goto(a.base + "/panel")
                            page.click("form[action='/admin/panel-cik'] button")
                            page.wait_for_load_state("networkidle")
                    ctx.close()
        browser.close()

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [r for r in report if r["errors"] or r["overflow"] > 0]
    print(f"{len(report)} görünüm; konsol hatası veya taşma olan: {len(bad)}; "
          f"kontrast ihlali olan: {sum(1 for r in report if r['contrast'])}; "
          f"adsız öğe olan: {sum(1 for r in report if r['unnamed'])}; etiketsiz alan olan: {sum(1 for r in report if r['unlabeled'])}")
    for r in bad:
        print(" -", r["group"], r["name"], r["width"], r["theme"], "taşma", r["overflow"], r["errors"][:2])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
