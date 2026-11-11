"""Marka varlıklarını üretir: favicon ve deniz haritası eş derinlik çizgileri (tanıtım ve giriş zemini).

Kullanım:  python scripts/make_brand_assets.py
Çıktılar deterministiktir; app/static/img altına yazılır.
"""
from __future__ import annotations

import math
from pathlib import Path

IMG = Path(__file__).resolve().parents[1] / "app" / "static" / "img"

# Logo işareti: radar halkası (Otel'in O'su), 60° tarama dilimi, dilimin içinde bulunan otel noktası.
MARK = """<circle cx="16" cy="16" r="12.3" fill="none" stroke="{ring}" stroke-width="2.6"/>
<circle cx="16" cy="16" r="6.2" fill="none" stroke="{ring}" stroke-width="1.5" opacity=".38"/>
<path d="M16 16V3.7A12.3 12.3 0 0 1 26.65 9.85Z" fill="{sweep}"/>
<circle cx="20.6" cy="10.4" r="2.25" fill="{dot}"/>
<circle cx="16" cy="16" r="1.9" fill="{ring}"/>"""


def favicon() -> str:
    mark = MARK.format(ring="#ffffff", sweep="#3d8fe6", dot="#f2b84b")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            f'<rect width="32" height="32" rx="7.5" fill="#0f2b3d"/><g transform="translate(3.2 3.2) scale(.8)">{mark}</g></svg>\n')


def contours(w: int = 1600, h: int = 900, levels: int = 13) -> str:
    """Bir koyun eş derinlik çizgilerini andıran, iç içe düzensiz kapalı eğriler."""
    cx, cy = w * 0.68, h * 0.46
    paths = []
    for i in range(levels):
        base = 70 + i * 62
        pts = []
        for k in range(73):
            a = k / 72 * math.tau
            r = base * (1 + 0.16 * math.sin(3 * a + i * 0.35) + 0.09 * math.sin(5 * a - i * 0.6) + 0.05 * math.sin(9 * a + 1.3))
            pts.append((cx + r * 1.45 * math.cos(a), cy + r * math.sin(a)))
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
        paths.append(f'<path d="{d}" opacity="{0.55 - i * 0.03:.2f}"/>')
    ticks = "".join(f'<path d="M{x} 0v{h}" opacity=".12"/>' for x in range(200, w, 200))
    ticks += "".join(f'<path d="M0 {y}h{w}" opacity=".12"/>' for y in range(150, h, 150))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid slice" '
            f'fill="none" stroke="#7fb6e6" stroke-width="1">{"".join(paths)}{ticks}</svg>\n')


if __name__ == "__main__":
    (IMG / "favicon.svg").write_text(favicon(), encoding="utf-8", newline="\n")
    (IMG / "chart-contours.svg").write_text(contours(), encoding="utf-8", newline="\n")
    print("favicon.svg, chart-contours.svg yazıldı")
