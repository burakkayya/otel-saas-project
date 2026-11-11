"""Otel (müşteri) paneli."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (
    CATEGORY_LABELS,
    AppliedObservation,
    CompetitorSet,
    Event,
    Hotel,
    Notification,
    Plan,
    PriceSuggestion,
    RoiEstimate,
    RoomType,
    Subscription,
)
from app.security import hash_password, password_problems, verify_password
from app.services import analytics
from app.services.backtest import run_backtest
from app.services.calendar_tr import holidays_between
from app.services.compset import add_manual_competitor, build_compset, rank_candidates, remove_competitor, set_feedback
from app.services.demand import demand_map
from app.services.market import category_price_by_hotel, latest_observations
from app.services.occupancy import compset_occupancy
from app.services.outcomes import STATUS_LABELS, outcome_summary, status_map
from app.services.pipeline import ensure_hotel_settings, get_setting
from app.services.pricing import STRATEGY_LABEL, generate_for_hotel
from app.services.seasonality import MONTHS_TR, monthly_coefficients
from app.services.uptake import uptake_stats
from app.web import HotelContext, audit, csrf_protect, redirect, render, require_hotel, unread_count

router = APIRouter(prefix="/panel")


def ctx(request: Request, hc: HotelContext, db: Session, active: str, **extra) -> dict:
    sub = hc.hotel.active_subscription
    return {"user": hc.user, "hotel": hc.hotel, "impersonating": hc.impersonating, "active": active,
            "unread": unread_count(db, hc.hotel.id), "subscription": sub, "CATEGORY_LABELS": CATEGORY_LABELS, **extra}


def _categories(hotel: Hotel) -> list[str]:
    seen = []
    for r in sorted(hotel.room_types, key=lambda r: r.id):
        if r.category and r.category not in seen:
            seen.append(r.category)
    return seen


# --------------------------------------------------------------------------- panel
@router.get("")
def dashboard(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    data = analytics.hotel_dashboard(db, hc.hotel)
    notes = list(db.execute(select(Notification).where(Notification.hotel_id == hc.hotel.id)
                            .order_by(Notification.created_at.desc()).limit(4)).scalars())
    up = uptake_stats(db, hc.hotel.id)
    roi = db.execute(select(RoiEstimate).where(RoiEstimate.hotel_id == hc.hotel.id, RoiEstimate.method == "control_group_did")
                     .order_by(RoiEstimate.created_at.desc())).scalars().first()
    comps = list(db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == hc.hotel.id).order_by(CompetitorSet.rank)).scalars())
    radar = analytics.radar_layout(hc.hotel, comps)
    # Bu gece, tüm oda kategorileri (resort gelir yöneticisi için): kategori başına ilk oda tipinin önerisi
    tonight, seen = [], set()
    for r in analytics.suggestion_rows(db, hc.hotel, date.today(), date.today()):
        if r["room_type"].category not in seen:
            seen.add(r["room_type"].category)
            tonight.append(r)
    today = date.today()
    occ_days = compset_occupancy(db, hc.hotel.id, [c.competitor_hotel_id for c in comps], today, today + timedelta(days=29))
    occ = {
        "tonight": occ_days.get(today) or {},
        "labels": [d.isoformat() for d in occ_days],
        "own": [round(v["own"] * 100) if v["own"] is not None else None for v in occ_days.values()],
        "comp": [round(v["comp"] * 100) if v["comp"] is not None else None for v in occ_days.values()],
        "week_own": _avg([v["own"] for d, v in occ_days.items() if d < today + timedelta(days=7)]),
        "week_comp": _avg([v["comp"] for d, v in occ_days.items() if d < today + timedelta(days=7)]),
    }
    outcome = outcome_summary(db, hc.hotel.id)
    return render(request, "hotel/dashboard.html", **ctx(request, hc, db, "dashboard", data=data, notes=notes,
                                                            uptake=up, roi=roi, comps=comps, radar=radar, tonight=tonight,
                                                            occ=occ, outcome=outcome, status_labels=STATUS_LABELS))


def _avg(vals: list) -> int | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals) * 100) if vals else None


@router.get("/hos-geldiniz")
def welcome(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    comps = list(db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == hc.hotel.id).order_by(CompetitorSet.rank)).scalars())
    hs = ensure_hotel_settings(db, hc.hotel)
    # Adımlar kullanıcının gerçek işaretlerine bağlıdır (rakip onayı/elle ekleme, oda tipi düzeltme, fiyat sınırı)
    steps = {
        "profile": True,
        "competitors": any(c.feedback == "confirmed" or c.is_manual for c in comps),
        "room_types": any(rt.reviewed or rt.mapped_by == "manual" for rt in hc.hotel.room_types),
        "limits": hs.min_price_eur is not None or hs.max_price_eur is not None,
    }
    return render(request, "hotel/welcome.html", **ctx(request, hc, db, "dashboard", comps=comps, steps=steps))


@router.post("/hos-geldiniz", dependencies=[Depends(csrf_protect)])
def welcome_done(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    ensure_hotel_settings(db, hc.hotel).onboarding_done = True
    db.commit()
    return redirect("/panel", request, "Kurulum tamamlandı. İyi satışlar!")


# --------------------------------------------------------------------------- öneriler
@router.get("/oneriler")
def suggestions(request: Request, kategori: str | None = None, gun: int = Query(30, ge=7, le=90),
                sadece: str | None = None, gorunum: str = "liste",
                hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    cats = _categories(hc.hotel)
    cat = kategori if kategori in cats else (cats[0] if cats else None)
    today = date.today()
    rows = analytics.suggestion_rows(db, hc.hotel, today, today + timedelta(days=gun - 1), category=cat)
    if sadece == "onemli":
        rows = [r for r in rows if r["change"] is not None and abs(r["change"]) >= 8]
    # takvim görünümü için aylara böl
    months: dict[tuple[int, int], list] = {}
    for r in rows:
        months.setdefault((r["date"].year, r["date"].month), []).append(r)
    return render(request, "hotel/suggestions.html", **ctx(
        request, hc, db, "suggestions", rows=rows, cats=cats, cat=cat, gun=gun, sadece=sadece, gorunum=gorunum,
        months=months, tolerance=float(hc.hotel.settings.tolerance_pct) if hc.hotel.settings else 5.0,
        status_labels=STATUS_LABELS))


@router.get("/oneriler/{suggestion_id}")
def suggestion_detail(suggestion_id: int, request: Request, hc: HotelContext = Depends(require_hotel),
                      db: Session = Depends(get_db)):
    s = db.get(PriceSuggestion, suggestion_id)
    if s is None or s.room_type.hotel_id != hc.hotel.id:
        raise HTTPException(404)
    comp_ids = [c.competitor_hotel_id for c in db.execute(
        select(CompetitorSet).where(CompetitorSet.hotel_id == hc.hotel.id).order_by(CompetitorSet.rank)).scalars()]
    prices = category_price_by_hotel(db, comp_ids, s.room_type.category or "other", s.stay_date, s.stay_date)
    hotels = {h.id: h for h in db.execute(select(Hotel).where(Hotel.id.in_(comp_ids or [0]))).scalars()}
    comp_prices = []
    for c in comp_ids:
        o = prices.get(c, {}).get(s.stay_date)
        comp_prices.append({"name": hotels[c].name, "price": o.price_eur if o else None,
                            "available": o.available if o else None, "closed": bool(o and o.price_eur is None),
                            "missing": o is None})
    own = latest_observations(db, [s.room_type_id], s.stay_date, s.stay_date).get((s.room_type_id, s.stay_date))
    history = list(db.execute(select(PriceSuggestion).where(
        PriceSuggestion.room_type_id == s.room_type_id, PriceSuggestion.stay_date == s.stay_date)
        .order_by(PriceSuggestion.created_at)).scalars())
    outcome = status_map(db, [s.room_type_id], s.stay_date, s.stay_date).get((s.room_type_id, s.stay_date))
    occ = compset_occupancy(db, hc.hotel.id, comp_ids, s.stay_date, s.stay_date).get(s.stay_date) or {}
    return render(request, "hotel/suggestion_detail.html", **ctx(
        request, hc, db, "suggestions", s=s, r=s.rationale or {}, comp_prices=comp_prices, own=own, history=history,
        steps=waterfall_steps(s), outcome=outcome, status_labels=STATUS_LABELS, occ=occ))


def waterfall_steps(s: PriceSuggestion) -> list[dict]:
    """Rakip medyanından önerilen fiyata adım adım geçiş (şelale grafiği)."""
    r = s.rationale or {}
    median = float(r.get("comp_median") or s.suggested_price)
    anchor = float(r.get("anchor_price") or median)
    adj = r.get("adjustments_pct") or {}
    steps = [{"label": "Rakip medyanı", "start": 0, "end": median, "kind": "base"}]
    cur = median
    if abs(anchor - median) >= 0.5:
        steps.append({"label": "Konumlama endeksi", "start": cur, "end": anchor, "kind": "delta"})
        cur = anchor
    for key, label in (("occupancy", "Doluluk farkı"), ("compression", "Pazar sıkışması"), ("demand", "Talep etkisi"),
                       ("inventory", "Kalan oda hızı"), ("season", "Sezon etkisi")):
        delta = anchor * float(adj.get(key) or 0) / 100
        if abs(delta) >= 0.5:
            steps.append({"label": label, "start": cur, "end": cur + delta, "kind": "delta"})
            cur += delta
    final = float(s.suggested_price)
    if abs(final - cur) >= 0.5:
        label = {"floor": "Taban sınırı", "ceiling": "Tavan sınırı"}.get(r.get("clamped"), "Ölü sezon / yuvarlama")
        steps.append({"label": label, "start": cur, "end": final, "kind": "delta"})
    steps.append({"label": "Önerilen fiyat", "start": 0, "end": final, "kind": "total"})
    top = max(max(st["start"], st["end"]) for st in steps) * 1.08 or 1
    for st in steps:
        lo, hi = sorted((st["start"], st["end"]))
        st["left"], st["width"] = lo / top * 100, max(0.8, (hi - lo) / top * 100)
        st["delta"] = st["end"] - st["start"]
    return steps


@router.post("/oneriler/yenile", dependencies=[Depends(csrf_protect)])
def regenerate(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    today = date.today()
    plan_h = hc.hotel.active_subscription.plan.horizon_days if hc.hotel.active_subscription else 30
    horizon = min(int(get_setting(db, "horizon_days", settings.horizon_days)), plan_h)
    n = len(generate_for_hotel(db, hc.hotel, today, today + timedelta(days=horizon), as_of=today))
    audit(db, request, hc.user, "suggestions_regenerated", "hotel", hc.hotel.id, {"count": n})
    db.commit()
    return redirect("/panel/oneriler", request, f"{n} öneri güncel ayarlarınızla yeniden hesaplandı.")


# --------------------------------------------------------------------------- rakipler
@router.get("/rakipler")
def competitors(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    comps = list(db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == hc.hotel.id).order_by(CompetitorSet.rank)).scalars())
    cands, radius = rank_candidates(db, hc.hotel, limit=25)
    taken = {c.competitor_hotel_id for c in comps}
    candidates = [c for c in cands if c.hotel.id not in taken]
    today = date.today()
    ids = [hc.hotel.id] + list(taken)
    prices = category_price_by_hotel(db, ids, "standard", today, today + timedelta(days=13))
    avg = {hid: (sum(o.price_eur for o in v.values() if o.price_eur) / max(1, sum(1 for o in v.values() if o.price_eur)))
           for hid, v in prices.items()}
    radar = analytics.radar_layout(hc.hotel, comps, avg)
    from app.services.compset import compset_accuracy
    return render(request, "hotel/competitors.html", **ctx(
        request, hc, db, "competitors", comps=comps, candidates=candidates, radius=radius, avg=avg, radar=radar,
        accuracy=compset_accuracy(db, hc.hotel.id), max_comp=hc.hotel.active_subscription.plan.max_competitors
        if hc.hotel.active_subscription else 5))


@router.post("/rakipler/ekle", dependencies=[Depends(csrf_protect)])
def competitor_add(request: Request, competitor_id: int = Form(...), hc: HotelContext = Depends(require_hotel),
                   db: Session = Depends(get_db)):
    comp = db.get(Hotel, competitor_id)
    if comp is None or comp.id == hc.hotel.id or comp.province != hc.hotel.province:
        raise HTTPException(400, "Geçersiz rakip")
    limit = hc.hotel.active_subscription.plan.max_competitors if hc.hotel.active_subscription else 5
    count = db.execute(select(func.count()).select_from(CompetitorSet).where(CompetitorSet.hotel_id == hc.hotel.id)).scalar()
    if count >= limit:
        return redirect("/panel/rakipler", request, f"Paketiniz en fazla {limit} rakibe izin veriyor. Önce bir rakibi çıkarın.", "warning")
    add_manual_competitor(db, hc.hotel, comp)
    audit(db, request, hc.user, "competitor_added", "hotel", comp.id)
    db.commit()
    return redirect("/panel/rakipler", request, f"{comp.name} rakip setinize eklendi.")


@router.post("/rakipler/{competitor_id}/geri-bildirim", dependencies=[Depends(csrf_protect)])
def competitor_feedback(competitor_id: int, request: Request, verdict: str = Form(...),
                        hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    if verdict not in ("confirmed", "rejected"):
        raise HTTPException(400)
    set_feedback(db, hc.hotel.id, competitor_id, verdict)
    audit(db, request, hc.user, f"competitor_{verdict}", "hotel", competitor_id)
    db.commit()
    msg = "Rakip onaylandı." if verdict == "confirmed" else "Rakip setten çıkarıldı ve bir daha önerilmeyecek."
    return redirect("/panel/rakipler", request, msg)


@router.post("/rakipler/{competitor_id}/cikar", dependencies=[Depends(csrf_protect)])
def competitor_remove(competitor_id: int, request: Request, hc: HotelContext = Depends(require_hotel),
                      db: Session = Depends(get_db)):
    remove_competitor(db, hc.hotel, competitor_id)
    audit(db, request, hc.user, "competitor_removed", "hotel", competitor_id)
    db.commit()
    return redirect("/panel/rakipler", request, "Rakip setten çıkarıldı.")


@router.post("/rakipler/yeniden-hesapla", dependencies=[Depends(csrf_protect)])
def competitor_rebuild(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    limit = hc.hotel.active_subscription.plan.max_competitors if hc.hotel.active_subscription else 5
    build_compset(db, hc.hotel, size=min(limit, settings.compset_size))
    db.commit()
    return redirect("/panel/rakipler", request, "Rakip seti yeniden hesaplandı. Elle eklediğiniz rakipler korundu.")


# --------------------------------------------------------------------------- pazar
@router.get("/pazar")
def market(request: Request, kategori: str | None = None, gun: int = Query(14, ge=7, le=60), veri: str = "fiyat",
           hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    cats = _categories(hc.hotel)
    cat = kategori if kategori in cats else (cats[0] if cats else "standard")
    today = date.today()
    grid = analytics.market_grid(db, hc.hotel, cat, today, today + timedelta(days=gun - 1))
    return render(request, "hotel/market.html", **ctx(request, hc, db, "market", grid=grid, cats=cats, cat=cat,
                                                         gun=gun, veri=veri))


# --------------------------------------------------------------------------- talep
@router.get("/talep")
def demand(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    today = date.today()
    start, end = today - timedelta(days=30), today + timedelta(days=60)
    dm = demand_map(db, hc.hotel.province, start, end)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    events = list(db.execute(select(Event).where(Event.province == hc.hotel.province, Event.end_date >= today,
                                                  Event.start_date <= today + timedelta(days=120))
                             .order_by(Event.start_date)).scalars())
    season = monthly_coefficients(db, hc.hotel.province, hc.hotel.district)
    upcoming = [(d, dm[d]) for d in days if d >= today and d in dm]
    peaks = sorted(upcoming, key=lambda x: float(x[1].demand_score), reverse=True)[:6]
    return render(request, "hotel/demand.html", **ctx(
        request, hc, db, "demand", days=days, dm=dm, events=events, holidays=holidays_between(today, today + timedelta(days=180)),
        season=season, months=MONTHS_TR, peaks=sorted(peaks, key=lambda x: x[0]), today_=today,
        timedelta_7=timedelta(days=7)))


# --------------------------------------------------------------------------- oda tipleri
@router.get("/oda-tipleri")
def room_types(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    rts = sorted(hc.hotel.room_types, key=lambda r: r.id)
    return render(request, "hotel/room_types.html", **ctx(request, hc, db, "room_types", rts=rts))


@router.post("/oda-tipleri/{rt_id}", dependencies=[Depends(csrf_protect)])
def room_type_update(rt_id: int, request: Request, category: str = Form(...), hc: HotelContext = Depends(require_hotel),
                     db: Session = Depends(get_db)):
    rt = db.get(RoomType, rt_id)
    if rt is None or rt.hotel_id != hc.hotel.id:
        raise HTTPException(404)
    if category not in CATEGORY_LABELS:
        raise HTTPException(400)
    old = rt.category
    rt.category, rt.mapped_by, rt.confidence, rt.reviewed = category, "manual", 1, True
    audit(db, request, hc.user, "room_type_mapped", "room_type", rt.id, {"from": old, "to": category})
    db.commit()
    return redirect("/panel/oda-tipleri", request, f"“{rt.raw_name}” {CATEGORY_LABELS[category]} olarak eşlendi.")


# --------------------------------------------------------------------------- performans
@router.get("/performans")
def performance(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    up = uptake_stats(db, hc.hotel.id, days=90)
    rt_ids = [r.id for r in hc.hotel.room_types]
    recent = db.execute(select(AppliedObservation, RoomType.raw_name).join(RoomType, RoomType.id == AppliedObservation.room_type_id)
                        .where(AppliedObservation.room_type_id.in_(rt_ids or [0]))
                        .order_by(AppliedObservation.observed_at.desc()).limit(25)).all()
    sugg_prices = {s.id: float(s.suggested_price) for s in db.execute(select(PriceSuggestion).where(
        PriceSuggestion.id.in_([a.suggestion_id for a, _ in recent if a.suggestion_id] or [0]))).scalars()}
    roi = db.execute(select(RoiEstimate).where(RoiEstimate.hotel_id == hc.hotel.id, RoiEstimate.method == "control_group_did")
                     .order_by(RoiEstimate.created_at.desc())).scalars().first()
    outcome = outcome_summary(db, hc.hotel.id)
    return render(request, "hotel/performance.html", **ctx(
        request, hc, db, "performance", uptake=up, recent=recent, sugg_prices=sugg_prices, roi=roi, outcome=outcome,
        tolerance=float(hc.hotel.settings.tolerance_pct) if hc.hotel.settings else 5.0))


@router.get("/backtest")
def backtest(request: Request, gun: int = Query(45, ge=14, le=90), oncul: int = Query(7, ge=1, le=30),
             kategori: str = "standard", hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    cats = _categories(hc.hotel)
    cat = kategori if kategori in cats else (cats[0] if cats else "standard")
    result = run_backtest(db, hc.hotel, days=gun, lead=oncul, category=cat)
    return render(request, "hotel/backtest.html", **ctx(request, hc, db, "backtest", result=result, gun=gun, oncul=oncul,
                                                           cats=cats, cat=cat))


# --------------------------------------------------------------------------- raporlar
@router.get("/raporlar")
def reports(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    return render(request, "hotel/reports.html", **ctx(request, hc, db, "reports"))


def _csv(filename: str, header: list[str], rows: list[list]) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")  # Excel'de Türkçe karakterler için BOM
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/raporlar/oneriler.csv")
def report_suggestions(gun: int = Query(60, ge=1, le=90), hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    today = date.today()
    rows = analytics.suggestion_rows(db, hc.hotel, today, today + timedelta(days=gun - 1))
    return _csv("oneriler.csv", ["tarih", "oda_tipi", "kategori", "mevcut_fiyat_eur", "rakip_medyan_eur", "oneri_eur",
                                 "taban_eur", "tavan_eur", "degisim_yuzde", "talep_skoru", "gerekce"],
                [[r["date"].isoformat(), r["room_type"].raw_name, r["room_type"].category, r["own"], r["median"],
                  r["suggested"], r["floor"], r["ceiling"], r["change"], r["demand"], r["text"]] for r in rows])


@router.get("/raporlar/pazar.csv")
def report_market(kategori: str = "standard", gun: int = Query(30, ge=1, le=60), hc: HotelContext = Depends(require_hotel),
                  db: Session = Depends(get_db)):
    today = date.today()
    grid = analytics.market_grid(db, hc.hotel, kategori, today, today + timedelta(days=gun - 1))
    header = ["otel"] + [d.isoformat() for d in grid["dates"]]
    rows = [[r["hotel"].name if r["hotel"] else "?"] + [c["price"] if c["price"] else ("KAPALI" if c["closed"] else "")
                                                         for c in r["cells"]] for r in grid["rows"]]
    return _csv(f"pazar_{kategori}.csv", header, rows)


@router.get("/raporlar/uyum.csv")
def report_uptake(hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    rt_ids = [r.id for r in hc.hotel.room_types]
    rows = db.execute(select(AppliedObservation, RoomType.raw_name).join(RoomType, RoomType.id == AppliedObservation.room_type_id)
                      .where(AppliedObservation.room_type_id.in_(rt_ids or [0])).order_by(AppliedObservation.observed_at)).all()
    return _csv("uyum.csv", ["gozlem_zamani", "oda_tipi", "konaklama", "gozlenen_fiyat_eur", "oneri_id", "tolerans_icinde"],
                [[a.observed_at.isoformat(), n, a.stay_date.isoformat(), a.observed_price, a.suggestion_id,
                  "evet" if a.within_tolerance else "hayır"] for a, n in rows])


# --------------------------------------------------------------------------- bildirimler
@router.get("/bildirimler")
def notifications(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    notes = list(db.execute(select(Notification).where(Notification.hotel_id == hc.hotel.id)
                            .order_by(Notification.created_at.desc()).limit(100)).scalars())
    return render(request, "hotel/notifications.html", **ctx(request, hc, db, "notifications", notes=notes))


@router.post("/bildirimler/okundu", dependencies=[Depends(csrf_protect)])
def notifications_read(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.hotel_id == hc.hotel.id).values(is_read=True))
    db.commit()
    return redirect("/panel/bildirimler", request, "Tüm bildirimler okundu olarak işaretlendi.")


# --------------------------------------------------------------------------- ayarlar
@router.get("/ayarlar")
def settings_page(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    hs = ensure_hotel_settings(db, hc.hotel)
    db.commit()
    return render(request, "hotel/settings.html", **ctx(request, hc, db, "settings", hs=hs, strategies=STRATEGY_LABEL,
                                                           errors=[]))


def _opt_float(v: str) -> float | None:
    v = (v or "").strip().replace(",", ".")
    return float(v) if v else None


@router.post("/ayarlar", dependencies=[Depends(csrf_protect)])
def settings_save(request: Request, strategy: str = Form("balanced"), tolerance_pct: str = Form("5"),
                  min_price_eur: str = Form(""), max_price_eur: str = Form(""), floor_below_p25_pct: str = Form("10"),
                  ceiling_margin_pct: str = Form("5"), room_count: str = Form(""), star_rating: str = Form(""),
                  notify_email: str = Form(""), hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    hs = ensure_hotel_settings(db, hc.hotel)
    fe: dict[str, str] = {}  # alan → Türkçe hata

    def num(name: str, raw: str) -> float | None:
        try:
            return _opt_float(raw)
        except ValueError:
            fe[name] = "Sayı girin (örn. 120)."
            return None

    tol, mn, mx = num("tolerance_pct", tolerance_pct), num("min_price_eur", min_price_eur), num("max_price_eur", max_price_eur)
    fl, cm = num("floor_below_p25_pct", floor_below_p25_pct), num("ceiling_margin_pct", ceiling_margin_pct)
    if strategy not in STRATEGY_LABEL:
        fe["strategy"] = "Listeden bir strateji seçin."
    if "tolerance_pct" not in fe and (tol is None or not 1 <= tol <= 25):
        fe["tolerance_pct"] = "Uyum toleransı %1 ile %25 arasında olmalı."
    for name, v in (("min_price_eur", mn), ("max_price_eur", mx)):
        if name not in fe and v is not None and v <= 0:
            fe[name] = "Fiyat sınırı sıfırdan büyük olmalı."
    if "min_price_eur" not in fe and "max_price_eur" not in fe and mn is not None and mx is not None and mn >= mx:
        fe["min_price_eur"] = "Minimum fiyat, maksimum fiyattan küçük olmalı."
        fe["max_price_eur"] = "Maksimum fiyat, minimum fiyattan büyük olmalı."
    for name, v in (("floor_below_p25_pct", fl), ("ceiling_margin_pct", cm)):
        if name not in fe and (v is None or not 0 <= v <= 50):
            fe[name] = "0 ile 50 arasında bir yüzde girin."
    errors = list(dict.fromkeys(fe.values()))
    rc = int(room_count) if room_count.strip().isdigit() else None
    sr = int(star_rating) if star_rating.strip().isdigit() and 1 <= int(star_rating) <= 5 else None
    if errors:
        form = {"strategy": strategy, "tolerance_pct": tolerance_pct, "min_price_eur": min_price_eur, "max_price_eur": max_price_eur,
                "floor_below_p25_pct": floor_below_p25_pct, "ceiling_margin_pct": ceiling_margin_pct,
                "room_count": room_count, "star_rating": star_rating, "notify_email": bool(notify_email)}
        return render(request, "hotel/settings.html", status_code=422,
                      **ctx(request, hc, db, "settings", hs=hs, strategies=STRATEGY_LABEL, errors=errors, fe=fe, form=form))
    hs.strategy, hs.tolerance_pct, hs.min_price_eur, hs.max_price_eur = strategy, tol, mn, mx
    hs.floor_below_p25_pct, hs.ceiling_margin_pct, hs.notify_email = fl, cm, bool(notify_email)
    if rc:
        hc.hotel.room_count = rc
    if sr:
        hc.hotel.star_rating = sr
    audit(db, request, hc.user, "settings_updated", "hotel", hc.hotel.id)
    db.commit()
    return redirect("/panel/ayarlar", request, "Ayarlar kaydedildi. Yeni öneriler bir sonraki hesaplamada bu kuralları kullanır.")


# --------------------------------------------------------------------------- abonelik
@router.get("/abonelik")
def subscription(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    subs = list(db.execute(select(Subscription).where(Subscription.hotel_id == hc.hotel.id)
                           .order_by(Subscription.started_at.desc())).scalars())
    plans = list(db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)).scalars())
    invoices = [i for s in subs for i in s.invoices]
    invoices.sort(key=lambda i: i.issued_at, reverse=True)
    comp_count = db.execute(select(func.count()).select_from(CompetitorSet).where(CompetitorSet.hotel_id == hc.hotel.id)).scalar()
    return render(request, "hotel/subscription.html", **ctx(request, hc, db, "subscription", subs=subs, plans=plans,
                                                               invoices=invoices, comp_count=comp_count))


@router.post("/abonelik/paket", dependencies=[Depends(csrf_protect)])
def change_plan(request: Request, plan_id: int = Form(...), hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    sub = hc.hotel.active_subscription
    plan = db.get(Plan, plan_id)
    if sub is None or plan is None or not plan.is_active:
        raise HTTPException(400)
    old = sub.plan.name
    sub.plan_id = plan.id
    audit(db, request, hc.user, "plan_changed", "subscription", sub.id, {"from": old, "to": plan.name})
    db.commit()
    return redirect("/panel/abonelik", request, f"Paketiniz {plan.name} olarak güncellendi.")


@router.post("/abonelik/iptal", dependencies=[Depends(csrf_protect)])
def cancel(request: Request, confirm: str = Form(""), hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    sub = hc.hotel.active_subscription
    if sub is None:
        raise HTTPException(400)
    if confirm != "IPTAL":
        return redirect("/panel/abonelik", request, "İptal için onay kutusuna IPTAL yazın.", "warning")
    sub.status, sub.canceled_at = "canceled", date.today()
    hc.hotel.is_subscriber = False
    audit(db, request, hc.user, "subscription_canceled", "subscription", sub.id)
    db.commit()
    return redirect("/panel/abonelik", request, "Aboneliğiniz iptal edildi. Verileriniz 30 gün saklanır.", "info")


# --------------------------------------------------------------------------- hesap
@router.get("/hesap")
def account(request: Request, hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    return render(request, "hotel/account.html", **ctx(request, hc, db, "account", errors=[]))


@router.post("/hesap", dependencies=[Depends(csrf_protect)])
def account_save(request: Request, full_name: str = Form(...), current_password: str = Form(""), new_password: str = Form(""),
                 hc: HotelContext = Depends(require_hotel), db: Session = Depends(get_db)):
    if hc.impersonating:
        return redirect("/panel/hesap", request, "Yönetici görünümünde hesap bilgileri değiştirilemez.", "warning")
    fe: dict[str, str] = {}
    if len(full_name.strip()) < 3:
        fe["full_name"] = "Ad soyad en az 3 karakter olmalı."
    if new_password:
        if not verify_password(current_password, hc.user.password_hash):
            fe["current_password"] = "Mevcut parola hatalı."
        problems = password_problems(new_password)
        if problems:
            fe["new_password"] = " ".join(problems)
    errors = list(fe.values())
    if errors:
        return render(request, "hotel/account.html", status_code=422,
                      **ctx(request, hc, db, "account", errors=errors, fe=fe, form={"full_name": full_name}))
    hc.user.full_name = full_name.strip()
    if new_password:
        hc.user.password_hash = hash_password(new_password)
        audit(db, request, hc.user, "password_changed", "user", hc.user.id)
    db.commit()
    return redirect("/panel/hesap", request, "Hesap bilgileriniz güncellendi.")
