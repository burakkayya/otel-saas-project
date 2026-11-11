"""Demo veri tohumu. Boş bir veritabanını, tüm ekranların dolu görüneceği şekilde
gerçekçi (kurgusal) verilerle doldurur. Gerçek veri modunda yalnızca temel
kayıtlar (paketler, yönetici, uyumluluk listesi) oluşturulur."""
from __future__ import annotations

import logging
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AuditLog,
    ComplianceItem,
    Hotel,
    Invoice,
    JobRun,
    Notification,
    Plan,
    PriceSuggestion,
    RateSnapshot,
    Subscription,
    User,
    utcnow,
)
from app.security import hash_password
from app.services import backtest as backtest_svc
from app.services.compset import build_compset, set_feedback
from app.services.costs import ensure_provider_costs
from app.services.demand import refresh_demand
from app.services.market import _aware
from app.services.outcomes import evaluate_outcomes
from app.services.pipeline import ensure_hotel_settings, ingest_rates, set_setting, upsert_hotel
from app.services.pricing import MODEL_VERSION, generate_for_hotel
from app.services.providers import UsageTracker, get_providers
from app.services.roi import estimate_did
from app.services.seasonality import monthly_coefficients
from app.services.uptake import record_uptake, uptake_stats

log = logging.getLogger(__name__)

PLANS = [
    dict(code="baslangic", name="Başlangıç", target="Butik otel ve pansiyonlar", monthly_price_eur=49, max_competitors=5,
         max_room_types=2, horizon_days=30, sort_order=1,
         features=["5 rakiplik rakip seti", "2 oda kategorisi", "30 günlük öneri ufku", "Günlük panel özeti (e-posta yakında)"]),
    dict(code="profesyonel", name="Profesyonel", target="Orta ölçekli oteller", monthly_price_eur=129, max_competitors=8,
         max_room_types=4, horizon_days=60, sort_order=2,
         features=["8 rakiplik rakip seti", "4 oda kategorisi", "60 günlük öneri ufku", "Talep sinyalleri", "Backtest raporu"]),
    dict(code="resort", name="Resort & Zincir", target="Zincir ve resort oteller", monthly_price_eur=349, max_competitors=12,
         max_room_types=8, horizon_days=90, sort_order=3,
         features=["12 rakiplik rakip seti", "8 oda kategorisi", "90 günlük öneri ufku", "Kontrol grubu ile tahmini etki ölçümü",
                   "Öncelikli destek"]),
]

COMPLIANCE = [
    ("data_source_terms", "Veri kaynağı (Makcorps / Caviar) kullanım koşulları yazılı olarak kaydedildi", "high"),
    ("ota_commercial_use", "Booking.com ve aggregator verilerinin ticari kullanım durumu teyit edildi", "high"),
    ("amadeus_terms", "Amadeus self-service, Flight Search Volume erişimi ve ticari kullanım koşulları teyit edildi", "medium"),
    ("predicthq_terms", "PredictHQ Developer Plan ticari kullanım kapsamı teyit edildi", "medium"),
    ("google_caching", "Google Places ve Distance Matrix önbellekleme ve saklama kısıtları kontrol edildi", "medium"),
    ("kvkk", "Kişisel veri (otel yetkilisi iletişim bilgisi) için KVKK uyumu değerlendirildi", "high"),
    ("contracts", "Abonelik sözleşmesi ve gizlilik politikası hazırlandı (hukukçu onayı)", "high"),
]

SUBSCRIBER_PICKS = [
    # (il, ilçe, tercih edilen tip, paket, abonelik kaç gün önce, uyum eğilimi)
    ("Muğla", "Bodrum", "boutique", "profesyonel", 49, 0.80),
    ("Muğla", "Bodrum", "resort", "resort", 42, 0.65),
    ("Muğla", "Fethiye", "midscale", "profesyonel", 42, 0.55),
    ("Muğla", "Marmaris", "resort", "resort", 35, 0.70),
    ("Muğla", "Datça", "pension", "baslangic", 28, 0.45),
    ("Muğla", "Dalyan", "boutique", "baslangic", 21, 0.60),
    ("Antalya", "Belek", "resort", "resort", 42, 0.75),
    ("Antalya", "Kaş", "boutique", "profesyonel", 28, 0.50),
]


# Önceki sürümün varsayılan paket maddeleri: değiştirilmemişlerse güncel (sınırlarla tutarlı) metne taşınır.
_OLD_DEFAULT_FEATURES = {
    "baslangic": ["5 rakiplik compset", "2 oda kategorisi", "30 günlük öneri ufku", "Günlük e-posta özeti"],
    "profesyonel": ["8 rakiplik compset", "4 oda kategorisi", "60 günlük öneri ufku", "Talep sinyalleri", "Backtest raporu"],
    "resort": ["12 rakiplik compset", "Sınırsız oda kategorisi", "90 günlük öneri ufku", "Kontrol grubu etki ölçümü",
               "Öncelikli destek"],
}


def ensure_base(db: Session) -> None:
    """Her ortamda gerekli temel kayıtlar."""
    for p in PLANS:
        existing = db.execute(select(Plan).where(Plan.code == p["code"])).scalar_one_or_none()
        if existing is None:
            db.add(Plan(**p))
        elif list(existing.features or []) == _OLD_DEFAULT_FEATURES.get(p["code"]):
            existing.features = p["features"]
    if db.execute(select(User).where(User.email == settings.admin_email)).scalar_one_or_none() is None:
        db.add(User(email=settings.admin_email, password_hash=hash_password(settings.admin_password),
                    full_name="Sistem Yöneticisi", role="admin"))
    for key, title, risk in COMPLIANCE:
        if db.execute(select(ComplianceItem).where(ComplianceItem.key == key)).scalar_one_or_none() is None:
            db.add(ComplianceItem(key=key, title=title, risk=risk))
    ensure_provider_costs(db)
    from app.services.pipeline import get_setting
    if get_setting(db, "model_version") is None:
        set_setting(db, "model_version", MODEL_VERSION)
    if get_setting(db, "scan_scope") is None:
        set_setting(db, "scan_scope", "all")
    if get_setting(db, "horizon_days") is None:
        set_setting(db, "horizon_days", settings.horizon_days)
    db.commit()


def _observation_plan(today: date, history_days: int, horizon: int) -> dict[date, list[date]]:
    """Hangi gözlem gününde hangi konaklama tarihlerinin tarandığı."""
    leads = (30, 14, 7, 1)
    plan: dict[date, set[date]] = defaultdict(set)
    first_stay = today - timedelta(days=history_days)
    last_stay = today + timedelta(days=horizon)
    d = first_stay
    while d <= last_stay:
        for lead in leads:
            obs = d - timedelta(days=lead)
            if obs <= today:
                plan[obs].add(d)
        d += timedelta(days=1)
    # Son iki haftada gelecek tarihler haftalık tam tarama (7 günlük trend için)
    for back in (14, 7, 0):
        obs = today - timedelta(days=back)
        for i in range(horizon + 1):
            stay = today + timedelta(days=i)
            if stay >= obs:
                plan[obs].add(stay)
    return {k: sorted(v) for k, v in sorted(plan.items())}


def _pick_subscribers(db: Session, scale: float) -> list[tuple[Hotel, str, int, float]]:
    picks = []
    used: set[int] = set()
    for prov, dist, htype, plan, ago, adoption in SUBSCRIBER_PICKS:
        q = select(Hotel).where(Hotel.province == prov).order_by(Hotel.id)
        cands = list(db.execute(q).scalars())
        cands = [h for h in cands if h.id not in used]
        best = next((h for h in cands if h.district == dist and h.hotel_type == htype), None) \
            or next((h for h in cands if h.district == dist), None) \
            or next((h for h in cands if h.hotel_type == htype), None) \
            or (cands[0] if cands else None)
        if best is None:
            continue
        used.add(best.id)
        picks.append((best, plan, ago, adoption))
        if scale < 0.5 and len(picks) >= 3:
            break
    return picks


def _simulate_adoption(db: Session, hotel: Hotel, start: date, adoption: float, rng: random.Random) -> int:
    """DEMO: abone otelin önerilerin bir kısmını uyguladığını simüle eder."""
    rt_ids = [r.id for r in hotel.room_types]
    sugg: dict[tuple[int, date], list[tuple[datetime, float]]] = defaultdict(list)
    for rt, stay, created, price in db.execute(
        select(PriceSuggestion.room_type_id, PriceSuggestion.stay_date, PriceSuggestion.created_at,
               PriceSuggestion.suggested_price).where(PriceSuggestion.room_type_id.in_(rt_ids))
    ):
        sugg[(rt, stay)].append((_aware(created), float(price)))
    for v in sugg.values():
        v.sort()
    start_dt = datetime.combine(start, time(0), tzinfo=timezone.utc)
    snaps = db.execute(
        select(RateSnapshot.id, RateSnapshot.room_type_id, RateSnapshot.stay_date, RateSnapshot.observed_at,
               RateSnapshot.price_eur, RateSnapshot.price_original)
        .where(RateSnapshot.room_type_id.in_(rt_ids), RateSnapshot.observed_at >= start_dt,
               RateSnapshot.price_eur.is_not(None))
    ).all()
    changed = 0
    for sid, rt, stay, obs, price_eur, price_orig in snaps:
        lst = sugg.get((rt, stay))
        if not lst:
            continue
        obs = _aware(obs)
        prior = [p for c, p in lst if c <= obs - timedelta(hours=1)]
        if not prior or rng.random() > adoption:
            continue
        new_eur = round(prior[-1] * (1 + rng.uniform(-0.02, 0.02)), 2)
        ratio = float(price_orig) / float(price_eur) if price_eur else 1.0
        db.execute(update(RateSnapshot).where(RateSnapshot.id == sid).values(
            price_eur=new_eur, price_original=round(new_eur * ratio, 2)))
        changed += 1
    db.flush()
    return changed


def seed_demo(db: Session, scale: float = 1.0, history_days: int = 120, horizon: int = 60, today: date | None = None,
              verbose: bool = False) -> dict:
    today = today or date.today()
    ensure_base(db)
    if db.execute(select(func.count(Hotel.id))).scalar():
        return {"skipped": True, "reason": "Veritabanında zaten otel var."}
    t0 = utcnow()
    run = JobRun(job_name="seed_demo", status="running", trigger="seed", started_at=t0)
    db.add(run)
    db.commit()
    rng = random.Random(42)
    set_setting(db, "horizon_days", horizon)

    tracker = UsageTracker()
    providers = get_providers(tracker, scale=scale)
    infos = {}
    hotels: list[Hotel] = []
    for prov in settings.pilot_provinces:
        for info in providers.rates.list_hotels(prov):
            infos[info.source_id] = info
            hotels.append(upsert_hotel(db, info, providers))
    tracker.flush(db, today - timedelta(days=history_days + 30))
    db.commit()
    if verbose:
        print(f"  {len(hotels)} otel oluşturuldu")

    plan = _observation_plan(today, history_days, horizon)
    total_rows = 0
    for obs_day, stays in plan.items():
        observed = datetime.combine(obs_day, time(6, 0), tzinfo=timezone.utc)
        total_rows += ingest_rates(db, providers, hotels, stays, observed, infos, record_events=obs_day >= today - timedelta(days=14))
        tracker.flush(db, obs_day)
        db.commit()
    if verbose:
        print(f"  {total_rows} fiyat gözlemi yazıldı")

    for prov in settings.pilot_provinces:
        refresh_demand(db, providers.demand, prov, today - timedelta(days=history_days + 7), today + timedelta(days=horizon), "demo")
    tracker.flush(db, today)
    db.commit()

    plans = {p.code: p for p in db.execute(select(Plan)).scalars()}
    subscribers = _pick_subscribers(db, scale)
    demo_users = []
    for idx, (h, plan_code, ago, adoption) in enumerate(subscribers):
        start = today - timedelta(days=ago)
        h.is_subscriber = True
        hs = ensure_hotel_settings(db, h)
        hs.strategy = ["balanced", "aggressive", "balanced", "conservative"][idx % 4]
        hs.onboarding_done = True
        sub = Subscription(hotel_id=h.id, plan_id=plans[plan_code].id, status="active" if ago > 14 else "trial",
                           started_at=start, renews_at=start + timedelta(days=30 * (ago // 30 + 1)))
        db.add(sub)
        db.flush()
        m = start
        n = 1
        while m <= today:
            db.add(Invoice(subscription_id=sub.id, number=f"INV-{h.id:04d}-{n:03d}", period_start=m,
                           period_end=m + timedelta(days=29), amount_eur=plans[plan_code].monthly_price_eur,
                           status="paid" if m + timedelta(days=30) <= today else "open", issued_at=m))
            m += timedelta(days=30)
            n += 1
        email = "otel@otelradar.local" if idx == 0 else f"otel{idx + 1}@otelradar.local"
        db.add(User(email=email, password_hash=hash_password("Demo1234!"),
                    full_name=f"{h.name} Yetkilisi", role="hotel", hotel_id=h.id))
        demo_users.append(email)
        build_compset(db, h, today=start)
        db.flush()
        coefs = monthly_coefficients(db, h.province, h.district, today=today)["coef"]
        as_of = start
        while as_of < today:  # haftalık geçmiş öneri çalıştırmaları; bugünkü set aşağıda
            created = datetime.combine(as_of, time(5, 0), tzinfo=timezone.utc)
            generate_for_hotel(db, h, as_of, as_of + timedelta(days=horizon), as_of=as_of, created_at=created, coefs=coefs)
            as_of += timedelta(days=7)
        db.commit()
        _simulate_adoption(db, h, start, adoption, rng)
        # Bugünkü güncel öneri seti (uyum simülasyonundan sonra, güncel fiyatlarla)
        generate_for_hotel(db, h, today, today + timedelta(days=horizon), as_of=today,
                           created_at=datetime.combine(today, time(5, 0), tzinfo=timezone.utc), coefs=coefs)
        record_uptake(db, h)
        evaluate_outcomes(db, h, today=today, lookback_days=min(history_days, 45))
        db.commit()
        if verbose:
            print(f"  abone: {h.name} ({plan_code})")


    for idx, (h, *_rest) in enumerate(subscribers):
        sub = h.active_subscription
        estimate_did(db, h, sub.started_at, today=today)
        res = backtest_svc.run_backtest(db, h, today=today, days=30 if scale < 0.5 else 45)
        if res.get("summary"):
            backtest_svc.store_summary(db, h.id, res)
        # örnek compset geri bildirimi
        from app.services.market import compset_ids
        ids = compset_ids(db, h.id)
        if ids:
            set_feedback(db, h.id, ids[0], "confirmed")
            if len(ids) > 3 and idx % 2 == 0:
                set_feedback(db, h.id, ids[1], "confirmed")
        stats = uptake_stats(db, h.id, today=today)
        db.add(Notification(hotel_id=h.id, title="Haftalık özet hazır",
                            body=f"Son 60 günde gözlenen fiyatlarınızın %{stats['rate'] or 0:.0f}'i önerilerle uyumlu.",
                            level="info", link="/panel/performans"))
        db.add(Notification(hotel_id=h.id, title="Rakip setiniz güncellendi",
                            body="Sistem 5 rakip önerdi. Uygun olmayanları Rakipler ekranından değiştirebilirsiniz.",
                            level="success", link="/panel/rakipler", is_read=True))
        db.commit()

    admin = db.execute(select(User).where(User.role == "admin")).scalars().first()
    db.add(AuditLog(user_id=admin.id if admin else None, action="seed_demo", entity="system",
                    details={"hotels": len(hotels), "snapshots": total_rows, "subscribers": len(subscribers)}))
    run = db.get(JobRun, run.id)
    run.status, run.finished_at, run.records = "success", utcnow(), total_rows
    run.message = f"Demo veri: {len(hotels)} otel, {total_rows} fiyat gözlemi, {len(subscribers)} abone."
    db.commit()
    return {"hotels": len(hotels), "snapshots": total_rows, "subscribers": len(subscribers), "users": demo_users}


__all__ = ["seed_demo", "ensure_base"]
