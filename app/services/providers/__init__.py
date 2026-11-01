"""Sağlayıcı fabrikası ve API kullanım sayacı."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.config import settings as default_settings
from app.services.providers.base import ProviderBundle, ProviderError
from app.services.providers.demo import DemoProvider

log = logging.getLogger(__name__)


class UsageTracker:
    """Sağlayıcı başına istek sayısını toplar ve api_usage tablosuna yazar.

    Demo modunda da çalışır: gerçek API kullanılsaydı yapılacak istek sayısı
    sayılır; böylece birim ekonomisi demo verisiyle bile hesaplanabilir."""

    def __init__(self):
        self.counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])

    def record(self, provider: str, endpoint: str, requests: int = 1, error: bool = False) -> None:
        c = self.counts[(provider, endpoint)]
        c[0] += requests
        if error:
            c[1] += 1

    def flush(self, db: Session, day: date | None = None) -> int:
        from app.models import ApiUsage

        day = day or date.today()
        total = 0
        for (provider, endpoint), (reqs, errs) in self.counts.items():
            row = db.execute(
                select(ApiUsage).where(ApiUsage.day == day, ApiUsage.provider == provider, ApiUsage.endpoint == endpoint)
            ).scalar_one_or_none()
            if row is None:
                row = ApiUsage(day=day, provider=provider, endpoint=endpoint, requests=0, errors=0)
                db.add(row)
            row.requests += reqs
            row.errors += errs
            total += reqs
        self.counts.clear()
        return total


class _Counting:
    """Demo sağlayıcı çağrılarını gerçek sağlayıcı adıyla sayan vekil."""

    MAP = {
        "list_hotels": ("rapidapi", "city"),
        "get_rates": ("rapidapi", "hotel"),
        "flight_search_index": ("amadeus", "searched-by-destination"),
        "events": ("predicthq", "events"),
        "lookup": ("google_places", "searchText"),
        "rates": ("fixer", "historical"),
    }

    def __init__(self, inner, tracker: UsageTracker):
        self._inner = inner
        self._tracker = tracker
        self.name = getattr(inner, "name", "demo")

    def __getattr__(self, item):
        attr = getattr(self._inner, item)
        if item in self.MAP and callable(attr):
            provider, endpoint = self.MAP[item]

            def wrapped(*a, **k):
                self._tracker.record(provider, endpoint)
                return attr(*a, **k)

            return wrapped
        return attr


_demo_singleton: DemoProvider | None = None


def demo_provider(scale: float = 1.0) -> DemoProvider:
    global _demo_singleton
    if _demo_singleton is None or _demo_singleton.scale != scale:
        _demo_singleton = DemoProvider(scale=scale)
    return _demo_singleton


def get_providers(tracker: UsageTracker | None = None, cfg: Settings | None = None, scale: float = 1.0) -> ProviderBundle:
    cfg = cfg or default_settings
    tracker = tracker or UsageTracker()
    demo = demo_provider(scale)
    counted_demo = _Counting(demo, tracker)
    if cfg.is_demo:
        return ProviderBundle(rates=counted_demo, demand=counted_demo, places=counted_demo, fx=counted_demo, mode="demo")

    from app.services.providers import live

    # Canlı modda anahtarı olmayan bileşen için SAHTE veri kullanılmaz:
    # fiyat -> açık hata, uçuş/etkinlik -> nötr, konum -> boş, kur -> ECB (anahtarsız).
    missing: list[str] = []
    try:
        rates = live.RapidApiHotelClient(cfg.rapidapi_key, cfg.rapidapi_hotel_provider, cfg.rapidapi_host,
                                         recorder=tracker.record)
    except ProviderError:
        rates, _ = live.MissingRates(), missing.append("otel fiyatları (RAPIDAPI_KEY)")
    try:
        flights = live.AmadeusClient(cfg.amadeus_client_id, cfg.amadeus_client_secret, cfg.amadeus_base_url,
                                     recorder=tracker.record)
    except ProviderError:
        flights, _ = live.NeutralDemand(), missing.append("uçuş arama trendi (Amadeus)")
    try:
        events = live.PredictHQClient(cfg.predicthq_token, recorder=tracker.record)
    except ProviderError:
        events, _ = live.NeutralDemand(), missing.append("etkinlikler (PredictHQ)")
    try:
        places = live.GooglePlacesClient(cfg.google_maps_key, recorder=tracker.record)
    except ProviderError:
        places, _ = live.NullPlaces(), missing.append("konum (Google Places)")
    try:
        fx = live.FixerClient(cfg.fx_api_key, recorder=tracker.record)
    except ProviderError:
        fx = live.EcbFxClient(recorder=tracker.record)
    bundle = ProviderBundle(rates=rates, demand=_CombinedDemand(flights, events), places=places, fx=fx,
                            mode="live" if not missing else "mixed")
    bundle.missing = missing
    if missing:
        log.warning("Canlı modda eksik veri kaynakları: %s", ", ".join(missing))
    return bundle


class _CombinedDemand:
    name = "combined"

    def __init__(self, flights, events):
        self._f, self._e = flights, events

    def flight_search_index(self, province, dates):
        return self._f.flight_search_index(province, dates)

    def events(self, province, start, end):
        return self._e.events(province, start, end)
