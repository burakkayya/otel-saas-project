"""Ekranlar için veri derleme (panel, pazar, admin özetleri)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ApiUsage,
    CompetitorSet,
    Hotel,
    JobRun,
    Plan,
    PriceSuggestion,
    RateSnapshot,
    RoiEstimate,
    RoomType,
    Subscription,
)
from app.services.demand import demand_map
from app.services.market import _aware, category_price_by_hotel, compset_ids, latest_observations


def latest_suggestions(db: Session, rt_ids: list[int], start: date, end: date) -> dict[tuple[int, date], PriceSuggestion]:
    if not rt_ids:
        return {}
    rows = db.execute(
        select(PriceSuggestion).where(PriceSuggestion.room_type_id.in_(rt_ids), PriceSuggestion.stay_date >= start,
                                      PriceSuggestion.stay_date <= end)
        .order_by(PriceSuggestion.created_at, PriceSuggestion.id)
    ).scalars()
    out: dict[tuple[int, date], PriceSuggestion] = {}
    for s in rows:
        out[(s.room_type_id, s.stay_date)] = s
    return out


def primary_room_type(hotel: Hotel, category: str | None = None) -> RoomType | None:
    rts = sorted(hotel.room_types, key=lambda r: r.id)
    if category:
        for r in rts:
            if r.category == category:
                return r
    for pref in ("standard", "deluxe", "family", "suite", "other"):
        for r in rts:
            if r.category == pref:
                return r
    return rts[0] if rts else None


def suggestion_rows(db: Session, hotel: Hotel, start: date, end: date, category: str | None = None) -> list[dict]:
    rts = [r for r in hotel.room_types if not category or r.category == category]
    rt_ids = [r.id for r in rts]
    sugg = latest_suggestions(db, rt_ids, start, end)
    own = latest_observations(db, rt_ids, start, end)
    dm = demand_map(db, hotel.province, start, end)
    rows = []
    for rt in sorted(rts, key=lambda r: r.id):
        d = start
        while d <= end:
            s = sugg.get((rt.id, d))
            if s:
                o = own.get((rt.id, d))
                r = s.rationale or {}
                own_price = o.price_eur if o else None
                change = round((float(s.suggested_price) / own_price - 1) * 100, 1) if own_price else None
                ds = dm.get(d)
                rows.append({
                    "id": s.id, "room_type": rt, "date": d, "suggested": float(s.suggested_price),
                    "floor": float(s.price_floor or 0), "ceiling": float(s.price_ceiling or 0),
                    "own": own_price, "own_available": o.available if o else None,
                    "change": change, "median": r.get("comp_median"), "demand": float(ds.demand_score) if ds else r.get("demand_score"),
                    "demand_level": r.get("demand_level"), "text": r.get("text"), "confidence": r.get("confidence"),
                    "action": s.user_action, "created_at": s.created_at, "season": r.get("season_label"),
                })
            d += timedelta(days=1)
    return rows


def market_grid(db: Session, hotel: Hotel, category: str, start: date, end: date) -> dict:
    comp = compset_ids(db, hotel.id)
    ids = [hotel.id] + comp
    prices = category_price_by_hotel(db, ids, category, start, end)
    prev = category_price_by_hotel(db, ids, category, start, end, as_of=date.today() - timedelta(days=7))
    hotels = {h.id: h for h in db.execute(select(Hotel).where(Hotel.id.in_(ids))).scalars()}
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    rows = []
    for hid in ids:
        cells = []
        for d in dates:
            o = prices.get(hid, {}).get(d)
            p = prev.get(hid, {}).get(d)
            cells.append({
                "price": o.price_eur if o else None, "available": o.available if o else None,
                "closed": bool(o and o.price_eur is None),
                "change": round((o.price_eur / p.price_eur - 1) * 100, 1) if o and p and o.price_eur and p.price_eur else None,
            })
        rows.append({"hotel": hotels.get(hid), "is_self": hid == hotel.id, "cells": cells})
    medians, p25s, p75s, own_series = [], [], [], []
    for i in range(len(dates)):
        vals = [r["cells"][i]["price"] for r in rows if not r["is_self"] and r["cells"][i]["price"]]
        if vals:
            vals.sort()
            medians.append(round(statistics.median(vals), 2))
            p25s.append(round(vals[max(0, int((len(vals) - 1) * 0.25))], 2))
            p75s.append(round(vals[min(len(vals) - 1, int(round((len(vals) - 1) * 0.75)))], 2))
        else:
            medians.append(None)
            p25s.append(None)
            p75s.append(None)
        own_series.append(rows[0]["cells"][i]["price"])
    return {"dates": dates, "rows": rows, "median": medians, "p25": p25s, "p75": p75s, "own": own_series}


def hotel_dashboard(db: Session, hotel: Hotel, today: date | None = None) -> dict:
    today = today or date.today()
    end = today + timedelta(days=59)
    rt = primary_room_type(hotel)
    cat = rt.category if rt else "standard"
    rows = suggestion_rows(db, hotel, today, end, category=cat)
    rows = [r for r in rows if rt and r["room_type"].id == rt.id]
    grid = market_grid(db, hotel, cat, today, end)
    dm = demand_map(db, hotel.province, today, end)
    next30 = [r for r in rows if r["date"] <= today + timedelta(days=29)]
    own_avg = statistics.fmean([r["own"] for r in next30 if r["own"]]) if any(r["own"] for r in next30) else None
    sug_avg = statistics.fmean([r["suggested"] for r in next30]) if next30 else None
    med_now = [m for m in grid["median"][:30] if m]
    under = sum(1 for r in next30 if r["change"] is not None and r["change"] >= 8)
    over = sum(1 for r in next30 if r["change"] is not None and r["change"] <= -8)
    demand_vals = [float(dm[d].demand_score) for d in sorted(dm) if d <= today + timedelta(days=6)]
    labels = [d.isoformat() for d in grid["dates"]]
    by_date = {r["date"]: r for r in rows}
    return {
        "room_type": rt,
        "category": cat,
        "today_row": by_date.get(today),
        "kpi": {
            "sug_avg": sug_avg, "own_avg": own_avg,
            "sug_vs_own": round((sug_avg / own_avg - 1) * 100, 1) if sug_avg and own_avg else None,
            "median_avg": statistics.fmean(med_now) if med_now else None,
            "demand_7d": statistics.fmean(demand_vals) if demand_vals else None,
            "under": under, "over": over,
        },
        "chart": {
            "labels": labels,
            "suggested": [by_date[d]["suggested"] if d in by_date else None for d in grid["dates"]],
            "floor": [by_date[d]["floor"] if d in by_date else None for d in grid["dates"]],
            "ceiling": [by_date[d]["ceiling"] if d in by_date else None for d in grid["dates"]],
            "own": grid["own"], "median": grid["median"], "p25": grid["p25"], "p75": grid["p75"],
            "demand": [float(dm[d].demand_score) if d in dm else None for d in grid["dates"]],
        },
        "next7": [by_date[d] for d in sorted(by_date) if d <= today + timedelta(days=6)],
        "grid": grid,
    }


def admin_overview(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    subs = list(db.execute(select(Subscription)).scalars())
    active = [s for s in subs if s.status in ("active", "past_due")]
    trial = [s for s in subs if s.status == "trial"]
    mrr = sum(float(s.plan.monthly_price_eur) for s in active)
    # MRR geçmişi: son 6 ay, ay sonundaki aktif abonelikler
    ends, d = [], today
    for _ in range(6):
        ends.append(d)
        d = d.replace(day=1) - timedelta(days=1)
    mrr_series = []
    for m_end in reversed(ends):
        val = sum(float(s.plan.monthly_price_eur) for s in subs
                  if s.started_at <= m_end and (s.canceled_at is None or s.canceled_at > m_end) and s.status != "trial")
        mrr_series.append({"label": f"{m_end.month:02d}/{m_end.year}", "value": round(val, 2)})
    by_plan = defaultdict(int)
    for s in active + trial:
        by_plan[s.plan.name] += 1
    hotels = db.execute(select(func.count(Hotel.id))).scalar() or 0
    by_prov = dict(db.execute(select(Hotel.province, func.count(Hotel.id)).group_by(Hotel.province)).all())
    since = datetime.combine(today - timedelta(days=13), datetime.min.time(), tzinfo=timezone.utc)
    snaps = db.execute(
        select(func.date(RateSnapshot.observed_at), func.count(RateSnapshot.id))
        .where(RateSnapshot.observed_at >= since).group_by(func.date(RateSnapshot.observed_at))
    ).all()
    snap_series = {str(d)[:10]: c for d, c in snaps}
    usage = db.execute(
        select(ApiUsage.provider, func.sum(ApiUsage.requests)).where(ApiUsage.day >= today - timedelta(days=29))
        .group_by(ApiUsage.provider)
    ).all()
    last_runs = list(db.execute(select(JobRun).order_by(JobRun.started_at.desc()).limit(8)).scalars())
    failed_24h = db.execute(select(func.count(JobRun.id)).where(
        JobRun.status == "failed", JobRun.started_at >= datetime.now(timezone.utc) - timedelta(hours=24))).scalar() or 0
    low_conf = db.execute(select(func.count(RoomType.id)).where(RoomType.confidence < 0.75, RoomType.reviewed.is_(False))).scalar() or 0
    roi = list(db.execute(select(RoiEstimate).where(RoiEstimate.method == "control_group_did")
                          .order_by(RoiEstimate.created_at.desc()).limit(20)).scalars())
    last_snapshot = db.execute(select(func.max(RateSnapshot.observed_at))).scalar()
    runs14 = db.execute(select(JobRun.started_at, JobRun.status).where(
        JobRun.started_at >= datetime.now(timezone.utc) - timedelta(days=14))).all()
    by_day: dict[date, set] = defaultdict(set)
    for started, status in runs14:
        by_day[_aware(started).date()].add(status)
    health = []
    for i in range(14):
        d = today - timedelta(days=13 - i)
        st = by_day.get(d, set())
        kind = "none" if not st else "fail" if st == {"failed"} else "mixed" if "failed" in st else "ok"
        health.append({"day": d.isoformat(), "kind": kind, "statuses": sorted(st)})
    return {
        "mrr": mrr, "arr": mrr * 12, "active": len(active), "trial": len(trial),
        "canceled": sum(1 for s in subs if s.status == "canceled"),
        "arpa": mrr / len(active) if active else 0,
        "mrr_series": mrr_series, "by_plan": dict(by_plan), "hotels": hotels, "by_province": by_prov,
        "snap_series": [{"day": (today - timedelta(days=13 - i)).isoformat(),
                         "count": snap_series.get((today - timedelta(days=13 - i)).isoformat(), 0)} for i in range(14)],
        "usage": {p: int(r or 0) for p, r in usage}, "last_runs": last_runs, "failed_24h": failed_24h,
        "low_conf": low_conf, "roi": roi, "health": health, "last_snapshot": _aware(last_snapshot) if last_snapshot else None,
        "plans": list(db.execute(select(Plan).order_by(Plan.sort_order)).scalars()),
        "compsets": db.execute(select(func.count(func.distinct(CompetitorSet.hotel_id)))).scalar() or 0,
    }


def radar_layout(hotel: Hotel, competitors: list, prices: dict | None = None) -> dict:
    """Rakipleri otel merkezde olacak şekilde yön (kerteriz) ve mesafeye göre radar düzlemine yerleştirir.
    Mesafe karekök ölçekte gösterilir; böylece 0,5 km ile 40 km aynı ekranda okunabilir."""
    import math

    from app.services.compset import haversine_km

    pts = []
    for c in competitors:
        h = c.competitor
        if h.lat is None or hotel.lat is None:
            continue
        d = haversine_km(hotel.lat, hotel.lng, h.lat, h.lng)
        lat1, lat2 = math.radians(float(hotel.lat)), math.radians(float(h.lat))
        dlng = math.radians(float(h.lng) - float(hotel.lng))
        bearing = math.atan2(math.sin(dlng) * math.cos(lat2),
                             math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng))
        pts.append({"hotel": h, "rank": c.rank, "dist": d, "bearing": bearing, "manual": c.is_manual,
                    "score": float(c.similarity_score) if c.similarity_score is not None else None,
                    "price": (prices or {}).get(h.id)})
    max_d = max([p["dist"] for p in pts] + [1.0])
    ring_km = [r for r in (1, 2, 5, 10, 20, 50, 100) if r <= max_d * 1.05][-3:] or [round(max_d, 1)]
    scale_max = max(max_d, ring_km[-1]) * 1.08
    for p in pts:
        r = math.sqrt(p["dist"] / scale_max) * 46  # merkezden yüzde (viewBox 100)
        p["x"] = round(50 + r * math.sin(p["bearing"]), 2)
        p["y"] = round(50 - r * math.cos(p["bearing"]), 2)
    rings = [{"km": km, "r": round(math.sqrt(km / scale_max) * 46, 2)} for km in ring_km]
    return {"points": pts, "rings": rings, "max_km": round(max_d, 1)}
