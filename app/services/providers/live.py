"""Gerçek API istemcileri.

ÖNEMLİ: Makcorps ve Caviar'ın RapidAPI yanıt formatları henüz örnek yanıtla
doğrulanmadı (dokümandaki Açık Soru #1 ve #2). Ayrıştırıcılar savunmacı yazıldı ve
alan adları `RATE_FIELD_CANDIDATES` ile yapılandırılabilir. İlk gerçek yanıt
alındığında `tests/unit/test_live_clients.py` içindeki örnek yanıtlar
güncellenmeli ve ayrıştırıcı netleştirilmelidir.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx

from app.services.providers.base import (
    EventInfo,
    HotelInfo,
    PlaceInfo,
    ProviderError,
    RateItem,
)

Recorder = Callable[..., None]


def _noop(*_a, **_k) -> None:
    return None


class _Base:
    provider_key = "base"

    def __init__(self, client: httpx.Client | None = None, recorder: Recorder | None = None, retries: int = 2):
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        self.record = recorder or _noop
        self.retries = retries

    def _request(self, method: str, url: str, endpoint: str, **kwargs) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.client.request(method, url, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise ProviderError(f"{self.provider_key} {endpoint}: HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    self.record(self.provider_key, endpoint, 1, True)
                    raise ProviderError(f"{self.provider_key} {endpoint}: HTTP {resp.status_code} {resp.text[:200]}")
                self.record(self.provider_key, endpoint, 1, False)
                return resp.json()
            except (httpx.HTTPError, ProviderError) as exc:
                last_exc = exc
                if isinstance(exc, ProviderError) and "HTTP 4" in str(exc) and "429" not in str(exc):
                    raise
                if attempt < self.retries:
                    time.sleep(min(2**attempt * 0.5, 4))
        self.record(self.provider_key, endpoint, 1, True)
        raise ProviderError(str(last_exc))


# --------------------------------------------------------------------------- otel fiyatları
RATE_FIELD_CANDIDATES = {
    "room_list": ["rooms", "roomTypes", "room_types", "data", "results"],
    "room_name": ["room_name", "roomName", "name", "room_type", "type"],
    "price": ["price", "rate", "amount", "total", "price_per_night", "pricePerNight"],
    "currency": ["currency", "currency_code", "currencyCode"],
    "available": ["available_rooms", "availableRooms", "rooms_left", "roomsLeft", "availability", "inventory"],
}


def _first(d: dict, keys: list[str]):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return None


def parse_rate_response(payload: Any, default_currency: str = "EUR") -> list[RateItem]:
    """Bilinmeyen/değişken formatlı yanıttan oda listesi çıkarır."""
    rooms = payload
    if isinstance(payload, dict):
        rooms = _first(payload, RATE_FIELD_CANDIDATES["room_list"]) or []
        if isinstance(rooms, dict):
            rooms = _first(rooms, RATE_FIELD_CANDIDATES["room_list"]) or [rooms]
    if not isinstance(rooms, list):
        return []
    items: list[RateItem] = []
    for r in rooms:
        if not isinstance(r, dict):
            continue
        name = _first(r, RATE_FIELD_CANDIDATES["room_name"])
        if not name:
            continue
        price = _first(r, RATE_FIELD_CANDIDATES["price"])
        if isinstance(price, dict):
            price = _first(price, ["amount", "value", "total"])
        try:
            price_f = float(str(price).replace(",", "")) if price is not None else None
        except ValueError:
            price_f = None
        avail = _first(r, RATE_FIELD_CANDIDATES["available"])
        try:
            avail_i = int(avail) if avail is not None else None
        except (TypeError, ValueError):
            avail_i = None
        currency = _first(r, RATE_FIELD_CANDIDATES["currency"]) or (
            _first(payload, RATE_FIELD_CANDIDATES["currency"]) if isinstance(payload, dict) else None
        )
        items.append(RateItem(str(name).strip(), price_f, str(currency or default_currency).upper()[:3], avail_i))
    return items


class RapidApiHotelClient(_Base):
    """Makcorps veya Caviar (RapidAPI). Uç noktalar env ile yapılandırılır."""

    DEFAULT_HOSTS = {
        "makcorps": "makcorps-hotel-price-comparison.p.rapidapi.com",
        "caviar": "caviar-hotels.p.rapidapi.com",
    }

    def __init__(self, api_key: str, provider: str = "makcorps", host: str = "", **kw):
        super().__init__(**kw)
        if not api_key:
            raise ProviderError("RAPIDAPI_KEY tanımlı değil")
        self.provider_key = provider
        self.name = provider
        self.host = host or self.DEFAULT_HOSTS.get(provider, "")
        self.headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": self.host}

    def list_hotels(self, province: str) -> list[HotelInfo]:
        data = self._request(
            "GET", f"https://{self.host}/city", "city", headers=self.headers,
            params={"cityname": province, "country": "Turkey", "pagination": 0},
        )
        rows = data if isinstance(data, list) else _first(data, ["hotels", "data", "results"]) or []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = _first(row, ["hotelId", "hotel_id", "id"])
            name = _first(row, ["name", "hotelName", "hotel_name"])
            if not sid or not name:
                continue
            geo = row.get("geocode") or {}
            out.append(
                HotelInfo(
                    source_id=f"{self.provider_key}-{sid}",
                    name=str(name),
                    province=province,
                    district=_first(row, ["district", "city", "area"]) or "",
                    lat=_first(geo, ["latitude", "lat"]) or _first(row, ["latitude", "lat"]),
                    lng=_first(geo, ["longitude", "lng"]) or _first(row, ["longitude", "lng"]),
                    star_rating=_first(row, ["stars", "star_rating", "hotelClass"]),
                )
            )
        return out

    def get_rates(self, hotel: HotelInfo | str, stay_date: date, observed: date) -> list[RateItem]:
        sid = hotel if isinstance(hotel, str) else hotel.source_id
        ext_id = sid.split("-", 1)[1] if "-" in sid else sid
        data = self._request(
            "GET", f"https://{self.host}/hotel", "hotel", headers=self.headers,
            params={
                "hotelid": ext_id,
                "checkin": stay_date.isoformat(),
                "checkout": (stay_date + timedelta(days=1)).isoformat(),
                "adults": 2, "rooms": 1, "currency": "EUR",
            },
        )
        return parse_rate_response(data)


# --------------------------------------------------------------------------- Amadeus
class AmadeusClient(_Base):
    provider_key = "amadeus"
    name = "amadeus"
    # Bölge -> hedef şehir IATA kodu
    CITY_CODES = {"Muğla": ["BJV", "DLM"], "Antalya": ["AYT"]}
    MARKETS = ["DE", "GB", "RU", "TR", "NL"]

    def __init__(self, client_id: str, client_secret: str, base_url: str, **kw):
        super().__init__(**kw)
        if not (client_id and client_secret):
            raise ProviderError("AMADEUS_CLIENT_ID / SECRET tanımlı değil")
        self.client_id, self.client_secret, self.base_url = client_id, client_secret, base_url.rstrip("/")
        self._token: str | None = None
        self._token_exp = 0.0

    def _auth(self) -> dict[str, str]:
        if not self._token or time.time() > self._token_exp - 60:
            data = self._request(
                "POST", f"{self.base_url}/v1/security/oauth2/token", "oauth",
                data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret},
            )
            self._token = data["access_token"]
            self._token_exp = time.time() + int(data.get("expires_in", 1799))
        return {"Authorization": f"Bearer {self._token}"}

    def flight_search_index(self, province: str, dates: list[date]) -> dict[date, float]:
        """'Flight Most Searched Destinations' analitiğinden aylık arama hacmi endeksi.
        Yanıt aylık olduğundan aynı aydaki günler aynı skoru alır."""
        months = sorted({d.strftime("%Y-%m") for d in dates})
        month_score: dict[str, float] = {}
        for m in months:
            scores = []
            for market in self.MARKETS:
                data = self._request(
                    "GET", f"{self.base_url}/v1/travel/analytics/air-traffic/searched/by-destination",
                    "searched-by-destination", headers=self._auth(),
                    params={"originCityCode": "IST" if market == "TR" else "LON" if market == "GB" else "FRA",
                            "destinationCityCode": self.CITY_CODES.get(province, ["AYT"])[0],
                            "searchPeriod": m, "marketCountryCode": market},
                )
                for row in (data.get("data") or []):
                    score = (row.get("analytics") or {}).get("searches", {}).get("score")
                    if score is not None:
                        scores.append(float(score))
            month_score[m] = round(sum(scores) / len(scores), 1) if scores else 50.0
        return {d: month_score[d.strftime("%Y-%m")] for d in dates}

    def events(self, province: str, start: date, end: date) -> list[EventInfo]:  # pragma: no cover
        return []


# --------------------------------------------------------------------------- PredictHQ
class PredictHQClient(_Base):
    provider_key = "predicthq"
    name = "predicthq"
    CENTERS = {"Muğla": (37.0, 28.2, "80km"), "Antalya": (36.88, 30.7, "90km")}
    CATEGORIES = "concerts,conferences,expos,festivals,performing-arts,sports,community,public-holidays,school-holidays"

    def __init__(self, token: str, **kw):
        super().__init__(**kw)
        if not token:
            raise ProviderError("PREDICTHQ_TOKEN tanımlı değil")
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def events(self, province: str, start: date, end: date) -> list[EventInfo]:
        lat, lng, radius = self.CENTERS.get(province, (37.0, 28.2, "80km"))
        out: list[EventInfo] = []
        url = "https://api.predicthq.com/v1/events/"
        params: dict | None = {
            "within": f"{radius}@{lat},{lng}",
            "active.gte": start.isoformat(), "active.lte": end.isoformat(),
            "category": self.CATEGORIES, "limit": 200, "sort": "start",
        }
        pages = 0
        while url and pages < 10:
            data = self._request("GET", url, "events", headers=self.headers, params=params)
            for ev in data.get("results", []):
                try:
                    s = date.fromisoformat(ev["start"][:10])
                    e = date.fromisoformat((ev.get("end") or ev["start"])[:10])
                except (KeyError, ValueError):
                    continue
                rank = ev.get("local_rank") or ev.get("rank") or 50
                out.append(EventInfo(
                    external_id=f"phq-{ev.get('id')}", name=ev.get("title", "Etkinlik"),
                    category=ev.get("category", "other"), start_date=s, end_date=e,
                    impact=int(min(100, rank if isinstance(rank, (int, float)) else 50)),
                ))
            url = data.get("next")
            params = None
            pages += 1
        return out

    def flight_search_index(self, province: str, dates: list[date]) -> dict[date, float]:  # pragma: no cover
        return {}


# --------------------------------------------------------------------------- Google Places
class GooglePlacesClient(_Base):
    provider_key = "google_places"
    name = "google_places"

    def __init__(self, api_key: str, **kw):
        super().__init__(**kw)
        if not api_key:
            raise ProviderError("GOOGLE_MAPS_KEY tanımlı değil")
        self.api_key = api_key

    def lookup(self, name: str, address: str | None, province: str, district: str | None) -> PlaceInfo:
        data = self._request(
            "POST", "https://places.googleapis.com/v1/places:searchText", "searchText",
            headers={
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "places.id,places.location,places.types,places.rating,places.formattedAddress",
            },
            json={"textQuery": f"{name} {address or ''} {district or ''} {province} Türkiye", "languageCode": "tr"},
        )
        places = data.get("places") or []
        if not places:
            return PlaceInfo(None, None, None)
        p = places[0]
        loc = p.get("location") or {}
        return PlaceInfo(p.get("id"), loc.get("latitude"), loc.get("longitude"), p.get("types") or [],
                         p.get("rating"), p.get("formattedAddress"))


# --------------------------------------------------------------------------- Kur
class FixerClient(_Base):
    provider_key = "fixer"
    name = "fixer"

    def __init__(self, api_key: str, **kw):
        super().__init__(**kw)
        if not api_key:
            raise ProviderError("FX_API_KEY tanımlı değil")
        self.api_key = api_key

    def rates(self, day: date) -> dict[str, float]:
        data = self._request(
            "GET", f"https://data.fixer.io/api/{day.isoformat()}", "historical",
            params={"access_key": self.api_key, "symbols": "TRY,USD,GBP"},
        )
        if not data.get("success", True):
            raise ProviderError(f"fixer: {data.get('error')}")
        rates = {k: float(v) for k, v in (data.get("rates") or {}).items()}
        rates["EUR"] = 1.0
        return rates


# --------------------------------------------------------------------------- ECB (anahtarsız kur)
class EcbFxClient(_Base):
    """Avrupa Merkez Bankası günlük referans kurları (anahtar gerektirmez). FX_API_KEY yoksa kullanılır."""

    provider_key = "ecb"
    name = "ecb"
    URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    def rates(self, day: date) -> dict[str, float]:
        import re as _re

        resp = self.client.get(self.URL)
        if resp.status_code != 200:
            self.record(self.provider_key, "daily", 1, True)
            raise ProviderError(f"ecb: HTTP {resp.status_code}")
        self.record(self.provider_key, "daily", 1, False)
        rates = {m.group(1): float(m.group(2)) for m in _re.finditer(r"currency='([A-Z]{3})' rate='([0-9.]+)'", resp.text)}
        if "TRY" not in rates:
            raise ProviderError("ecb: TRY kuru bulunamadı")
        rates["EUR"] = 1.0
        return rates


# --------------------------------------------------------------------------- canlı modda eksik bileşenler
class MissingRates:
    """Canlı modda RapidAPI anahtarı yoksa sahte veri üretmek yerine açık hata verir."""

    name = "missing"

    def list_hotels(self, province):
        raise ProviderError("RAPIDAPI_KEY tanımlı değil: canlı modda otel fiyat verisi çekilemez.")

    def get_rates(self, hotel, stay_date, observed):
        raise ProviderError("RAPIDAPI_KEY tanımlı değil: canlı modda otel fiyat verisi çekilemez.")


class NeutralDemand:
    """Uçuş/etkinlik kaynağı yoksa nötr değer döndürür (50 puan, etkinlik yok); demo veri KULLANILMAZ."""

    name = "neutral"

    def flight_search_index(self, province, dates):
        return {d: 50.0 for d in dates}

    def events(self, province, start, end):
        return []


class NullPlaces:
    name = "none"

    def lookup(self, name, address, province, district):
        from app.services.providers.base import PlaceInfo

        return PlaceInfo(None, None, None)
