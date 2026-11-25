"""Gerçek API istemcileri: ağ çağrısı yapılmadan (httpx.MockTransport) test edilir.

Örnek yanıtlar 24-25 Kasım 2026'da gerçek isteklerle alınan yanıtların kısaltılmış biçimidir.
LiteAPI testleri: tests/unit/test_liteapi_client.py.
"""
from datetime import date

import httpx
import pytest

from app.services.providers import live
from app.services.providers.base import HotelInfo, ProviderError, RateItem


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(live.time, "sleep", lambda *_: None)


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- ortak istek davranışı
def test_client_error_raises_without_retry():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(401, text="unauthorized")

    c = live.PredictHQClient("T", client=mock(handler), retries=2)
    with pytest.raises(ProviderError):
        c.events("Muğla", date(2026, 7, 1), date(2026, 7, 2))
    assert n["c"] == 1


def test_server_error_is_retried():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(503) if n["c"] < 3 else httpx.Response(200, json={"results": [], "next": None})

    c = live.PredictHQClient("T", client=mock(handler), retries=2)
    assert c.events("Muğla", date(2026, 7, 1), date(2026, 7, 2)) == []
    assert n["c"] == 3


# ---------------------------------------------------------------- Travelpayouts
def _matrix(prices: dict[str, float]):
    return {"success": True, "data": [{"depart_date": d, "value": v} for d, v in prices.items()]}


def test_travelpayouts_fare_index():
    base = {f"2026-12-{d:02d}": 100.0 for d in range(1, 11)}
    seen = []

    def handler(req):
        seen.append((req.url.params["origin"], req.url.params["destination"], req.url.params["month"]))
        assert req.headers["x-access-token"] == "TP"
        prices = dict(base)
        prices["2026-12-05"] = 130.0  # o gün bilet %30 pahalı -> talep yüksek
        return httpx.Response(200, json=_matrix(prices))

    c = live.TravelpayoutsClient("TP", client=mock(handler))
    out = c.flight_search_index("Muğla", [date(2026, 12, 4), date(2026, 12, 5), date(2026, 12, 20)])
    assert out[date(2026, 12, 4)] == 50.0 and out[date(2026, 12, 5)] == 80.0
    assert out[date(2026, 12, 20)] == 50.0  # veri yok -> nötr
    assert len(seen) == len(c.ROUTES["Muğla"]) and seen[0][2] == "2026-12-01"


def test_travelpayouts_sparse_routes_stay_neutral():
    c = live.TravelpayoutsClient("TP", client=mock(lambda r: httpx.Response(200, json=_matrix({"2026-12-05": 300.0}))))
    assert c.flight_search_index("Muğla", [date(2026, 12, 5)]) == {date(2026, 12, 5): 50.0}
    with pytest.raises(ProviderError):
        live.TravelpayoutsClient("")


# ---------------------------------------------------------------- DataForSEO
SEARCH = {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"items": [
    {"hotel_identifier": "G-other", "title": "Başka Otel", "location": {"latitude": 37.2, "longitude": 27.6}},
    {"hotel_identifier": "G-dinc", "title": "Dinç Pansiyon", "location": {"latitude": 37.0345, "longitude": 27.4302}},
]}]}]}
CALENDAR = {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"prices": {"prices_by_dates": [
    {"price": 58, "currency": "EUR", "check_in_date": "2026-12-05 00:00:00 +00:00"},
    {"price": 70, "currency": "EUR", "check_in_date": "2026-12-06 00:00:00 +00:00"},
]}}]}]}


def _dfs_handler(calls):
    def handler(req):
        calls.append(req.url.path)
        assert req.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json=SEARCH if "hotel_searches" in req.url.path else CALENDAR)
    return handler


def test_dataforseo_find_hotel_and_calendar(tmp_path):
    calls = []
    cache = tmp_path / "ids.json"
    c = live.DataForSeoClient("L", "P", cache_path=str(cache), client=mock(_dfs_handler(calls)))
    info = HotelInfo("liteapi-lpaeb3e", "Dinc Pansiyon", "Muğla", "Bodrum", lat=37.0344, lng=27.4300)
    assert c.find_hotel(info, date(2026, 12, 5)) == "G-dinc"
    assert c.find_hotel(info, date(2026, 12, 5)) == "G-dinc" and len(calls) == 1  # önbellekten
    # Diskteki önbellek yeni süreçte de kullanılır
    c2 = live.DataForSeoClient("L", "P", cache_path=str(cache), client=mock(_dfs_handler(calls)))
    assert c2.find_hotel(info, date(2026, 12, 5)) == "G-dinc" and len(calls) == 1
    assert c.calendar("G-dinc", date(2026, 12, 5), 21) == {date(2026, 12, 5): 58.0, date(2026, 12, 6): 70.0}


def test_dataforseo_task_error_is_reported():
    bad = {"status_code": 20000, "tasks": [{"status_code": 40104, "status_message": "Please verify your account"}]}
    c = live.DataForSeoClient("L", "P", client=mock(lambda r: httpx.Response(200, json=bad)))
    with pytest.raises(ProviderError, match="verify"):
        c.calendar("G", date(2026, 12, 5), 21)
    with pytest.raises(ProviderError):
        live.DataForSeoClient("", "")


class _FakeLite:
    """LiteAPI vekili: önbellek yapısı gerçek istemciyle aynı."""

    def __init__(self, day_items):
        self._cache = {date(2026, 12, 5): day_items}

    def list_hotels(self, province):
        return [HotelInfo(f"liteapi-{h}", h, province, "Bodrum") for h in self._cache[date(2026, 12, 5)]]

    def get_rates(self, hotel, stay_date, observed):
        sid = hotel if isinstance(hotel, str) else hotel.source_id
        return self._cache.get(stay_date, {}).get(sid.split("-", 1)[1], [])


class _FakeGoogle:
    def __init__(self, prices):
        self.prices = prices

    def find_hotel(self, info, check_in):
        return info.source_id

    def calendar(self, gid, start, days):
        p = self.prices.get(gid)
        return {date(2026, 12, 5): p} if p else {}


def test_google_fallback_is_calibrated_to_liteapi_level():
    lite = _FakeLite({"a": [RateItem("Std", 100.0, "EUR", 2)], "b": [RateItem("Std", 120.0, "EUR", 1)],
                      "c": [RateItem("Std", 90.0, "EUR", 3)], "x": []})
    google = _FakeGoogle({"liteapi-a": 60.0, "liteapi-b": 80.0, "liteapi-c": 60.0, "liteapi-x": 50.0})
    comp = live.LiteApiWithGoogleRates(lite, google, 21)
    comp.list_hotels("Muğla")
    assert comp.get_rates("liteapi-a", date(2026, 12, 5), date(2026, 11, 25))[0].price == 100.0  # LiteAPI önce
    got = comp.get_rates("liteapi-x", date(2026, 12, 5), date(2026, 11, 25))
    # oranlar 1,667 / 1,5 / 1,5 -> medyan 1,5; Google €50 -> €75, kalan oda bilinmiyor
    assert [(i.raw_room_name, i.price, i.available_rooms) for i in got] == [(live.GOOGLE_ROOM_NAME, 75.0, None)]
    assert comp.ratio == 1.5


def test_google_fallback_not_used_without_enough_pairs():
    lite = _FakeLite({"a": [RateItem("Std", 100.0, "EUR", 2)], "x": []})
    comp = live.LiteApiWithGoogleRates(lite, _FakeGoogle({"liteapi-a": 60.0, "liteapi-x": 50.0}), 21)
    comp.list_hotels("Muğla")
    assert comp.get_rates("liteapi-x", date(2026, 12, 5), date(2026, 11, 25)) == []


# ---------------------------------------------------------------- PredictHQ, Places, ECB
def test_predicthq_pagination():
    def handler(req: httpx.Request):
        if "page=2" not in str(req.url):
            assert req.url.params["country"] == "TR"  # Rodos (Yunanistan) etkinlikleri gelmesin
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"results": [{"id": "b", "title": "B", "start": "2026-07-02T00:00:00Z",
                                                          "category": "sports", "rank": 40, "local_rank": 90}], "next": None})
        return httpx.Response(200, json={"results": [{"id": "a", "title": "A", "start": "2026-07-01T00:00:00Z",
                                                      "end": "2026-07-03T00:00:00Z", "category": "concerts", "rank": 80}],
                                         "next": "https://api.predicthq.com/v1/events/?page=2"})

    evs = live.PredictHQClient("tok", client=mock(handler)).events("Muğla", date(2026, 7, 1), date(2026, 7, 31))
    assert [(e.name, e.impact) for e in evs] == [("A", 80), ("B", 40)]
    assert evs[0].end_date == date(2026, 7, 3)


def test_google_places():
    def handler(req: httpx.Request):
        assert req.headers["X-Goog-Api-Key"] == "G"
        return httpx.Response(200, json={"places": [{"id": "p1", "location": {"latitude": 36.8, "longitude": 30.7},
                                                     "types": ["lodging"], "rating": 4.5}]})

    p = live.GooglePlacesClient("G", client=mock(handler)).lookup("Otel", None, "Antalya", "Lara")
    assert (p.place_id, p.lat, p.lng) == ("p1", 36.8, 30.7)


def test_ecb_fx():
    xml = "<Cube currency='USD' rate='1.16'/><Cube currency='TRY' rate='49.31'/>"
    c = live.EcbFxClient(client=mock(lambda r: httpx.Response(200, text=xml)))
    assert c.rates(date(2026, 11, 1)) == {"USD": 1.16, "TRY": 49.31, "EUR": 1.0}
    bad = live.EcbFxClient(client=mock(lambda r: httpx.Response(200, text="<x/>")))
    with pytest.raises(ProviderError):
        bad.rates(date(2026, 11, 1))


# ---------------------------------------------------------------- sağlayıcı fabrikası
def _live_cfg(**keys):
    from app.config import Settings

    cfg = Settings()
    cfg.data_provider = "live"
    for attr in ("liteapi_key", "dataforseo_login", "dataforseo_password", "travelpayouts_token",
                 "predicthq_token", "google_maps_key"):
        setattr(cfg, attr, "")
    for k, v in keys.items():
        setattr(cfg, k, v)
    return cfg


def test_live_mode_falls_back_per_component():
    from app.services.providers import get_providers

    bundle = get_providers(cfg=_live_cfg(liteapi_key="sand_x"))
    assert bundle.mode == "mixed"
    assert isinstance(bundle.rates, live.LiteApiHotelClient)  # DataForSEO yoksa yalnızca LiteAPI
    assert bundle.fx.name == "ecb"  # anahtarsız resmi kaynak, sahte kur değil
    assert bundle.demand.flight_search_index("Muğla", [date(2026, 7, 1)]) == {date(2026, 7, 1): 50.0}
    assert bundle.demand.events("Muğla", date(2026, 7, 1), date(2026, 7, 2)) == []
    assert bundle.places.lookup("x", None, "Muğla", None).lat is None
    assert any("Travelpayouts" in m for m in bundle.missing)
    assert any("DataForSEO" in m for m in bundle.missing)


def test_live_mode_full_bundle():
    from app.services.providers import get_providers

    bundle = get_providers(cfg=_live_cfg(liteapi_key="sand_x", dataforseo_login="L", dataforseo_password="P",
                                         travelpayouts_token="T", predicthq_token="P", google_maps_key="G"))
    assert bundle.mode == "live" and not bundle.missing
    assert isinstance(bundle.rates, live.LiteApiWithGoogleRates)


def test_live_mode_without_rate_key_fails_loudly():
    from app.services.providers import get_providers

    bundle = get_providers(cfg=_live_cfg())
    with pytest.raises(ProviderError):
        bundle.rates.list_hotels("Muğla")
