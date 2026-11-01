"""Veri sağlayıcı arayüzleri. Demo üretici ve gerçek API istemcileri aynı sözleşmeyi uygular."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass
class HotelInfo:
    source_id: str
    name: str
    province: str
    district: str
    lat: float | None = None
    lng: float | None = None
    star_rating: int | None = None
    hotel_type: str | None = None
    room_count: int | None = None
    address: str | None = None
    currency: str = "EUR"
    room_names: list[str] = field(default_factory=list)


@dataclass
class RateItem:
    raw_room_name: str
    price: float | None
    currency: str
    available_rooms: int | None  # API vermiyorsa None


@dataclass
class EventInfo:
    external_id: str
    name: str
    category: str
    start_date: date
    end_date: date
    impact: int  # 0-100
    district: str | None = None


@dataclass
class PlaceInfo:
    place_id: str | None
    lat: float | None
    lng: float | None
    types: list[str] = field(default_factory=list)
    rating: float | None = None
    formatted_address: str | None = None


class UsageRecorder(Protocol):
    def __call__(self, provider: str, endpoint: str, requests: int = 1, error: bool = False) -> None: ...


class HotelRateProvider(Protocol):
    name: str

    def list_hotels(self, province: str) -> list[HotelInfo]: ...

    def get_rates(self, hotel: HotelInfo | str, stay_date: date, observed: date) -> list[RateItem]: ...


class DemandProvider(Protocol):
    name: str

    def flight_search_index(self, province: str, dates: list[date]) -> dict[date, float]: ...

    def events(self, province: str, start: date, end: date) -> list[EventInfo]: ...


class PlacesProvider(Protocol):
    name: str

    def lookup(self, name: str, address: str | None, province: str, district: str | None) -> PlaceInfo: ...


class FxProvider(Protocol):
    name: str

    def rates(self, day: date) -> dict[str, float]: ...


@dataclass
class ProviderBundle:
    rates: HotelRateProvider
    demand: DemandProvider
    places: PlacesProvider
    fx: FxProvider
    mode: str = "demo"
    missing: list[str] = field(default_factory=list)


class ProviderError(RuntimeError):
    """Harici API hatası (anahtar yok, kota, beklenmeyen yanıt)."""
