"""Herkese açık sayfalar: tanıtım, paketler, yasal metinler, sağlık kontrolü."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Hotel, Plan, User
from app.web import current_user, render

router = APIRouter()


def sample_radar() -> dict:
    """Tanıtım ve giriş sayfalarındaki örnek radar (kurgusal rakipler)."""
    import math

    pts = []
    sample = [(35, 1.2, .82, 172), (110, 3.4, .74, 158), (200, 2.1, .69, 161), (265, 6.5, .58, 149), (320, 9.0, .51, 186)]
    for i, (deg, km, score, price) in enumerate(sample, start=1):
        r = math.sqrt(km / 11) * 46
        pts.append({"hotel": {"name": f"Örnek rakip {i}"}, "rank": i, "dist": km, "score": score, "manual": i == 4, "price": price,
                    "delay": round(deg / 360 * 2.2, 2),  # tarama ışını bu rakibe ulaştığında belirir
                    "x": round(50 + r * math.sin(math.radians(deg)), 2), "y": round(50 - r * math.cos(math.radians(deg)), 2)})
    rings = [{"km": km, "r": round(math.sqrt(km / 11) * 46, 2)} for km in (2, 5, 10)]
    return {"points": pts, "rings": rings, "max_km": 9.0}

LEGAL = {
    "gizlilik": "Gizlilik Politikası",
    "kvkk": "KVKK Aydınlatma Metni",
    "kullanim-kosullari": "Kullanım Koşulları",
}


@router.get("/")
def landing(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    plans = list(db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)).scalars())
    tracked = db.execute(select(func.count(Hotel.id)).where(Hotel.is_active.is_(True))).scalar() or 0
    return render(request, "public/landing.html", plans=plans, user=user, tracked=tracked, radar=sample_radar())


@router.get("/fiyatlar")
def pricing(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    plans = list(db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)).scalars())
    return render(request, "public/pricing.html", plans=plans, user=user)


@router.get("/yasal/{slug}")
def legal(slug: str, request: Request, user: User | None = Depends(current_user)):
    if slug not in LEGAL:
        raise HTTPException(404)
    return render(request, "public/legal.html", slug=slug, title=LEGAL[slug], user=user, legal_pages=LEGAL)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
