"""LiteAPI istemcisi: ağ çağrısı yapılmadan (httpx.MockTransport).

Örnek yanıtlar 24 Kasım 2026'da sandbox anahtarıyla alınan gerçek yanıtların kısaltılmış biçimidir."""
import json
from datetime import date

import httpx
import pytest

from app.services.providers import live
from app.services.providers.base import ProviderError

HOTELS = {"data": [
    {"id": "lp4b30f", "name": "Rixos Premium Bodrum", "city": "Bodrum", "latitude": "37.094913",
     "longitude": "27.492756", "stars": "5", "address": "Torba mah.", "currency": "EUR", "deletedAt": None},
    {"id": "lp31938", "name": "DoubleTree Işıl Club", "city": "Bodrum", "latitude": None, "longitude": None,
     "stars": "0", "deletedAt": None},
    {"id": "lpdead", "name": "Silinmiş", "deletedAt": "2026-01-01"},
], "total": 3}


def _rate(name, amount, occ=1):
    return {"name": name, "occupancyNumber": occ, "boardType": "BI",
            "retailRate": {"total": [{"amount": amount, "currency": "EUR"}]}}


RATES = {"data": [{"hotelId": "lp4b30f", "roomTypes": [
    {"rates": [_rate("DELUXE ROOM SEA VIEW ", 115.38)]},
    {"rates": [_rate("DELUXE ROOM  SEA VIEW", 112.0)]},
    {"rates": [_rate("Run of House", 114.08), _rate("Run of House", 99.0, occ=2)]},
]}], "sandbox": True}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(live.time, "sleep", lambda *_: None)


def make(handler, **kw):
    kw.setdefault("room_ladder", ())
    return live.LiteApiHotelClient("sand_test", {"Muğla": ["Bodrum"]}, client=httpx.Client(
        transport=httpx.MockTransport(handler)), **kw)


def test_parse_city_map():
    assert live.parse_city_map("Muğla:Bodrum, Marmaris;Antalya:Kemer") == {
        "Muğla": ["Bodrum", "Marmaris"], "Antalya": ["Kemer"]}
    assert live.parse_city_map("") == {}


def test_parse_rates_cheapest_per_room_name_first_room_only():
    items = live.parse_liteapi_rates(RATES["data"][0])
    got = {i.raw_room_name: i.price for i in items}
    assert got == {"DELUXE ROOM SEA VIEW": 112.0, "Run of House": 114.08}
    assert all(i.available_rooms is None and i.currency == "EUR" for i in items)


def test_clean_room_name_drops_board_and_refund_parts():
    assert live.clean_room_name("Studio Oda - Bed & breakfast - İade Edilemez") == "Studio Oda"
    assert live.clean_room_name("1+1 Lux Oda - Half board/modified American plan - İade Edilebilir") == "1+1 Lux Oda"
    assert live.clean_room_name("Room - Garden view") == "Room - Garden view"
    assert live.clean_room_name("  Deluxe   Room ") == "Deluxe Room"


def test_list_hotels_maps_fields_and_skips_deleted():
    seen = {}

    def handler(req):
        seen["key"] = req.headers.get("X-API-Key")
        seen["params"] = dict(req.url.params)
        return httpx.Response(200, json=HOTELS)

    c = make(handler)
    hotels = c.list_hotels("Muğla")
    assert seen["key"] == "sand_test" and seen["params"]["cityName"] == "Bodrum"
    assert [h.source_id for h in hotels] == ["liteapi-lp4b30f", "liteapi-lp31938"]
    assert hotels[0].lat == pytest.approx(37.094913) and hotels[0].star_rating == 5
    assert hotels[1].lat is None and hotels[1].star_rating is None
    assert c.list_hotels("Antalya") == []  # haritada yok -> istek yok


def test_get_rates_batches_one_request_per_date():
    calls = []

    def handler(req):
        if req.url.path.endswith("/data/hotels"):
            return httpx.Response(200, json=HOTELS)
        body = json.loads(req.content)
        calls.append(body)
        return httpx.Response(200, json=RATES)

    c = make(handler)
    c.list_hotels("Muğla")
    d = date(2026, 12, 8)
    a = c.get_rates("liteapi-lp4b30f", d, date(2026, 11, 24))
    b = c.get_rates("liteapi-lp31938", d, date(2026, 11, 24))
    assert len(calls) == 1 and calls[0]["hotelIds"] == ["lp4b30f", "lp31938"]
    assert calls[0]["checkout"] == "2026-12-09" and calls[0]["occupancies"] == [{"adults": 2}]
    assert len(a) == 2 and b == []  # teklif dönmeyen otel boş liste


def test_get_rates_chunks_large_hotel_lists():
    calls = []

    def handler(req):
        calls.append(json.loads(req.content)["hotelIds"])
        return httpx.Response(200, json={"data": []})

    c = make(handler)
    c._known = [f"h{i}" for i in range(85)]
    c.get_rates("liteapi-h0", date(2026, 12, 8), date(2026, 11, 24))
    assert [len(x) for x in calls] == [40, 40, 5]


def test_requires_key_and_reports_http_errors():
    with pytest.raises(ProviderError):
        live.LiteApiHotelClient("")
    c = make(lambda req: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(ProviderError):
        c.list_hotels("Muğla")



def _offer(name, n, amount=100.0):
    return {"rates": [{"name": name, "occupancyNumber": i, "retailRate": {"total": [{"amount": amount}]}}
                      for i in range(1, n + 1)]}


def test_full_room_types_requires_all_rooms_same_type():
    entry = {"roomTypes": [_offer("Economy", 3), _offer("Deluxe", 2),
                           {"rates": [{"name": "Economy", "occupancyNumber": 1}, {"name": "Deluxe", "occupancyNumber": 2},
                                      {"name": "Deluxe", "occupancyNumber": 3}]}]}
    assert live.full_room_types(entry, 3) == {"Economy"}


def test_room_ladder_gives_remaining_rooms_lower_bound():
    """Gerçek gözlem (Dinc Pansiyon, 5 Ara 2026): 2 odada 2 tip, 3 odada yalnızca Economy, 5 odada hiç."""
    calls = []

    def handler(req):
        body = json.loads(req.content)
        n = len(body["occupancies"])
        calls.append((n, body["hotelIds"]))
        offers = {1: [_offer("Economy", 1, 98), _offer("Deluxe", 1, 126), _offer("Triple", 1, 153)],
                  2: [_offer("Economy", 2), _offer("Deluxe", 2)],
                  3: [_offer("Economy", 3)]}.get(n, [])
        data = [{"hotelId": "lpaeb3e", "roomTypes": offers}] if offers else []
        return httpx.Response(200, json={"data": data})

    c = make(handler, room_ladder=(2, 3, 5, 8))
    c._known = ["lpaeb3e", "lpbos"]
    got = {i.raw_room_name: i.available_rooms for i in c.get_rates("liteapi-lpaeb3e", date(2026, 12, 5), date(2026, 11, 25))}
    assert got == {"Economy": 3, "Deluxe": 2, "Triple": 1}
    # 8'e sorulmaz: 5 odada kimse kalmadı; teklifsiz otel merdivene hiç girmez
    assert [n for n, _ in calls] == [1, 2, 3, 5]
    assert all(ids == ["lpaeb3e"] for n, ids in calls if n > 1)
