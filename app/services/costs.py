"""Birim ekonomisi: abone başına API maliyeti. Doküman 4.4 ve Açık Soru #3.

Varsayılan birim fiyatlar YER TUTUCUDUR — sağlayıcıların güncel fiyat sayfalarına
göre yönetim panelinden (API & Maliyet) güncellenmelidir.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ApiUsage, Plan, ProviderCost

DEFAULT_PROVIDER_COSTS = [
    # provider, etiket, birim €, aylık sabit €, dahil istek, not
    ("liteapi", "LiteAPI (rakip fiyatı, kalan oda)", 0.0, 0.0, 0,
     "Arama ücretsiz, ancak arama/rezervasyon oranı 5000:1 aşılırsa faturalanabilir; kullanım koşulları teyit edilmeli."),
    ("dataforseo", "DataForSEO (Google Hotels fiyat takvimi)", 0.0074, 0.0, 0,
     "Fiyat takvimi isteği ~0,008 $, otel arama ~0,004 $ (25 Kasım 2026 gözlemi). Ön ödemeli bakiye."),
    ("travelpayouts", "Travelpayouts (uçuş fiyat endeksi)", 0.0, 0.0, 0,
     "Ücretsiz Data API; satış ortaklığı koşulları teyit edilmeli."),
    ("predicthq", "PredictHQ (etkinlikler)", 0.0, 0.0, 0, "Developer Plan; ticari kullanım kapsamı doğrulanmalı."),
    ("google_places", "Google Places (konum)", 0.028, 0.0, 0, "Yer tutucu. Text Search birim fiyatı; tek seferlik çağrı."),
    ("llm", "LLM (belirsiz oda eşleme)", 0.0005, 0.0, 0, "Yer tutucu. Yalnızca belirsiz oda adları gönderilir."),
]
REMOVED_PROVIDERS = ("rapidapi", "amadeus", "fixer")  # 25 Kasım 2026'da kaldırıldı


@dataclass
class EconomicsInput:
    subscribers: int = 10
    compset_size: int = 5
    horizon_days: int = 60
    scans_per_day: int = 1
    dates_per_request: int = 1      # API tek çağrıda birden çok tarih döndürüyorsa artırın
    overlap_pct: float = 30.0       # abonelerin rakip setlerindeki ortak oteller
    provinces: int = 2
    new_hotels_per_month: int = 5
    llm_rooms_per_month: int = 40


def ensure_provider_costs(db: Session) -> None:
    for old in REMOVED_PROVIDERS:
        row = db.get(ProviderCost, old)
        if row is not None:
            db.delete(row)
    for provider, label, unit, fee, incl, note in DEFAULT_PROVIDER_COSTS:
        if db.get(ProviderCost, provider) is None:
            db.add(ProviderCost(provider=provider, label=label, unit_cost_eur=unit, monthly_fee_eur=fee,
                                included_requests=incl, notes=note))
    db.flush()


def estimate_monthly_requests(inp: EconomicsInput) -> dict[str, int]:
    tracked = inp.subscribers * (1 + inp.compset_size) * (1 - inp.overlap_pct / 100)
    tracked = max(tracked, inp.subscribers)
    months_ahead = max(1, round(inp.horizon_days / 30) + 1)
    chunks = -(-round(tracked) // 40)  # LiteAPI bir tarih için 40 oteli tek istekte sorgular
    return {
        # 1 fiyat isteği + kalan oda merdiveninde ortalama ~2 istek
        "liteapi": round(inp.horizon_days * inp.scans_per_day * 30 * chunks * 3 + inp.provinces * 8 * 30),
        # LiteAPI'de teklifi olmayan oteller için günlük Google fiyat takvimi (otel başına 1 istek)
        "dataforseo": round(tracked * 30 + inp.new_hotels_per_month),
        "travelpayouts": inp.provinces * 6 * months_ahead * 30,
        "predicthq": inp.provinces * 30 * 2,
        "google_places": inp.new_hotels_per_month,
        "llm": inp.llm_rooms_per_month,
    }


def provider_cost(pc: ProviderCost, requests: int) -> float:
    billable = max(0, requests - int(pc.included_requests or 0))
    return float(pc.monthly_fee_eur or 0) + billable * float(pc.unit_cost_eur or 0)


def unit_economics(db: Session, inp: EconomicsInput) -> dict:
    ensure_provider_costs(db)
    reqs = estimate_monthly_requests(inp)
    rows = []
    total = 0.0
    for pc in db.execute(select(ProviderCost).order_by(ProviderCost.provider)).scalars():
        if not pc.enabled:
            continue
        r = reqs.get(pc.provider, 0)
        c = provider_cost(pc, r)
        total += c
        rows.append({"provider": pc.provider, "label": pc.label, "requests": r, "cost": round(c, 2),
                     "unit_cost": float(pc.unit_cost_eur), "monthly_fee": float(pc.monthly_fee_eur),
                     "included": pc.included_requests, "notes": pc.notes})
    per_sub = total / max(1, inp.subscribers)
    plans = []
    for p in db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)).scalars():
        price = float(p.monthly_price_eur)
        margin = price - per_sub
        plans.append({"name": p.name, "price": price, "cost_per_sub": round(per_sub, 2), "margin": round(margin, 2),
                      "margin_pct": round(margin / price * 100, 1) if price else None})
    return {"input": asdict(inp), "rows": rows, "total": round(total, 2), "per_subscriber": round(per_sub, 2),
            "plans": plans}


def measured_usage(db: Session, days: int = 30, today: date | None = None) -> dict:
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    by_provider = dict(db.execute(
        select(ApiUsage.provider, func.sum(ApiUsage.requests)).where(ApiUsage.day >= start).group_by(ApiUsage.provider)
    ).all())
    by_day = db.execute(
        select(ApiUsage.day, ApiUsage.provider, func.sum(ApiUsage.requests))
        .where(ApiUsage.day >= start).group_by(ApiUsage.day, ApiUsage.provider).order_by(ApiUsage.day)
    ).all()
    costs = {pc.provider: pc for pc in db.execute(select(ProviderCost)).scalars()}
    cost_total = sum(provider_cost(costs[p], int(r or 0)) for p, r in by_provider.items() if p in costs)
    errors = db.execute(select(func.sum(ApiUsage.errors)).where(ApiUsage.day >= start)).scalar() or 0
    return {"by_provider": {k: int(v or 0) for k, v in by_provider.items()},
            "by_day": [(d.isoformat(), p, int(r or 0)) for d, p, r in by_day],
            "cost_total": round(cost_total, 2), "errors": int(errors), "start": start.isoformat()}
