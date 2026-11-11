"""Yönetim paneli."""
from __future__ import annotations

import secrets
import statistics
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.models import (
    CATEGORY_LABELS,
    AppSetting,
    AuditLog,
    CompetitorSet,
    ComplianceItem,
    DemandSignal,
    Event,
    Hotel,
    Invoice,
    JobRun,
    Plan,
    PriceSuggestion,
    ProviderCost,
    RateSnapshot,
    RoiEstimate,
    RoomType,
    Subscription,
    User,
    utcnow,
)
from app.security import hash_password, password_problems
from app.services import analytics
from app.services.backtest import run_backtest
from app.services.compset import compset_accuracy
from app.services.costs import EconomicsInput, ensure_provider_costs, measured_usage, unit_economics
from app.services.demand import demand_map
from app.services.market import category_price_by_hotel, subscriber_hotels
from app.services.pipeline import JOBS, get_setting, run_job, set_setting
from app.services.pricing import DEFAULT_WEIGHTS, MODEL_VERSION, load_weights
from app.services.roi import estimate_did
from app.services.room_mapping import REVIEW_THRESHOLD
from app.services.uptake import uptake_stats
from app.web import audit, csrf_protect, paginate, redirect, render, require_admin

router = APIRouter(prefix="/admin")


def actx(user: User, active: str, **extra) -> dict:
    return {"user": user, "active": active, "admin": True, **extra}


# --------------------------------------------------------------------------- özet
@router.get("")
def dashboard(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ov = analytics.admin_overview(db)
    subs = []
    for h in subscriber_hotels(db):
        up = uptake_stats(db, h.id, days=30)
        bt = db.get(AppSetting, f"backtest:{h.id}")
        subs.append({"hotel": h, "uptake": up["rate"], "backtest": (bt.value or {}).get("summary") if bt else None})
    return render(request, "admin/dashboard.html", **actx(user, "dashboard", ov=ov, subs=subs,
                                                            accuracy=compset_accuracy(db)))


# --------------------------------------------------------------------------- oteller
@router.get("/oteller")
def hotels(request: Request, q: str = "", il: str = "", abone: str = "", sayfa: int = Query(1, ge=1),
           user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(Hotel)
    if q:
        query = query.where(or_(Hotel.name.ilike(f"%{q}%"), Hotel.district.ilike(f"%{q}%")))
    if il:
        query = query.where(Hotel.province == il)
    if abone == "evet":
        query = query.where(Hotel.is_subscriber.is_(True))
    elif abone == "hayir":
        query = query.where(Hotel.is_subscriber.is_(False))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar()
    pg = paginate(total, sayfa, 25)
    rows = list(db.execute(query.order_by(Hotel.is_subscriber.desc(), Hotel.province, Hotel.name)
                           .offset(pg["offset"]).limit(pg["per_page"])).scalars())
    rt_counts = dict(db.execute(select(RoomType.hotel_id, func.count()).group_by(RoomType.hotel_id)).all())
    return render(request, "admin/hotels.html", **actx(user, "hotels", rows=rows, pg=pg, q=q, il=il, abone=abone,
                                                         rt_counts=rt_counts, provinces=settings.pilot_provinces))


@router.get("/oteller/{hotel_id}")
def hotel_detail(hotel_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(Hotel, hotel_id)
    if h is None:
        raise HTTPException(404)
    today = date.today()
    start = today - timedelta(days=60)
    end = today + timedelta(days=60)
    series = {}
    for cat in ("standard", "deluxe"):
        p = category_price_by_hotel(db, [h.id], cat, start, end).get(h.id, {})
        if p:
            series[cat] = [(d.isoformat(), o.price_eur) for d, o in sorted(p.items())]
    comps = list(db.execute(select(CompetitorSet).where(CompetitorSet.hotel_id == h.id).order_by(CompetitorSet.rank)).scalars())
    users = list(db.execute(select(User).where(User.hotel_id == h.id)).scalars())
    snap_count = db.execute(select(func.count(RateSnapshot.id)).join(RoomType, RoomType.id == RateSnapshot.room_type_id)
                            .where(RoomType.hotel_id == h.id)).scalar()
    sugg_count = db.execute(select(func.count(PriceSuggestion.id)).join(RoomType, RoomType.id == PriceSuggestion.room_type_id)
                            .where(RoomType.hotel_id == h.id)).scalar()
    roi = list(db.execute(select(RoiEstimate).where(RoiEstimate.hotel_id == h.id).order_by(RoiEstimate.created_at.desc()).limit(5)).scalars())
    return render(request, "admin/hotel_detail.html", **actx(
        user, "hotels", h=h, series=series, comps=comps, users=users, snap_count=snap_count, sugg_count=sugg_count,
        roi=roi, CATEGORY_LABELS=CATEGORY_LABELS))


@router.post("/oteller/{hotel_id}", dependencies=[Depends(csrf_protect)])
def hotel_update(hotel_id: int, request: Request, star_rating: str = Form(""), room_count: str = Form(""),
                 hotel_type: str = Form(""), district: str = Form(""), is_active: str = Form(""),
                 user: User = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(Hotel, hotel_id)
    if h is None:
        raise HTTPException(404)
    if star_rating.isdigit() and 1 <= int(star_rating) <= 5:
        h.star_rating = int(star_rating)
    if room_count.isdigit():
        h.room_count = int(room_count)
    if hotel_type in ("pension", "boutique", "midscale", "resort", "chain"):
        h.hotel_type = hotel_type
    h.district = district.strip() or h.district
    h.is_active = bool(is_active)
    audit(db, request, user, "hotel_updated", "hotel", h.id)
    db.commit()
    return redirect(f"/admin/oteller/{h.id}", request, "Otel bilgileri güncellendi.")


@router.post("/oteller/{hotel_id}/panel", dependencies=[Depends(csrf_protect)])
def impersonate(hotel_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(Hotel, hotel_id)
    if h is None:
        raise HTTPException(404)
    request.session["view_hotel_id"] = h.id
    audit(db, request, user, "impersonate_hotel", "hotel", h.id)
    db.commit()
    return redirect("/panel", request, f"{h.name} paneline yönetici olarak bakıyorsunuz.", "info")


@router.post("/panel-cik", dependencies=[Depends(csrf_protect)])
def stop_impersonate(request: Request, user: User = Depends(require_admin)):
    hid = request.session.pop("view_hotel_id", None)
    return redirect(f"/admin/oteller/{hid}" if hid else "/admin")


# --------------------------------------------------------------------------- abonelikler
@router.get("/aboneler")
def subscriptions(request: Request, durum: str = "", user: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(Subscription).order_by(Subscription.started_at.desc())
    if durum:
        q = q.where(Subscription.status == durum)
    subs = list(db.execute(q).scalars())
    plans = list(db.execute(select(Plan).order_by(Plan.sort_order)).scalars())
    return render(request, "admin/subscriptions.html", **actx(user, "subscriptions", subs=subs, plans=plans, durum=durum))


@router.post("/aboneler/{sub_id}", dependencies=[Depends(csrf_protect)])
def subscription_update(sub_id: int, request: Request, status: str = Form(...), plan_id: int = Form(...),
                        user: User = Depends(require_admin), db: Session = Depends(get_db)):
    sub = db.get(Subscription, sub_id)
    if sub is None or status not in ("trial", "active", "past_due", "canceled") or db.get(Plan, plan_id) is None:
        raise HTTPException(400)
    sub.status, sub.plan_id = status, plan_id
    if status == "canceled":
        sub.canceled_at = sub.canceled_at or date.today()
        sub.hotel.is_subscriber = False
    else:
        sub.canceled_at = None
        sub.hotel.is_subscriber = True
    audit(db, request, user, "subscription_updated", "subscription", sub.id, {"status": status, "plan_id": plan_id})
    db.commit()
    return redirect("/admin/aboneler", request, "Abonelik güncellendi.")


# --------------------------------------------------------------------------- paketler
@router.get("/paketler")
def plans(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = list(db.execute(select(Plan).order_by(Plan.sort_order)).scalars())
    counts = dict(db.execute(select(Subscription.plan_id, func.count()).where(Subscription.status != "canceled")
                             .group_by(Subscription.plan_id)).all())
    return render(request, "admin/plans.html", **actx(user, "plans", rows=rows, counts=counts))


def _plan_from_form(p: Plan, name, target, price, max_competitors, max_room_types, horizon_days, features, is_active, sort_order):
    p.name, p.target = name.strip(), target.strip()
    p.monthly_price_eur = float(price.replace(",", "."))
    p.max_competitors, p.max_room_types, p.horizon_days = int(max_competitors), int(max_room_types), int(horizon_days)
    p.features = [f.strip() for f in features.splitlines() if f.strip()]
    p.is_active, p.sort_order = bool(is_active), int(sort_order or 0)


@router.post("/paketler", dependencies=[Depends(csrf_protect)])
def plan_create(request: Request, code: str = Form(...), name: str = Form(...), target: str = Form(""), price: str = Form(...),
                max_competitors: str = Form("5"), max_room_types: str = Form("4"), horizon_days: str = Form("60"),
                features: str = Form(""), is_active: str = Form("1"), sort_order: str = Form("9"),
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    code = code.strip().lower()
    if not code.isidentifier() or db.execute(select(Plan).where(Plan.code == code)).scalar_one_or_none():
        return redirect("/admin/paketler", request, "Paket kodu benzersiz ve boşluksuz olmalı.", "error")
    p = Plan(code=code)
    try:
        _plan_from_form(p, name, target, price, max_competitors, max_room_types, horizon_days, features, is_active, sort_order)
    except ValueError:
        return redirect("/admin/paketler", request, "Sayısal alanlarda geçersiz değer var.", "error")
    db.add(p)
    audit(db, request, user, "plan_created", "plan", code)
    db.commit()
    return redirect("/admin/paketler", request, f"{p.name} paketi oluşturuldu.")


@router.post("/paketler/{plan_id}", dependencies=[Depends(csrf_protect)])
def plan_update(plan_id: int, request: Request, name: str = Form(...), target: str = Form(""), price: str = Form(...),
                max_competitors: str = Form("5"), max_room_types: str = Form("4"), horizon_days: str = Form("60"),
                features: str = Form(""), is_active: str = Form(""), sort_order: str = Form("0"),
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(Plan, plan_id)
    if p is None:
        raise HTTPException(404)
    try:
        _plan_from_form(p, name, target, price, max_competitors, max_room_types, horizon_days, features, is_active, sort_order)
    except ValueError:
        return redirect("/admin/paketler", request, "Sayısal alanlarda geçersiz değer var.", "error")
    audit(db, request, user, "plan_updated", "plan", p.id)
    db.commit()
    return redirect("/admin/paketler", request, f"{p.name} paketi güncellendi.")


# --------------------------------------------------------------------------- faturalar
@router.get("/faturalar")
def invoices(request: Request, durum: str = "", user: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(Invoice).order_by(Invoice.issued_at.desc())
    if durum:
        q = q.where(Invoice.status == durum)
    rows = list(db.execute(q.limit(300)).scalars())
    totals = dict(db.execute(select(Invoice.status, func.sum(Invoice.amount_eur)).group_by(Invoice.status)).all())
    return render(request, "admin/invoices.html", **actx(user, "invoices", rows=rows, durum=durum,
                                                           totals={k: float(v or 0) for k, v in totals.items()}))


@router.post("/faturalar/{invoice_id}", dependencies=[Depends(csrf_protect)])
def invoice_update(invoice_id: int, request: Request, status: str = Form(...), user: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if inv is None or status not in ("paid", "open", "failed", "void"):
        raise HTTPException(400)
    inv.status = status
    audit(db, request, user, "invoice_status", "invoice", inv.id, {"status": status})
    db.commit()
    return redirect("/admin/faturalar", request, f"{inv.number} durumu güncellendi.")


# --------------------------------------------------------------------------- kullanıcılar
@router.get("/kullanicilar")
def users(request: Request, q: str = "", user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(User).order_by(User.role, User.email)
    if q:
        query = query.where(or_(User.email.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%")))
    rows = list(db.execute(query).scalars())
    hotels_free = list(db.execute(select(Hotel).where(Hotel.is_subscriber.is_(True)).order_by(Hotel.name)).scalars())
    return render(request, "admin/users.html", **actx(user, "users", rows=rows, q=q, hotels=hotels_free,
                                                        temp_password=request.session.pop("temp_password", None)))


@router.post("/kullanicilar", dependencies=[Depends(csrf_protect)])
def user_create(request: Request, email: str = Form(...), full_name: str = Form(...), role: str = Form("hotel"),
                hotel_id: str = Form(""), password: str = Form(...), user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    email = email.lower().strip()
    probs = password_problems(password)
    if role not in ("admin", "hotel"):
        probs.append("Geçersiz rol.")
    if role == "hotel" and not hotel_id.isdigit():
        probs.append("Otel kullanıcısı için otel seçin.")
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        probs.append("Bu e-posta zaten kayıtlı.")
    if probs:
        return redirect("/admin/kullanicilar", request, " ".join(probs), "error")
    u = User(email=email, full_name=full_name.strip(), role=role, password_hash=hash_password(password),
             hotel_id=int(hotel_id) if role == "hotel" else None)
    db.add(u)
    audit(db, request, user, "user_created", "user", email, {"role": role})
    db.commit()
    return redirect("/admin/kullanicilar", request, f"{email} oluşturuldu.")


@router.post("/kullanicilar/{user_id}/durum", dependencies=[Depends(csrf_protect)])
def user_toggle(user_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404)
    if u.id == user.id:
        return redirect("/admin/kullanicilar", request, "Kendi hesabınızı devre dışı bırakamazsınız.", "warning")
    u.is_active = not u.is_active
    audit(db, request, user, "user_toggled", "user", u.id, {"active": u.is_active})
    db.commit()
    return redirect("/admin/kullanicilar", request, f"{u.email} {'etkinleştirildi' if u.is_active else 'devre dışı bırakıldı'}.")


@router.post("/kullanicilar/{user_id}/parola", dependencies=[Depends(csrf_protect)])
def user_reset_password(user_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404)
    temp = "Gc" + secrets.token_urlsafe(8) + "7"
    u.password_hash = hash_password(temp)
    audit(db, request, user, "password_reset_by_admin", "user", u.id)
    db.commit()
    request.session["temp_password"] = {"email": u.email, "password": temp}
    return redirect("/admin/kullanicilar", request, f"{u.email} için geçici parola oluşturuldu.")


# --------------------------------------------------------------------------- veri hattı
def _run_in_background(name: str) -> None:
    with SessionLocal() as db:
        run_job(db, name, trigger="manual")


@router.get("/veri-hatti")
def pipeline(request: Request, is_: str = Query("", alias="is"), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(JobRun).order_by(JobRun.started_at.desc())
    if is_:
        q = q.where(JobRun.job_name == is_)
    runs = list(db.execute(q.limit(60)).scalars())
    last = {}
    for name in JOBS:
        last[name] = db.execute(select(JobRun).where(JobRun.job_name == name).order_by(JobRun.started_at.desc())).scalars().first()
    durations = [((r.finished_at - r.started_at).total_seconds(), r) for r in runs if r.finished_at]
    from app.scheduler import SCHEDULE_LABELS
    return render(request, "admin/pipeline.html", **actx(user, "pipeline", runs=runs, jobs=JOBS, last=last, filt=is_,
                                                           durations=durations, schedule=SCHEDULE_LABELS,
                                                           scheduler_on=settings.scheduler_enabled))


@router.post("/veri-hatti/calistir", dependencies=[Depends(csrf_protect)])
def pipeline_run(request: Request, background: BackgroundTasks, job: str = Form(...), user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    if job not in JOBS:
        raise HTTPException(400)
    running = db.execute(select(JobRun).where(JobRun.job_name == job, JobRun.status == "running",
                                              JobRun.started_at >= utcnow() - timedelta(hours=2))).scalars().first()
    if running:
        return redirect("/admin/veri-hatti", request, "Bu iş zaten çalışıyor.", "warning")
    audit(db, request, user, "job_triggered", "job", job)
    db.commit()
    background.add_task(_run_in_background, job)
    return redirect("/admin/veri-hatti", request, f"“{JOBS[job][0]}” başlatıldı. Sonuç birkaç saniye içinde listede görünür.", "info")


# --------------------------------------------------------------------------- API & maliyet
@router.get("/api-maliyet")
def costs(request: Request, abone: int = Query(10, ge=1, le=5000), rakip: int = Query(5, ge=1, le=20),
          ufuk: int = Query(60, ge=7, le=365), tarama: int = Query(1, ge=1, le=24), tarih_basina: int = Query(1, ge=1, le=60),
          ortak: float = Query(30, ge=0, le=90), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ensure_provider_costs(db)
    inp = EconomicsInput(subscribers=abone, compset_size=rakip, horizon_days=ufuk, scans_per_day=tarama,
                         dates_per_request=tarih_basina, overlap_pct=ortak)
    econ = unit_economics(db, inp)
    usage = measured_usage(db)
    providers = list(db.execute(select(ProviderCost).order_by(ProviderCost.provider)).scalars())
    db.commit()
    return render(request, "admin/costs.html", **actx(user, "costs", econ=econ, usage=usage, providers=providers, inp=inp,
                                                        keys=settings.configured_keys()))


@router.post("/api-maliyet/{provider}", dependencies=[Depends(csrf_protect)])
def cost_update(provider: str, request: Request, unit_cost_eur: str = Form(...), monthly_fee_eur: str = Form(...),
                included_requests: str = Form("0"), notes: str = Form(""), enabled: str = Form(""),
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    pc = db.get(ProviderCost, provider)
    if pc is None:
        raise HTTPException(404)
    try:
        pc.unit_cost_eur = float(unit_cost_eur.replace(",", "."))
        pc.monthly_fee_eur = float(monthly_fee_eur.replace(",", "."))
        pc.included_requests = int(included_requests or 0)
    except ValueError:
        return redirect("/admin/api-maliyet", request, "Geçersiz sayı.", "error")
    pc.notes, pc.enabled = notes.strip(), bool(enabled)
    audit(db, request, user, "provider_cost_updated", "provider_cost", provider)
    db.commit()
    return redirect("/admin/api-maliyet", request, f"{pc.label} fiyatları güncellendi.")


# --------------------------------------------------------------------------- oda eşleme
@router.get("/oda-eslemeleri")
def mappings(request: Request, filtre: str = "inceleme", sayfa: int = Query(1, ge=1), user: User = Depends(require_admin),
             db: Session = Depends(get_db)):
    q = select(RoomType).join(Hotel, Hotel.id == RoomType.hotel_id)
    if filtre == "inceleme":
        q = q.where(RoomType.confidence < REVIEW_THRESHOLD, RoomType.reviewed.is_(False))
    elif filtre in CATEGORY_LABELS:
        q = q.where(RoomType.category == filtre)
    elif filtre in ("rule", "llm", "manual"):
        q = q.where(RoomType.mapped_by == filtre)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    pg = paginate(total, sayfa, 40)
    rows = list(db.execute(q.order_by(RoomType.confidence, Hotel.name).offset(pg["offset"]).limit(pg["per_page"])).scalars())
    stats = dict(db.execute(select(RoomType.mapped_by, func.count()).group_by(RoomType.mapped_by)).all())
    cats = dict(db.execute(select(RoomType.category, func.count()).group_by(RoomType.category)).all())
    pending = db.execute(select(func.count()).select_from(RoomType).where(
        RoomType.confidence < REVIEW_THRESHOLD, RoomType.reviewed.is_(False))).scalar()
    return render(request, "admin/mappings.html", **actx(user, "mappings", rows=rows, pg=pg, filtre=filtre, stats=stats,
                                                           cats=cats, pending=pending, CATEGORY_LABELS=CATEGORY_LABELS,
                                                           threshold=REVIEW_THRESHOLD))


@router.post("/oda-eslemeleri/toplu-onay", dependencies=[Depends(csrf_protect)])
async def mapping_bulk(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    form = await request.form()
    ids = [int(v) for v in form.getlist("ids") if str(v).isdigit()]
    n = 0
    for rt in db.execute(select(RoomType).where(RoomType.id.in_(ids or [0]))).scalars():
        rt.reviewed = True
        n += 1
    audit(db, request, user, "room_type_bulk_approve", "room_type", None, {"count": n})
    db.commit()
    return redirect("/admin/oda-eslemeleri", request, f"{n} eşleme olduğu gibi onaylandı.")


@router.post("/oda-eslemeleri/{rt_id}", dependencies=[Depends(csrf_protect)])
def mapping_update(rt_id: int, request: Request, category: str = Form(...), filtre: str = Form("inceleme"),
                   user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rt = db.get(RoomType, rt_id)
    if rt is None or category not in CATEGORY_LABELS:
        raise HTTPException(400)
    rt.category, rt.mapped_by, rt.confidence, rt.reviewed = category, "manual", 1, True
    audit(db, request, user, "room_type_mapped", "room_type", rt.id, {"to": category})
    db.commit()
    return redirect(f"/admin/oda-eslemeleri?filtre={filtre}", request, f"“{rt.raw_name}” → {CATEGORY_LABELS[category]}")


# --------------------------------------------------------------------------- model
@router.get("/model")
def model(request: Request, deneme: int = 0, demand: float | None = None, inventory: float | None = None,
          season: float | None = None, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    weights = load_weights(db)
    version = get_setting(db, "model_version", MODEL_VERSION)
    comparison = None
    if deneme:
        proposed = {**weights, **{k: v for k, v in (("demand", demand), ("inventory", inventory), ("season", season)) if v is not None}}
        comparison = []
        for h in subscriber_hotels(db)[:4]:  # yanıt süresini makul tutmak için ilk 4 abone, son 21 gün
            cur = run_backtest(db, h, days=21, weights=weights).get("summary")
            new = run_backtest(db, h, days=21, weights=proposed).get("summary")
            if cur and new:
                comparison.append({"hotel": h, "current": cur, "proposed": new})
        agg = {}
        for k in ("mape_suggestion", "direction_hit_rate", "band_hit_rate"):
            c = [r["current"][k] for r in comparison if r["current"].get(k) is not None]
            n = [r["proposed"][k] for r in comparison if r["proposed"].get(k) is not None]
            agg[k] = (statistics.fmean(c) if c else None, statistics.fmean(n) if n else None)
        comparison = {"rows": comparison, "agg": agg, "proposed": proposed}
    sugg_by_version = db.execute(select(PriceSuggestion.model_version, func.count()).group_by(PriceSuggestion.model_version)).all()
    return render(request, "admin/model.html", **actx(user, "model", weights=weights, defaults=DEFAULT_WEIGHTS, version=version,
                                                        comparison=comparison, by_version=sugg_by_version,
                                                        form={"demand": demand, "inventory": inventory, "season": season}))


@router.post("/model", dependencies=[Depends(csrf_protect)])
def model_save(request: Request, demand: str = Form(...), inventory: str = Form(...), season: str = Form(...),
               max_up: str = Form(...), max_down: str = Form(...), version: str = Form(...),
               user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        w = {k: float(v.replace(",", ".")) for k, v in
             (("demand", demand), ("inventory", inventory), ("season", season), ("max_up", max_up), ("max_down", max_down))}
    except ValueError:
        return redirect("/admin/model", request, "Ağırlıklar sayısal olmalı.", "error")
    if any(v < 0 or v > 1 for v in w.values()):
        return redirect("/admin/model", request, "Ağırlıklar 0 ile 1 arasında olmalı.", "error")
    old = load_weights(db)
    set_setting(db, "pricing_weights", {**old, **w})  # formda olmayan ağırlıklar (doluluk, hız, sıkışma) korunur
    set_setting(db, "model_version", version.strip() or MODEL_VERSION)
    audit(db, request, user, "model_updated", "model", version, {"from": old, "to": w})
    db.commit()
    return redirect("/admin/model", request, "Model ayarları kaydedildi. Sonraki öneri çalıştırmasında kullanılacak.")


# --------------------------------------------------------------------------- etki ölçümü
@router.get("/etki")
def impact(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = []
    for h in subscriber_hotels(db):
        est = db.execute(select(RoiEstimate).where(RoiEstimate.hotel_id == h.id, RoiEstimate.method == "control_group_did")
                         .order_by(RoiEstimate.created_at.desc())).scalars().first()
        rows.append({"hotel": h, "est": est, "uptake": uptake_stats(db, h.id)["rate"]})
    by_prov = dict(db.execute(select(Hotel.province, func.count()).where(Hotel.is_subscriber.is_(False))
                              .group_by(Hotel.province)).all())
    return render(request, "admin/impact.html", **actx(user, "impact", rows=rows, controls=by_prov))


@router.post("/etki/{hotel_id}", dependencies=[Depends(csrf_protect)])
def impact_run(hotel_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(Hotel, hotel_id)
    if h is None or h.active_subscription is None:
        raise HTTPException(400)
    res = estimate_did(db, h, h.active_subscription.started_at)
    db.commit()
    if res.get("status") != "ok":
        return redirect("/admin/etki", request, res.get("message", "Hesaplanamadı."), "warning")
    return redirect("/admin/etki", request, f"{h.name} için DiD tahmini güncellendi (güven: {res['confidence']}).")


# --------------------------------------------------------------------------- talep
@router.get("/talep")
def demand(request: Request, il: str = "Muğla", user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if il not in settings.pilot_provinces:
        il = settings.pilot_provinces[0]
    today = date.today()
    dm = demand_map(db, il, today - timedelta(days=30), today + timedelta(days=90))
    events = list(db.execute(select(Event).where(Event.province == il, Event.end_date >= today - timedelta(days=30))
                             .order_by(Event.start_date)).scalars())
    last = db.execute(select(func.max(DemandSignal.updated_at)).where(DemandSignal.province == il)).scalar()
    return render(request, "admin/demand.html", **actx(user, "demand", dm=dm, events=events, il=il,
                                                         provinces=settings.pilot_provinces, last=last))


@router.post("/talep/etkinlik", dependencies=[Depends(csrf_protect)])
def event_create(request: Request, province: str = Form(...), name: str = Form(...), category: str = Form("festivals"),
                 start_date: date = Form(...), end_date: date = Form(...), impact: int = Form(50), district: str = Form(""),
                 user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if end_date < start_date or not 0 <= impact <= 100 or province not in settings.pilot_provinces:
        return redirect(f"/admin/talep?il={province}", request, "Etkinlik bilgileri geçersiz.", "error")
    db.add(Event(province=province, district=district or None, name=name.strip(), category=category, start_date=start_date,
                 end_date=end_date, impact=impact, source="manual"))
    audit(db, request, user, "event_created", "event", name)
    db.commit()
    return redirect(f"/admin/talep?il={province}", request,
                    "Etkinlik eklendi. Talep skorları bir sonraki 'Talep sinyali yenileme' işinde güncellenir.")


@router.post("/talep/etkinlik/{event_id}/sil", dependencies=[Depends(csrf_protect)])
def event_delete(event_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404)
    prov = ev.province
    db.delete(ev)
    audit(db, request, user, "event_deleted", "event", event_id)
    db.commit()
    return redirect(f"/admin/talep?il={prov}", request, "Etkinlik silindi.")


# --------------------------------------------------------------------------- uyumluluk
@router.get("/uyumluluk")
def compliance(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    items = list(db.execute(select(ComplianceItem).order_by(ComplianceItem.id)).scalars())
    return render(request, "admin/compliance.html", **actx(user, "compliance", items=items))


@router.post("/uyumluluk/{item_id}", dependencies=[Depends(csrf_protect)])
def compliance_update(item_id: int, request: Request, is_done: str = Form(""), evidence_note: str = Form(""),
                      user: User = Depends(require_admin), db: Session = Depends(get_db)):
    it = db.get(ComplianceItem, item_id)
    if it is None:
        raise HTTPException(404)
    if is_done and not evidence_note.strip():
        return redirect("/admin/uyumluluk", request, "Tamamlandı işaretlemek için kanıt/not girmeniz gerekiyor (doküman 9.1).", "warning")
    it.is_done, it.evidence_note, it.updated_at = bool(is_done), evidence_note.strip() or None, utcnow()
    audit(db, request, user, "compliance_updated", "compliance", it.key, {"done": it.is_done})
    db.commit()
    return redirect("/admin/uyumluluk", request, "Kontrol listesi güncellendi.")


# --------------------------------------------------------------------------- denetim
@router.get("/denetim")
def audit_log(request: Request, islem: str = "", sayfa: int = Query(1, ge=1), user: User = Depends(require_admin),
              db: Session = Depends(get_db)):
    q = select(AuditLog)
    if islem:
        q = q.where(AuditLog.action == islem)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    pg = paginate(total, sayfa, 50)
    rows = list(db.execute(q.order_by(AuditLog.created_at.desc()).offset(pg["offset"]).limit(pg["per_page"])).scalars())
    actions = [a for (a,) in db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()]
    return render(request, "admin/audit.html", **actx(user, "audit", rows=rows, pg=pg, islem=islem, actions=actions))


# --------------------------------------------------------------------------- sistem
@router.get("/sistem")
def system(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app import models as m

    counts = {}
    for model_cls in (m.Hotel, m.RoomType, m.RateSnapshot, m.InventoryEvent, m.PriceSuggestion, m.AppliedObservation,
                      m.RoiEstimate, m.DemandSignal, m.Event, m.User, m.Subscription, m.ApiUsage, m.AuditLog):
        counts[model_cls.__tablename__] = db.execute(select(func.count()).select_from(model_cls)).scalar()
    return render(request, "admin/system.html", **actx(
        user, "system", counts=counts, keys=settings.configured_keys(), scan_scope=get_setting(db, "scan_scope", "all"),
        horizon=get_setting(db, "horizon_days", settings.horizon_days),
        db_kind="PostgreSQL" if not settings.is_sqlite else "SQLite"))


@router.post("/sistem", dependencies=[Depends(csrf_protect)])
def system_save(request: Request, scan_scope: str = Form(...), horizon_days: int = Form(...),
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if scan_scope not in ("all", "compset") or not 7 <= horizon_days <= 180:
        return redirect("/admin/sistem", request, "Geçersiz değer.", "error")
    set_setting(db, "scan_scope", scan_scope)
    set_setting(db, "horizon_days", horizon_days)
    audit(db, request, user, "system_settings", "system", None, {"scan_scope": scan_scope, "horizon": horizon_days})
    db.commit()
    return redirect("/admin/sistem", request, "Sistem ayarları kaydedildi.")
