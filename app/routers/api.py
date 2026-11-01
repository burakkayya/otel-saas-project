"""JSON API (oturum çerezi ile). Panel grafikleri ve harici entegrasyon için temel.
Not: Harici sistemler için API anahtarı tabanlı kimlik doğrulama açık konudur."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.services import analytics
from app.services.demand import demand_map
from app.web import HotelContext, require_admin, require_hotel, require_user

router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/me")
def me(user: User = Depends(require_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role, "hotel_id": user.hotel_id}


@router.get("/suggestions")
def suggestions(days: int = Query(30, ge=1, le=90), category: str | None = None,
                hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    today = date.today()
    rows = analytics.suggestion_rows(db, hc.hotel, today, today + timedelta(days=days - 1), category=category)
    return [{
        "id": r["id"], "stay_date": r["date"].isoformat(), "room_type": r["room_type"].raw_name,
        "category": r["room_type"].category, "suggested_price_eur": r["suggested"], "floor_eur": r["floor"],
        "ceiling_eur": r["ceiling"], "current_price_eur": r["own"], "change_pct": r["change"],
        "comp_median_eur": r["median"], "demand_score": r["demand"], "rationale": r["text"],
    } for r in rows]


@router.get("/market")
def market(category: str = "standard", days: int = Query(14, ge=1, le=60), hc: HotelContext = Depends(require_hotel),
           db: Session = Depends(get_db)):
    today = date.today()
    g = analytics.market_grid(db, hc.hotel, category, today, today + timedelta(days=days - 1))
    return {
        "dates": [d.isoformat() for d in g["dates"]],
        "median": g["median"], "own": g["own"],
        "hotels": [{"name": r["hotel"].name if r["hotel"] else None, "is_self": r["is_self"],
                    "prices": [c["price"] for c in r["cells"]], "available": [c["available"] for c in r["cells"]]}
                   for r in g["rows"]],
    }


@router.get("/demand")
def demand(days: int = Query(60, ge=1, le=180), hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    today = date.today()
    dm = demand_map(db, hc.hotel.province, today, today + timedelta(days=days - 1))
    return [{"date": d.isoformat(), "score": float(s.demand_score), "flight": float(s.flight_score or 0),
             "event": float(s.event_score or 0), "holiday": float(s.holiday_score or 0),
             "components": s.components} for d, s in sorted(dm.items())]


@router.get("/admin/overview")
def admin_overview(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    ov = analytics.admin_overview(db)
    return {"mrr": ov["mrr"], "active": ov["active"], "trial": ov["trial"], "hotels": ov["hotels"],
            "by_plan": ov["by_plan"], "usage_30d": ov["usage"], "failed_jobs_24h": ov["failed_24h"]}
