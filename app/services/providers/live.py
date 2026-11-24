"""Gerçek API istemcileri.

Rakip fiyatı ve kalan oda: LiteAPI (Nuitee); fiyat kapsamı: DataForSEO (Google Hotels);
uçuş talebi vekili: Travelpayouts; etkinlik: PredictHQ; konum: Google Places; kur: ECB.
Yanıt biçimleri 24-25 Kasım 2026'da gerçek isteklerle doğrulandı (docs/CANLI_TEST_2026-11-24.md).
"""
from __future__ import annotations

import re
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


# --------------------------------------------------------------------------- LiteAPI (Nuitee)
LITEAPI_DEFAULT_CITIES = {
    "Muğla": ["Bodrum", "Marmaris", "Fethiye", "Dalaman", "Datça", "Köyceğiz", "Milas", "Ortaca"],
    "Antalya": ["Antalya", "Alanya", "Kemer", "Belek", "Side", "Manavgat", "Kaş", "Kalkan"],
}


def parse_city_map(raw: str) -> dict[str, list[str]]:
    """'Muğla:Bodrum,Marmaris;Antalya:Kemer' -> {"Muğla": ["Bodrum", "Marmaris"], "Antalya": ["Kemer"]}"""
    out: dict[str, list[str]] = {}
    for part in (raw or "").split(";"):
        if ":" not in part:
            continue
        prov, cities = part.split(":", 1)
        out[prov.strip()] = [c.strip() for c in cities.split(",") if c.strip()]
    return out


_RATE_PLAN_WORDS = re.compile(
    r"breakfast|board|plan|inclusive|room only|refund|iade|kahvalt|pansiyon|her şey dahil|yarım|tam ", re.I)


def clean_room_name(name: str) -> str:
    """Oda adından pansiyon ve iade koşulu parçalarını atar:
    'Studio Oda - Bed & breakfast - İade Edilemez' -> 'Studio Oda'."""
    parts = [p.strip() for p in " ".join(str(name).split()).split(" - ")]
    kept = [p for i, p in enumerate(parts) if i == 0 or not _RATE_PLAN_WORDS.search(p)]
    return " - ".join(kept)


def full_room_types(hotel_entry: dict, n: int) -> set[str]:
    """n odalık sorguda, n odanın HEPSİNİ aynı oda tipinden karşılayan teklifler -> o oda tipleri.

    Bu tipte satış kanalında en az n oda açık demektir (kalan oda alt sınırı)."""
    out: set[str] = set()
    for offer in hotel_entry.get("roomTypes") or []:
        rates = offer.get("rates") or []
        names = {clean_room_name(r.get("name") or "") for r in rates}
        occ = {r.get("occupancyNumber") for r in rates}
        if len(names) == 1 and occ >= set(range(1, n + 1)):
            out |= names
    out.discard("")
    return out


def parse_liteapi_rates(hotel_entry: dict) -> list[RateItem]:
    """Bir otelin teklifleri -> oda adı başına en ucuz gecelik fiyat (vergiler dahil toplam).

    LiteAPI kalan oda sayısı vermez; available_rooms burada None, oda merdiveniyle sonradan doldurulur."""
    best: dict[str, tuple[float, str]] = {}
    for offer in hotel_entry.get("roomTypes") or []:
        for rate in offer.get("rates") or []:
            if rate.get("occupancyNumber", 1) != 1:
                continue
            name = clean_room_name(rate.get("name") or "")
            totals = ((rate.get("retailRate") or {}).get("total") or [])
            if not name or not totals:
                continue
            try:
                amount = float(totals[0].get("amount"))
            except (TypeError, ValueError):
                continue
            cur = str(totals[0].get("currency") or "EUR").upper()[:3]
            if name not in best or amount < best[name][0]:
                best[name] = (amount, cur)
    return [RateItem(name, round(p, 2), cur, None) for name, (p, cur) in best.items()]


class LiteApiHotelClient(_Base):
    """LiteAPI /hotels/rates: bir konaklama tarihi için tüm otelleri tek istekte (40'lık parçalar) sorgular.

    Arama/rezervasyon oranı sınırı (5000:1) nedeniyle istek sayısı bilinçli olarak düşük tutulur:
    günlük tarama = ufuk günü × ceil(otel / 40) istek."""

    provider_key = "liteapi"
    name = "liteapi"
    BASE = "https://api.liteapi.travel/v3.0"
    CHUNK = 40

    def __init__(self, api_key: str, cities: dict[str, list[str]] | None = None, max_per_city: int = 40,
                 room_ladder: tuple[int, ...] = (2, 3, 5, 8), hotel_ids: list[str] | None = None, **kw):
        super().__init__(**kw)
        if not api_key:
            raise ProviderError("LITEAPI_KEY tanımlı değil")
        self.headers = {"X-API-Key": api_key, "accept": "application/json"}
        self.sandbox = api_key.startswith("sand")
        self.cities = cities or LITEAPI_DEFAULT_CITIES
        self.max_per_city = max_per_city
        # Kalan oda merdiveni: aynı oda tipinden 2, 3, 5, 8 oda istenir; teklifin kesildiği yer kalan oda alt sınırıdır.
        self.room_ladder = tuple(sorted(n for n in room_ladder if n > 1))
        # Boş değilse yalnızca bu LiteAPI otelleri taranır (ör. bir butik otel ve çevresi)
        self.hotel_ids = set(hotel_ids or [])
        self._known: list[str] = []
        self._cache: dict[date, dict[str, list[RateItem]]] = {}

    def list_hotels(self, province: str) -> list[HotelInfo]:
        out: list[HotelInfo] = []
        for city in self.cities.get(province, []):
            limit = 1000 if self.hotel_ids else self.max_per_city
            data = self._request("GET", f"{self.BASE}/data/hotels", "data/hotels", headers=self.headers,
                                 params={"countryCode": "TR", "cityName": city, "limit": limit})
            for row in data.get("data") or []:
                if row.get("deletedAt") or not row.get("id") or not row.get("name"):
                    continue
                if self.hotel_ids and row["id"] not in self.hotel_ids:
                    continue
                try:
                    lat, lng = float(row["latitude"]), float(row["longitude"])
                except (KeyError, TypeError, ValueError):
                    lat = lng = None
                try:
                    stars = int(float(row.get("stars") or 0)) or None
                except (TypeError, ValueError):
                    stars = None
                out.append(HotelInfo(
                    source_id=f"liteapi-{row['id']}", name=str(row["name"]).strip(), province=province,
                    district=str(row.get("city") or city), lat=lat, lng=lng, star_rating=stars,
                    address=row.get("address") or None, currency=str(row.get("currency") or "EUR"),
                ))
                if row["id"] not in self._known:
                    self._known.append(row["id"])
        return out

    def _rates_call(self, ids: list[str], stay_date: date, rooms: int) -> dict[str, dict]:
        data = self._request("POST", f"{self.BASE}/hotels/rates", "hotels/rates", headers=self.headers, json={
            "hotelIds": ids, "occupancies": [{"adults": 2}] * rooms, "currency": "EUR", "guestNationality": "DE",
            "checkin": stay_date.isoformat(), "checkout": (stay_date + timedelta(days=1)).isoformat(),
            "timeout": 10,
        })
        return {str(e.get("hotelId")): e for e in data.get("data") or []}

    def _fetch(self, ids: list[str], stay_date: date) -> dict[str, list[RateItem]]:
        out: dict[str, list[RateItem]] = {}
        for i in range(0, len(ids), self.CHUNK):
            chunk = ids[i:i + self.CHUNK]
            entries = self._rates_call(chunk, stay_date, 1)
            items = {hid: parse_liteapi_rates(e) for hid, e in entries.items()}
            if self.room_ladder:
                # En az 1 oda açık olan her tip için kalan oda alt sınırı; merdivende yukarı çıkıldıkça
                # yalnızca hâlâ oda veren otellere sorulur (istek sayısı düşük kalır).
                avail = {hid: {it.raw_room_name: 1 for it in its} for hid, its in items.items()}
                alive = [h for h in chunk if avail.get(h)]
                for n in self.room_ladder:
                    if not alive:
                        break
                    got = self._rates_call(alive, stay_date, n)
                    nxt = []
                    for hid in alive:
                        full = full_room_types(got[hid], n) if hid in got else set()
                        for name in full:
                            if name in avail[hid]:
                                avail[hid][name] = n
                        if full:
                            nxt.append(hid)
                    alive = nxt
                for hid, its in items.items():
                    for it in its:
                        it.available_rooms = avail[hid].get(it.raw_room_name, 1)
            out.update(items)
            for hid in chunk:
                out.setdefault(hid, [])  # teklif yok = o gece satışta değil (ya da kaynakta yok)
        return out

    def get_rates(self, hotel: HotelInfo | str, stay_date: date, observed: date) -> list[RateItem]:
        sid = hotel if isinstance(hotel, str) else hotel.source_id
        ext = sid.split("-", 1)[1] if sid.startswith("liteapi-") else sid
        if ext not in self._known:
            self._known.append(ext)
        day = self._cache.setdefault(stay_date, {})
        if ext not in day:
            missing = [h for h in self._known if h not in day]
            day.update(self._fetch(missing, stay_date))
        return day.get(ext, [])


# --------------------------------------------------------------------------- DataForSEO (Google Hotels)
GOOGLE_ROOM_NAME = "Standart oda (Google en düşük fiyat, kanal farkı düzeltilmiş)"


def _norm_name(s: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(s).lower().replace("ı", "i"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


class DataForSeoClient(_Base):
    """Google Hotels (DataForSEO Business Data). Kalan oda vermez.

    - find_hotel: otel adı + şehirle tek arama, Google otel kimliğini bulur (sonuç diskte önbelleğe alınır).
    - calendar: bir otelin önümüzdeki ~2-3 ay için gecelik EN DÜŞÜK fiyatı (tek istek)."""

    provider_key = "dataforseo"
    name = "dataforseo"
    BASE = "https://api.dataforseo.com/v3/business_data/google"

    def __init__(self, login: str, password: str, cache_path: str | None = None, **kw):
        super().__init__(**kw)
        if not (login and password):
            raise ProviderError("DATAFORSEO_LOGIN / PASSWORD tanımlı değil")
        self.auth = (login, password)
        self.cache_path = cache_path
        self._ids: dict[str, str | None] = {}
        if cache_path:
            import json
            import os

            if os.path.exists(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    self._ids = json.load(f)

    def _save(self) -> None:
        if not self.cache_path:
            return
        import json
        import os

        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._ids, f, ensure_ascii=False, indent=1)

    def _post(self, path: str, endpoint: str, task: dict) -> dict:
        data = self._request("POST", f"{self.BASE}/{path}", endpoint, auth=self.auth, json=[task])
        tasks = data.get("tasks") or []
        if data.get("status_code") != 20000 or not tasks or tasks[0].get("status_code") != 20000:
            msg = (tasks[0].get("status_message") if tasks else None) or data.get("status_message")
            raise ProviderError(f"dataforseo {endpoint}: {msg}")
        return (tasks[0].get("result") or [{}])[0] or {}

    def find_hotel(self, info: HotelInfo, check_in: date) -> str | None:
        """Ad benzerliği ≥0,8 ya da (≥0,5 ve 400 m içinde) olan ilk Google sonucu."""
        import difflib

        if info.source_id in self._ids:
            return self._ids[info.source_id]
        res = self._post("hotel_searches/live", "hotel_searches", {
            "keyword": f"{info.name} {info.district or info.province}", "location_code": 2792, "language_code": "en",
            "check_in": check_in.isoformat(), "check_out": (check_in + timedelta(days=1)).isoformat(),
            "currency": "EUR", "adults": 2, "depth": 18})
        best, best_score = None, 0.0
        for it in res.get("items") or []:
            sim = difflib.SequenceMatcher(None, _norm_name(info.name), _norm_name(it.get("title") or "")).ratio()
            loc = it.get("location") or {}
            near = False
            if info.lat is not None and loc.get("latitude") is not None:
                from app.services.compset import haversine_km

                near = haversine_km(info.lat, info.lng, float(loc["latitude"]), float(loc["longitude"])) <= 0.4
            if (sim >= 0.8 or (sim >= 0.5 and near)) and sim > best_score:
                best, best_score = it.get("hotel_identifier"), sim
        self._ids[info.source_id] = best
        self._save()
        return best

    def calendar(self, gid: str, start: date, days: int) -> dict[date, float]:
        rng = "month" if days <= 58 else "three_months"
        res = self._post("hotel_info/live/advanced", "hotel_info", {
            "hotel_identifier": gid, "location_code": 2792, "language_code": "en",
            "check_in": start.isoformat(), "check_out": (start + timedelta(days=1)).isoformat(),
            "currency": "EUR", "adults": 2, "load_prices_by_dates": True, "prices_date_range": rng})
        out: dict[date, float] = {}
        for row in (res.get("prices") or {}).get("prices_by_dates") or []:
            try:
                if str(row.get("currency") or "EUR").upper() == "EUR" and row.get("price"):
                    out[date.fromisoformat(str(row["check_in_date"])[:10])] = float(row["price"])
            except (KeyError, TypeError, ValueError):
                continue
        return out


class LiteApiWithGoogleRates:
    """LiteAPI birincil (oda tipi, vergiler dahil fiyat, kalan oda); LiteAPI'de o gece teklifi olmayan otel için
    Google'ın en düşük fiyatı kullanılır.

    Google en düşük fiyatı, LiteAPI fiyatından sistematik olarak düşüktür (vergisiz/üye fiyatları). Doğrudan karışırsa
    motor yanlış "indir" der. Bu yüzden iki kaynakta da fiyatı olan otel-gecelerinden medyan oran (LiteAPI / Google)
    hesaplanır ve Google fiyatı bu oranla düzeltilir. En az 3 eşleşen gözlem yoksa Google fiyatı KULLANILMAZ."""

    MIN_PAIRS = 3

    def __init__(self, lite: LiteApiHotelClient, google: DataForSeoClient, horizon_days: int = 60):
        self.lite, self.google = lite, google
        self.name = "liteapi+google"
        self.horizon_days = horizon_days
        self._infos: dict[str, HotelInfo] = {}
        self._cal: dict[str, dict[date, float]] = {}
        self._cal_loaded = False
        self.ratio: float | None = None

    def list_hotels(self, province: str) -> list[HotelInfo]:
        infos = self.lite.list_hotels(province)
        for i in infos:
            self._infos[i.source_id] = i
        return infos

    def _load_calendars(self, start: date) -> None:
        self._cal_loaded = True
        for sid, info in self._infos.items():
            try:
                gid = self.google.find_hotel(info, start + timedelta(days=7))
                if gid:
                    self._cal[sid] = self.google.calendar(gid, start, self.horizon_days)
            except ProviderError:
                continue  # bir otelin Google verisi alınamazsa diğerleri etkilenmez

    def _ratio(self) -> float | None:
        pairs = []
        for d, day in self.lite._cache.items():
            for hid, items in day.items():
                g = self._cal.get(f"liteapi-{hid}", {}).get(d)
                prices = [i.price for i in items if i.price]
                if g and prices:
                    pairs.append(min(prices) / g)
        if len(pairs) < self.MIN_PAIRS:
            return None
        pairs.sort()
        return pairs[len(pairs) // 2]

    def get_rates(self, hotel: HotelInfo | str, stay_date: date, observed: date) -> list[RateItem]:
        items = self.lite.get_rates(hotel, stay_date, observed)
        if items:
            return items
        sid = hotel if isinstance(hotel, str) else hotel.source_id
        if not self._cal_loaded:
            self._load_calendars(observed)
        g = self._cal.get(sid, {}).get(stay_date)
        self.ratio = self._ratio()
        if not g or self.ratio is None:
            return []
        return [RateItem(GOOGLE_ROOM_NAME, round(g * self.ratio, 2), "EUR", None)]


# --------------------------------------------------------------------------- Travelpayouts (uçuş)
class TravelpayoutsClient(_Base):
    """Uçuş talebi vekili: kaynak pazarlardan bölge havalimanlarına günlük en ucuz bilet fiyatı (Aviasales önbelleği).

    Bir rotada bir günün bileti, o rotanın ufuktaki medyanından ne kadar pahalıysa talep o kadar yüksek kabul edilir.
    Skor = 50 + 100 × (ortalama fiyat oranı − 1), 5–95 arasında. En az 2 rotada veri yoksa nötr (50).
    Arama sayısı değildir; fiyat, talebin dolaylı göstergesidir."""

    provider_key = "travelpayouts"
    name = "travelpayouts"
    URL = "https://api.travelpayouts.com/v2/prices/month-matrix"
    ROUTES = {
        "Muğla": [("IST", "BJV"), ("IST", "DLM"), ("LON", "DLM"), ("LON", "BJV"), ("MOW", "BJV"), ("BER", "DLM")],
        "Antalya": [("IST", "AYT"), ("LON", "AYT"), ("BER", "AYT"), ("MOW", "AYT"), ("AMS", "AYT")],
    }
    MIN_ROUTES = 2

    def __init__(self, token: str, **kw):
        super().__init__(**kw)
        if not token:
            raise ProviderError("TRAVELPAYOUTS_TOKEN tanımlı değil")
        self.headers = {"x-access-token": token, "Accept-Encoding": "gzip, deflate"}

    def flight_search_index(self, province: str, dates: list[date]) -> dict[date, float]:
        if not dates:
            return {}
        months = sorted({d.replace(day=1) for d in dates})
        ratios: dict[date, list[float]] = {}
        for origin, dest in self.ROUTES.get(province, []):
            fares: dict[date, float] = {}
            for m in months:
                data = self._request("GET", self.URL, "month-matrix", headers=self.headers, params={
                    "origin": origin, "destination": dest, "month": m.isoformat(), "currency": "eur",
                    "show_to_affiliates": "true"})
                for row in data.get("data") or []:
                    try:
                        fares[date.fromisoformat(str(row["depart_date"])[:10])] = float(row["value"])
                    except (KeyError, TypeError, ValueError):
                        continue
            if len(fares) < 5:
                continue  # seyrek rota: oran güvenilmez
            med = sorted(fares.values())[len(fares) // 2]
            for d, v in fares.items():
                if med > 0:
                    ratios.setdefault(d, []).append(v / med)
        out = {}
        for d in dates:
            r = ratios.get(d) or []
            out[d] = round(max(5.0, min(95.0, 50 + 100 * (sum(r) / len(r) - 1))), 1) if len(r) >= self.MIN_ROUTES else 50.0
        return out

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
            # Muğla çemberi Rodos'u (Yunanistan) da kapsıyor: yalnızca Türkiye'deki etkinlikler
            "country": "TR",
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
                # Genel önem sırası: local_rank küçük yerel maçları bile 70+ yapıp talebi şişiriyordu
                rank = ev.get("rank") if ev.get("rank") is not None else 50
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
    """Canlı modda LiteAPI anahtarı yoksa sahte veri üretmek yerine açık hata verir."""

    name = "missing"

    def list_hotels(self, province):
        raise ProviderError("LITEAPI_KEY tanımlı değil: canlı modda otel fiyat verisi çekilemez.")

    def get_rates(self, hotel, stay_date, observed):
        raise ProviderError("LITEAPI_KEY tanımlı değil: canlı modda otel fiyat verisi çekilemez.")


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
