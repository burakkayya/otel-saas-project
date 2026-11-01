"""Veri hattı: otel envanteri, fiyat/oda çekme, envanter olayları, kur, talep,
compset, öneri ve uyum hesapları. Zamanlayıcı ve yönetim paneli bu işleri çağırır."""
from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AppSetting,
    FxRate,
    Hotel,
    HotelSettings,
    InventoryEvent,
    JobRun,
    Notification,
    PriceSuggestion,
    RateSnapshot,
    RoomType,
    utcnow,
)
from app.services import backtest as backtest_svc
from app.services.compset import build_compset
from app.services.demand import refresh_demand
from app.services.market import compset_ids, latest_observations, subscriber_hotels
from app.services.pricing import generate_for_hotel
from app.services.providers import ProviderBundle, UsageTracker, get_providers
from app.services.providers.base import HotelInfo
from app.services.roi import estimate_did
from app.services.room_mapping import map_room
from app.services.uptake import record_uptake

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- yardımcılar
def get_setting(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    return row.value if row is not None else default


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    db.flush()


def fx_for(db: Session, providers: ProviderBundle, day: date) -> dict[str, float]:
    rows = list(db.execute(select(FxRate).where(FxRate.date == day)).scalars())
    if rows:
        return {r.currency: float(r.per_eur) for r in rows}
    rates = providers.fx.rates(day)
    for cur, val in rates.items():
        db.add(FxRate(date=day, currency=cur, per_eur=val, source=providers.mode))
    db.flush()
    return rates


def upsert_hotel(db: Session, info: HotelInfo, providers: ProviderBundle | None = None) -> Hotel:
    h = db.execute(select(Hotel).where(Hotel.source_id == info.source_id)).scalar_one_or_none()
    if h is None:
        h = Hotel(source_id=info.source_id, name=info.name, province=info.province)
        db.add(h)
    h.name = info.name
    h.province = info.province
    h.district = info.district or h.district
    h.address = info.address or h.address
    h.hotel_type = info.hotel_type or h.hotel_type
    h.star_rating = info.star_rating or h.star_rating
    h.room_count = info.room_count or h.room_count
    if info.lat is not None:
        h.lat, h.lng = info.lat, info.lng
    elif providers is not None and h.lat is None:
        place = providers.places.lookup(info.name, info.address, info.province, info.district)
        h.lat, h.lng, h.place_id = place.lat, place.lng, place.place_id
    db.flush()
    return h


def ensure_room_type(db: Session, hotel: Hotel, raw_name: str, cache: dict | None = None) -> RoomType:
    key = (hotel.id, raw_name)
    if cache is not None and key in cache:
        return cache[key]
    rt = db.execute(select(RoomType).where(RoomType.hotel_id == hotel.id, RoomType.raw_name == raw_name)).scalar_one_or_none()
    if rt is None:
        m = map_room(raw_name, hotel_context=f"{hotel.name} ({hotel.star_rating or '?'}*, {hotel.hotel_type or ''})")
        rt = RoomType(hotel_id=hotel.id, raw_name=raw_name, category=m.category, mapped_by=m.mapped_by,
                      confidence=m.confidence, reviewed=False)
        db.add(rt)
        db.flush()
    if cache is not None:
        cache[key] = rt
    return rt


def classify_inventory(prev: int | None, new: int | None) -> str | None:
    if prev is None or new is None:
        return None
    if new == prev:
        return "unchanged"
    if new == 0 and prev > 0:
        return "closed"
    if prev == 0 and new > 0:
        return "reopen"
    if new < prev:
        return "drop"
    return "reopen"


def ingest_rates(
    db: Session, providers: ProviderBundle, hotels: list[Hotel], stay_dates: list[date], observed_at: datetime,
    infos: dict[str, HotelInfo] | None = None, record_events: bool = True,
) -> int:
    """Fiyat ve kalan oda gözlemlerini toplu olarak yazar."""
    fx = fx_for(db, providers, observed_at.date())
    rt_cache: dict = {}
    hotel_rts = {h.id: [] for h in hotels}
    rows = []
    for h in hotels:
        target = (infos or {}).get(h.source_id) or h.source_id
        for stay in stay_dates:
            if stay < observed_at.date():
                continue
            for item in providers.rates.get_rates(target, stay, observed_at.date()):
                rt = ensure_room_type(db, h, item.raw_room_name, rt_cache)
                hotel_rts[h.id].append(rt.id)
                rate = fx.get(item.currency) or 1.0
                rows.append({
                    "room_type_id": rt.id, "stay_date": stay, "observed_at": observed_at,
                    "price_original": item.price, "currency": item.currency,
                    "price_eur": round(item.price / rate, 2) if item.price is not None else None,
                    "available_rooms": item.available_rooms, "source": providers.rates.name,
                })
    if record_events and rows:
        rt_ids = list({r["room_type_id"] for r in rows})
        prev = latest_observations(db, rt_ids, min(stay_dates), max(stay_dates), as_of=observed_at.date() - timedelta(days=1))
        events = []
        for r in rows:
            p = prev.get((r["room_type_id"], r["stay_date"]))
            et = classify_inventory(p.available if p else None, r["available_rooms"])
            if et and et != "unchanged":
                events.append({"room_type_id": r["room_type_id"], "stay_date": r["stay_date"], "observed_at": observed_at,
                               "prev_count": p.available, "new_count": r["available_rooms"], "event_type": et})
        if events:
            db.execute(insert(InventoryEvent), events)
    if rows:
        for i in range(0, len(rows), 5000):
            db.execute(insert(RateSnapshot), rows[i:i + 5000])
    db.flush()
    return len(rows)


def scan_scope_hotels(db: Session) -> list[Hotel]:
    """Taranacak oteller. 'all': pilot bölgedeki tüm oteller (kontrol grubu için gerekli),
    'compset': yalnızca aboneler ve rakipleri (maliyet tasarrufu)."""
    scope = get_setting(db, "scan_scope", "all")
    if scope == "compset":
        ids: set[int] = set()
        for h in subscriber_hotels(db):
            ids.add(h.id)
            ids.update(compset_ids(db, h.id))
        if not ids:
            return []
        return list(db.execute(select(Hotel).where(Hotel.id.in_(ids))).scalars())
    return list(db.execute(select(Hotel).where(Hotel.is_active.is_(True), Hotel.province.in_(settings.pilot_provinces))).scalars())


def notify_big_moves(db: Session, hotel: Hotel, suggestions: list[PriceSuggestion], threshold: float = 12.0) -> int:
    moves = [s for s in suggestions
             if s.rationale and s.rationale.get("change_vs_own_pct") is not None
             and abs(s.rationale["change_vs_own_pct"]) >= threshold and (s.stay_date - date.today()).days <= 21]
    if not moves:
        return 0
    up = sum(1 for s in moves if s.rationale["change_vs_own_pct"] > 0)
    down = len(moves) - up
    body = f"Önümüzdeki 3 haftada {len(moves)} gün için mevcut fiyatınızdan %{threshold:.0f}+ sapan öneri var"
    body += f" ({up} artış, {down} düşüş)."
    db.add(Notification(hotel_id=hotel.id, title="Dikkat gerektiren fiyat önerileri", body=body,
                        level="warning", link="/panel/oneriler?sadece=onemli"))
    return 1


# --------------------------------------------------------------------------- işler
def job_daily(db: Session, today: date | None = None, tracker: UsageTracker | None = None) -> tuple[int, str]:
    today = today or date.today()
    tracker = tracker or UsageTracker()
    providers = get_providers(tracker)
    infos: dict[str, HotelInfo] = {}
    for prov in settings.pilot_provinces:
        for info in providers.rates.list_hotels(prov):
            infos[info.source_id] = info
            upsert_hotel(db, info, providers)
    hotels = scan_scope_hotels(db)
    horizon = int(get_setting(db, "horizon_days", settings.horizon_days))
    stays = [today + timedelta(days=i) for i in range(horizon + 1)]
    observed = datetime.combine(today, time(6, 0), tzinfo=timezone.utc)
    # Aynı gün ikinci kez çalıştırılırsa önceki gözlemlerin yerine yazar (idempotent)
    rt_ids = select(RoomType.id).where(RoomType.hotel_id.in_([h.id for h in hotels]))
    db.execute(delete(RateSnapshot).where(RateSnapshot.observed_at == observed, RateSnapshot.room_type_id.in_(rt_ids)))
    db.execute(delete(InventoryEvent).where(InventoryEvent.observed_at == observed, InventoryEvent.room_type_id.in_(rt_ids)))
    n = ingest_rates(db, providers, hotels, stays, observed, infos)
    for prov in settings.pilot_provinces:
        refresh_demand(db, providers.demand, prov, today - timedelta(days=7), today + timedelta(days=horizon), providers.mode)
    sugg = 0
    for h in subscriber_hotels(db):
        if not compset_ids(db, h.id):
            build_compset(db, h, today=today)
        created = generate_for_hotel(db, h, today, today + timedelta(days=horizon), as_of=today)
        sugg += len(created)
        notify_big_moves(db, h, created)
        record_uptake(db, h, since=observed - timedelta(hours=1))
    tracker.flush(db, today)
    return n + sugg, f"{len(hotels)} otel tarandı, {n} fiyat gözlemi, {sugg} öneri üretildi ({providers.mode} modu)."


def job_demand(db: Session, today: date | None = None, tracker: UsageTracker | None = None) -> tuple[int, str]:
    today = today or date.today()
    tracker = tracker or UsageTracker()
    providers = get_providers(tracker)
    horizon = int(get_setting(db, "horizon_days", settings.horizon_days))
    n = 0
    for prov in settings.pilot_provinces:
        n += refresh_demand(db, providers.demand, prov, today - timedelta(days=7), today + timedelta(days=horizon), providers.mode)
    tracker.flush(db, today)
    return n, f"{n} gün için talep skoru güncellendi."


def job_suggestions(db: Session, today: date | None = None, **_) -> tuple[int, str]:
    today = today or date.today()
    horizon = int(get_setting(db, "horizon_days", settings.horizon_days))
    n = 0
    for h in subscriber_hotels(db):
        n += len(generate_for_hotel(db, h, today, today + timedelta(days=horizon), as_of=today))
    return n, f"{n} öneri üretildi."


def job_compsets(db: Session, today: date | None = None, **_) -> tuple[int, str]:
    hs = subscriber_hotels(db)
    for h in hs:
        build_compset(db, h, today=today)
    return len(hs), f"{len(hs)} abone için rakip seti yeniden hesaplandı (elle eklenenler korundu)."


def job_uptake(db: Session, **_) -> tuple[int, str]:
    n = sum(record_uptake(db, h) for h in subscriber_hotels(db))
    return n, f"{n} yeni uyum gözlemi kaydedildi."


def job_roi(db: Session, today: date | None = None, **_) -> tuple[int, str]:
    n = 0
    for h in subscriber_hotels(db):
        sub = h.active_subscription
        if not sub:
            continue
        res = estimate_did(db, h, sub.started_at, today=today)
        n += 1 if res.get("status") == "ok" else 0
    return n, f"{n} abone için kontrol grubu (DiD) tahmini güncellendi."


def job_backtest(db: Session, today: date | None = None, **_) -> tuple[int, str]:
    n = 0
    for h in subscriber_hotels(db):
        res = backtest_svc.run_backtest(db, h, today=today)
        if res.get("summary"):
            backtest_svc.store_summary(db, h.id, res)
            n += 1
    return n, f"{n} abone için backtest özeti güncellendi."


JOBS: dict[str, tuple[str, Callable]] = {
    "daily_pipeline": ("Günlük veri hattı (fiyat + talep + öneri + uyum)", job_daily),
    "demand_refresh": ("Talep sinyali yenileme", job_demand),
    "suggestions": ("Fiyat önerisi üretimi", job_suggestions),
    "compset_rebuild": ("Rakip setlerini yeniden hesapla", job_compsets),
    "uptake": ("Öneriye uyum hesabı", job_uptake),
    "roi_did": ("Kontrol grubu (DiD) tahmini", job_roi),
    "backtest": ("Backtest özetleri", job_backtest),
}


def run_job(db: Session, name: str, trigger: str = "manual", **kwargs) -> JobRun:
    if name not in JOBS:
        raise KeyError(name)
    run = JobRun(job_name=name, status="running", trigger=trigger, started_at=utcnow())
    db.add(run)
    db.commit()
    try:
        records, message = JOBS[name][1](db, **kwargs)
        run.status, run.records, run.message = "success", records, message
    except Exception as exc:  # noqa: BLE001 - iş hatası kaydedilip yönetime gösterilir
        db.rollback()
        log.exception("İş başarısız: %s", name)
        run = db.get(JobRun, run.id)
        run.status = "failed"
        run.message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}"
    run.finished_at = utcnow()
    db.commit()
    return run


def ensure_hotel_settings(db: Session, hotel: Hotel) -> HotelSettings:
    if hotel.settings is None:
        hotel.settings = HotelSettings(hotel_id=hotel.id)
        db.flush()
    return hotel.settings
