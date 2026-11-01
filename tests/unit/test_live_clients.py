"""Gerçek API istemcileri — ağ çağrısı yapılmadan (httpx.MockTransport) test edilir.

NOT: Makcorps/Caviar örnek yanıtları VARSAYIMSALDIR. İlk gerçek yanıt alındığında
SAMPLE_* sabitleri gerçek yanıtla değiştirilmelidir (docs/ACIK_KONULAR.md #1).
"""
from datetime import date

import httpx
import pytest

from app.services.providers import live
from app.services.providers.base import ProviderError

SAMPLE_RATES_A = {"rooms": [
    {"room_name": "Deluxe Double Room", "price": "142.50", "currency": "EUR", "rooms_left": 3},
    {"room_name": "Family Room", "price": {"amount": 210}, "available_rooms": "1"},
    {"name": ""},
]}
SAMPLE_RATES_B = [{"roomName": "Standart Oda", "pricePerNight": 4100, "currencyCode": "try"}]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(live.time, "sleep", lambda *_: None)


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_rate_variants():
    a = live.parse_rate_response(SAMPLE_RATES_A)
    assert [(i.raw_room_name, i.price, i.currency, i.available_rooms) for i in a] == [
        ("Deluxe Double Room", 142.5, "EUR", 3), ("Family Room", 210.0, "EUR", 1)]
    b = live.parse_rate_response(SAMPLE_RATES_B)
    assert b[0].currency == "TRY" and b[0].available_rooms is None
    assert live.parse_rate_response("bozuk") == []


def test_rapidapi_client_sends_headers_and_parses():
    seen = {}

    def handler(req: httpx.Request):
        seen["host"] = req.headers["X-RapidAPI-Host"]
        seen["key"] = req.headers["X-RapidAPI-Key"]
        seen["params"] = dict(req.url.params)
        return httpx.Response(200, json=SAMPLE_RATES_A)

    calls = []
    c = live.RapidApiHotelClient("KEY", "makcorps", client=mock(handler),
                                 recorder=lambda *a, **k: calls.append(a))
    items = c.get_rates("makcorps-123", date(2026, 7, 1), date(2026, 6, 1))
    assert len(items) == 2
    assert seen["key"] == "KEY" and "makcorps" in seen["host"]
    assert seen["params"]["hotelid"] == "123" and seen["params"]["checkout"] == "2026-07-02"
    assert calls and calls[0][0] == "makcorps"


def test_rapidapi_requires_key():
    with pytest.raises(ProviderError):
        live.RapidApiHotelClient("")


def test_client_error_raises_without_retry():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(401, text="unauthorized")

    c = live.RapidApiHotelClient("K", client=mock(handler), retries=2)
    with pytest.raises(ProviderError):
        c.get_rates("makcorps-1", date(2026, 7, 1), date(2026, 6, 1))
    assert n["c"] == 1


def test_server_error_is_retried():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(503) if n["c"] < 3 else httpx.Response(200, json=SAMPLE_RATES_B)

    c = live.RapidApiHotelClient("K", client=mock(handler), retries=2)
    assert len(c.get_rates("makcorps-1", date(2026, 7, 1), date(2026, 6, 1))) == 1
    assert n["c"] == 3


def test_list_hotels():
    def handler(req):
        return httpx.Response(200, json=[{"hotelId": 9, "name": "Test Otel", "geocode": {"latitude": 37.0, "longitude": 27.4}},
                                         {"name": "kimliksiz"}])

    hotels = live.RapidApiHotelClient("K", client=mock(handler)).list_hotels("Muğla")
    assert len(hotels) == 1 and hotels[0].source_id == "makcorps-9" and hotels[0].lat == 37.0


def test_amadeus_token_and_search_volume():
    hits = {"token": 0, "search": 0}

    def handler(req: httpx.Request):
        if req.url.path.endswith("/oauth2/token"):
            hits["token"] += 1
            return httpx.Response(200, json={"access_token": "T", "expires_in": 1799})
        assert req.headers["Authorization"] == "Bearer T"
        hits["search"] += 1
        return httpx.Response(200, json={"data": [{"analytics": {"searches": {"score": 60}}}]})

    c = live.AmadeusClient("id", "secret", "https://test.api.amadeus.com", client=mock(handler))
    out = c.flight_search_index("Antalya", [date(2026, 7, 1), date(2026, 7, 15), date(2026, 8, 1)])
    assert out[date(2026, 7, 1)] == 60.0 and len(out) == 3
    assert hits["token"] == 1 and hits["search"] == 2 * len(c.MARKETS)


def test_predicthq_pagination():
    def handler(req: httpx.Request):
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"results": [{"id": "b", "title": "B", "start": "2026-07-02T00:00:00Z",
                                                          "category": "sports", "local_rank": 40}], "next": None})
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


def test_fixer_rates_and_error():
    ok = live.FixerClient("F", client=mock(lambda r: httpx.Response(200, json={"success": True, "rates": {"TRY": 49.1}})))
    assert ok.rates(date(2026, 11, 1)) == {"TRY": 49.1, "EUR": 1.0}
    bad = live.FixerClient("F", client=mock(lambda r: httpx.Response(200, json={"success": False, "error": {"code": 101}})))
    with pytest.raises(ProviderError):
        bad.rates(date(2026, 11, 1))


def test_live_mode_falls_back_per_component(monkeypatch):
    from app.config import Settings
    from app.services.providers import get_providers

    cfg = Settings()
    cfg.data_provider = "live"
    cfg.rapidapi_key = "K"
    for attr in ("amadeus_client_id", "predicthq_token", "google_maps_key", "fx_api_key"):
        setattr(cfg, attr, "")
    bundle = get_providers(cfg=cfg)
    assert bundle.mode == "mixed"
    assert isinstance(bundle.rates, live.RapidApiHotelClient)
    assert bundle.fx.name == "ecb"  # anahtarsız resmi kaynak, sahte kur değil
    assert bundle.demand.flight_search_index("Muğla", [date(2026, 7, 1)]) == {date(2026, 7, 1): 50.0}
    assert bundle.demand.events("Muğla", date(2026, 7, 1), date(2026, 7, 2)) == []
    assert bundle.places.lookup("x", None, "Muğla", None).lat is None
    assert any("Amadeus" in m for m in bundle.missing)


def test_live_mode_without_rate_key_fails_loudly():
    from app.config import Settings
    from app.services.providers import get_providers

    cfg = Settings()
    cfg.data_provider = "live"
    cfg.rapidapi_key = ""
    bundle = get_providers(cfg=cfg)
    with pytest.raises(ProviderError):
        bundle.rates.list_hotels("Muğla")


def test_ecb_fx():
    xml = "<Cube currency='USD' rate='1.16'/><Cube currency='TRY' rate='49.31'/>"
    c = live.EcbFxClient(client=mock(lambda r: httpx.Response(200, text=xml)))
    assert c.rates(date(2026, 11, 1)) == {"USD": 1.16, "TRY": 49.31, "EUR": 1.0}
    bad = live.EcbFxClient(client=mock(lambda r: httpx.Response(200, text="<x/>")))
    with pytest.raises(ProviderError):
        bad.rates(date(2026, 11, 1))
