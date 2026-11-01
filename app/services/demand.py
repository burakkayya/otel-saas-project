"""Talep sinyali: uçuş arama trendi (Amadeus) + etkinlik (PredictHQ) + tatil takvimi."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DemandSignal, Event, utcnow
from app.services.calendar_tr import holiday_name, holiday_score

WEIGHTS = {"flight": 0.45, "event": 0.35, "holiday": 0.20}


def demand_level(score: float) -> str:
    if score >= 70:
        return "Çok yüksek"
    if score >= 55:
        return "Yüksek"
    if score >= 40:
        return "Normal"
    if score >= 25:
        return "Düşük"
    return "Çok düşük"


def combine(flight: float, event: float, holiday: float) -> float:
    return round(max(0.0, min(100.0, WEIGHTS["flight"] * flight + WEIGHTS["event"] * event + WEIGHTS["holiday"] * holiday)), 1)


def refresh_events(db: Session, provider, province: str, start: date, end: date) -> int:
    count = 0
    for ev in provider.events(province, start, end):
        row = db.execute(select(Event).where(Event.external_id == ev.external_id)).scalar_one_or_none()
        if row is None:
            row = Event(external_id=ev.external_id, province=province, source=getattr(provider, "name", "api"))
            db.add(row)
            count += 1
        row.name, row.category, row.district = ev.name, ev.category, ev.district
        row.start_date, row.end_date, row.impact = ev.start_date, ev.end_date, ev.impact
    db.flush()
    return count


def refresh_demand(db: Session, provider, province: str, start: date, end: date, source: str = "demo") -> int:
    refresh_events(db, provider, province, start - timedelta(days=7), end)
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    flights = provider.flight_search_index(province, dates)
    events = list(db.execute(
        select(Event).where(Event.province == province, Event.end_date >= start, Event.start_date <= end)
    ).scalars())
    existing = {
        r.date: r for r in db.execute(
            select(DemandSignal).where(DemandSignal.province == province, DemandSignal.date >= start, DemandSignal.date <= end)
        ).scalars()
    }
    for d in dates:
        active = [e for e in events if e.start_date <= d <= e.end_date]
        ev_score = min(100.0, float(sum(e.impact for e in active)))
        hol = holiday_score(d)
        fl = float(flights.get(d, 50.0))
        score = combine(fl, ev_score, hol)
        row = existing.get(d)
        if row is None:
            row = DemandSignal(province=province, date=d)
            db.add(row)
        row.flight_score, row.event_score, row.holiday_score, row.demand_score = fl, ev_score, hol, score
        row.components = {
            "events": [e.name for e in active],
            "holiday": holiday_name(d),
            "weights": WEIGHTS,
        }
        row.source = source
        row.updated_at = utcnow()
    db.flush()
    return len(dates)


def demand_map(db: Session, province: str, start: date, end: date) -> dict[date, DemandSignal]:
    return {
        r.date: r for r in db.execute(
            select(DemandSignal).where(DemandSignal.province == province, DemandSignal.date >= start, DemandSignal.date <= end)
        ).scalars()
    }
