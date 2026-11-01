"""Demo (sentetik) veri sağlayıcısı.

Gerçek API anahtarları olmadan tüm uygulamanın uçtan uca çalışabilmesi için
deterministik, gerçekçi görünen veri üretir. Tüm otel adları ve etkinlikler
KURGUSALDIR; panelde "Demo veri" etiketiyle gösterilir.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta

from app.services.calendar_tr import holiday_score
from app.services.providers.base import EventInfo, HotelInfo, PlaceInfo, RateItem


def _rand(*parts) -> float:
    """[0,1) aralığında deterministik sözde rastgele sayı."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


DISTRICTS: dict[str, list[dict]] = {
    "Muğla": [
        {"name": "Bodrum", "lat": 37.0344, "lng": 27.4305, "profile": "summer", "price": 1.25, "n": 9},
        {"name": "Marmaris", "lat": 36.8550, "lng": 28.2740, "profile": "summer", "price": 0.95, "n": 7},
        {"name": "Fethiye", "lat": 36.6217, "lng": 29.1164, "profile": "long", "price": 1.0, "n": 7},
        {"name": "Datça", "lat": 36.7280, "lng": 27.6870, "profile": "summer", "price": 1.05, "n": 4},
        {"name": "Dalyan", "lat": 36.8340, "lng": 28.6420, "profile": "long", "price": 0.85, "n": 4},
        {"name": "Köyceğiz", "lat": 36.9700, "lng": 28.6870, "profile": "long", "price": 0.75, "n": 3},
    ],
    "Antalya": [
        {"name": "Lara", "lat": 36.8520, "lng": 30.7950, "profile": "antalya", "price": 1.1, "n": 6},
        {"name": "Konyaaltı", "lat": 36.8650, "lng": 30.6350, "profile": "antalya", "price": 0.95, "n": 5},
        {"name": "Kemer", "lat": 36.5980, "lng": 30.5600, "profile": "antalya", "price": 1.0, "n": 6},
        {"name": "Belek", "lat": 36.8620, "lng": 31.0550, "profile": "antalya", "price": 1.35, "n": 6},
        {"name": "Side", "lat": 36.7670, "lng": 31.3890, "profile": "antalya", "price": 1.0, "n": 5},
        {"name": "Alanya", "lat": 36.5440, "lng": 31.9990, "profile": "antalya", "price": 0.85, "n": 6},
        {"name": "Kaş", "lat": 36.2010, "lng": 29.6370, "profile": "long", "price": 1.05, "n": 4},
    ],
}

# Aylık sezon çarpanları (Ocak..Aralık)
SEASON_PROFILES = {
    "summer": [0.55, 0.55, 0.62, 0.78, 0.98, 1.32, 1.62, 1.66, 1.26, 0.86, 0.60, 0.56],
    "long": [0.62, 0.62, 0.72, 0.90, 1.06, 1.28, 1.48, 1.52, 1.28, 1.02, 0.70, 0.64],
    "antalya": [0.66, 0.66, 0.76, 0.92, 1.08, 1.26, 1.42, 1.46, 1.28, 1.08, 0.76, 0.68],
}

PREFIXES = [
    "Mavi", "Lavanta", "Zeytin", "Begonvil", "Ege", "Defne", "Kekik", "Liman", "Çınar",
    "Yakamoz", "Martı", "Sedir", "Nergis", "Palmiye", "Rüzgar", "Kumsal", "Mercan",
    "Gün Işığı", "Turkuaz", "Sakız", "Nar", "Badem", "Asmalı", "Deniz Feneri", "Kuytu",
    "Akdeniz", "Lir", "Pırlanta", "İnci", "Vadi",
]
TYPES = [
    # (tip, yıldız aralığı, ad soneki, oda sayısı aralığı, olasılık ağırlığı)
    ("pension", (2, 3), "Pansiyon", (8, 18), 0.18),
    ("boutique", (3, 4), "Butik Otel", (12, 40), 0.30),
    ("midscale", (3, 4), "Hotel", (40, 140), 0.27),
    ("resort", (4, 5), "Resort & Spa", (150, 520), 0.20),
    ("chain", (4, 5), "Suites", (90, 260), 0.05),
]
STAR_BASE_EUR = {2: 52, 3: 78, 4: 118, 5: 205}
TYPE_MULT = {"pension": 0.78, "boutique": 1.18, "midscale": 0.95, "resort": 1.28, "chain": 1.12}

ROOM_NAMES = {
    "standard": ["Standart Oda", "Standard Double Room", "Klasik Çift Kişilik", "Economy Twin", "Double Room Garden View"],
    "deluxe": ["Deluxe Deniz Manzaralı", "Superior Room Sea View", "Delüks Oda", "Deluxe Double Room"],
    "suite": ["Junior Suite", "Süit Oda", "Honeymoon Suite with Jacuzzi"],
    "family": ["Aile Odası", "Family Room (2+2)", "Connecting Family Room"],
    "other": ["Bungalow", "Garden Villa", "Penthouse Loft", "Taş Ev"],
}
CATEGORY_MULT = {"standard": 1.0, "deluxe": 1.32, "family": 1.52, "suite": 2.1, "other": 1.4}
CURRENCIES = [("EUR", 0.55), ("TRY", 0.30), ("USD", 0.10), ("GBP", 0.05)]

FX_BASE = {"EUR": 1.0, "TRY": 49.2, "USD": 1.16, "GBP": 0.865}

EVENT_TEMPLATES = {
    "Muğla": [
        ("Bodrum Caz Haftası (demo)", "concerts", "Bodrum", (7, 18), 4, 70),
        ("Ege Yelken Kupası (demo)", "sports", "Marmaris", (5, 3), 6, 55),
        ("Fethiye Yamaç Paraşütü Festivali (demo)", "festivals", "Fethiye", (10, 15), 5, 60),
        ("Datça Badem Çiçeği Festivali (demo)", "festivals", "Datça", (2, 20), 3, 40),
        ("Bodrum Kongre Haftası (demo)", "conferences", "Bodrum", (11, 12), 4, 50),
        ("Marmaris Yat Fuarı (demo)", "expos", "Marmaris", (4, 22), 4, 45),
        ("Muğla Yılbaşı Etkinlikleri (demo)", "festivals", None, (12, 30), 3, 50),
    ],
    "Antalya": [
        ("Antalya Film Haftası (demo)", "festivals", "Lara", (10, 4), 7, 65),
        ("Belek Golf Turnuvası (demo)", "sports", "Belek", (11, 6), 5, 60),
        ("Antalya Maratonu (demo)", "sports", "Konyaaltı", (3, 8), 2, 55),
        ("Alanya Triatlon (demo)", "sports", "Alanya", (10, 24), 2, 45),
        ("Kemer Müzik Festivali (demo)", "concerts", "Kemer", (8, 8), 4, 60),
        ("Antalya Turizm Fuarı (demo)", "expos", "Lara", (11, 25), 4, 55),
        ("Side Antik Tiyatro Konserleri (demo)", "concerts", "Side", (7, 25), 6, 50),
    ],
}


def season_multiplier(profile: str, d: date) -> float:
    """Aylık çarpanlar arasında gün bazında doğrusal geçiş."""
    p = SEASON_PROFILES[profile]
    m = d.month - 1
    frac = (d.day - 1) / 30.0
    nxt = (m + 1) % 12 if frac > 0.5 else m
    prv = m if frac > 0.5 else (m - 1) % 12
    w = (frac - 0.5) if frac > 0.5 else (frac + 0.5)
    return p[prv] * (1 - w) + p[nxt] * w


class DemoProvider:
    """Otel, fiyat, talep, konum ve kur verisinin tamamını üreten sağlayıcı."""

    name = "demo"

    def __init__(self, seed: str = "otelradar", scale: float = 1.0):
        self.seed = seed
        self.scale = scale  # testlerde otel sayısını küçültmek için
        self._hotels: dict[str, HotelInfo] = {}
        self._meta: dict[str, dict] = {}
        self._demand_cache: dict[tuple[str, date], float] = {}

    # ------------------------------------------------------------------ oteller
    def list_hotels(self, province: str) -> list[HotelInfo]:
        hotels: list[HotelInfo] = []
        used_names: set[str] = set()
        for dist in DISTRICTS.get(province, []):
            count = max(1, round(dist["n"] * self.scale))
            for i in range(count):
                sid = f"demo-{province[:3].lower()}-{dist['name'][:4].lower()}-{i:02d}"
                if sid in self._hotels:
                    hotels.append(self._hotels[sid])
                    continue
                r = _rand(self.seed, sid, "type")
                acc = 0.0
                chosen = TYPES[-1]
                for t in TYPES:
                    acc += t[4]
                    if r <= acc:
                        chosen = t
                        break
                htype, stars, suffix, rooms, _ = chosen
                star = stars[0] if _rand(self.seed, sid, "star") < 0.5 else stars[1]
                room_count = int(rooms[0] + _rand(self.seed, sid, "rooms") * (rooms[1] - rooms[0]))
                pi = int(_rand(self.seed, sid, "name") * len(PREFIXES))
                name = f"{PREFIXES[pi]} {dist['name']} {suffix}"
                k = 1
                while name in used_names:
                    name = f"{PREFIXES[(pi + k) % len(PREFIXES)]} {dist['name']} {suffix}"
                    k += 1
                used_names.add(name)
                ang = _rand(self.seed, sid, "ang") * 2 * math.pi
                rad = 0.004 + _rand(self.seed, sid, "rad") * 0.045  # ~0.4-5 km
                lat = dist["lat"] + rad * math.sin(ang)
                lng = dist["lng"] + rad * math.cos(ang) * 1.25
                rc = _rand(self.seed, sid, "cur")
                acc = 0.0
                currency = "EUR"
                for cur, w in CURRENCIES:
                    acc += w
                    if rc <= acc:
                        currency = cur
                        break
                cats = ["standard", "deluxe"]
                if htype in ("resort", "chain", "midscale"):
                    cats += ["family", "suite"]
                elif htype == "boutique":
                    cats += ["suite"]
                if _rand(self.seed, sid, "other") < 0.25:
                    cats.append("other")
                room_names = [
                    ROOM_NAMES[c][int(_rand(self.seed, sid, c) * len(ROOM_NAMES[c]))] for c in cats
                ]
                info = HotelInfo(
                    source_id=sid,
                    name=name,
                    province=province,
                    district=dist["name"],
                    lat=round(lat, 6),
                    lng=round(lng, 6),
                    star_rating=star,
                    hotel_type=htype,
                    room_count=room_count,
                    address=f"{dist['name']} Mah. {PREFIXES[pi]} Sk. No:{1 + int(_rand(sid, 'no') * 120)}, {dist['name']}/{province}",
                    currency=currency,
                    room_names=room_names,
                )
                self._hotels[sid] = info
                self._meta[sid] = {
                    "profile": dist["profile"],
                    "district_mult": dist["price"],
                    "quality": 0.85 + _rand(self.seed, sid, "q") * 0.35,
                    "cats": dict(zip(room_names, cats)),
                }
                hotels.append(info)
        return hotels

    def _ensure(self, sid: str) -> None:
        if sid not in self._meta:
            for prov in DISTRICTS:
                self.list_hotels(prov)
                if sid in self._meta:
                    return
            raise KeyError(f"Demo otel bulunamadı: {sid}")

    # ------------------------------------------------------------------ talep
    def demand_index(self, province: str, d: date) -> float:
        """0-100 talep endeksi (uçuş arama + etkinlik + tatil bileşimi)."""
        key = (province, d)
        if key in self._demand_cache:
            return self._demand_cache[key]
        profile = "antalya" if province == "Antalya" else "summer"
        season = season_multiplier(profile, d)
        flight = self.flight_search_index(province, [d])[d]
        ev = sum(e.impact for e in self.events(province, d, d))
        val = max(0.0, min(100.0, 0.45 * flight + 0.35 * min(ev, 100) + 0.2 * holiday_score(d) + (season - 1) * 10))
        self._demand_cache[key] = val
        return val

    def flight_search_index(self, province: str, dates: list[date]) -> dict[date, float]:
        profile = "antalya" if province == "Antalya" else "summer"
        out = {}
        for d in dates:
            # aramalar konaklamadan ~4-8 hafta önce yükselir; endeks konaklama tarihine göre
            base = 15 + (season_multiplier(profile, d) - 0.5) / 1.2 * 85
            weekly = 6 * math.sin(d.toordinal() / 7 * 2 * math.pi)
            noise = (_rand(self.seed, province, d, "fl") - 0.5) * 14
            out[d] = round(max(0.0, min(100.0, base + weekly + noise + holiday_score(d) * 0.15)), 1)
        return out

    def events(self, province: str, start: date, end: date) -> list[EventInfo]:
        out = []
        for year in range(start.year - 1, end.year + 2):
            for name, cat, district, (m, dd), length, impact in EVENT_TEMPLATES.get(province, []):
                try:
                    s = date(year, m, dd)
                except ValueError:
                    continue
                e = s + timedelta(days=length - 1)
                if e < start or s > end:
                    continue
                out.append(
                    EventInfo(
                        external_id=f"demo-{province}-{name}-{year}",
                        name=name,
                        category=cat,
                        start_date=s,
                        end_date=e,
                        impact=impact,
                        district=district,
                    )
                )
        return out

    # ------------------------------------------------------------------ fiyat
    def _true_price_eur(self, sid: str, raw_room: str, stay: date, observed: date) -> float:
        info = self._hotels[sid]
        meta = self._meta[sid]
        cat = meta["cats"].get(raw_room, "other")
        base = STAR_BASE_EUR.get(info.star_rating or 3, 80) * TYPE_MULT.get(info.hotel_type or "midscale", 1.0)
        base *= meta["district_mult"] * meta["quality"] * CATEGORY_MULT[cat]
        season = season_multiplier(meta["profile"], stay)
        weekday = 1.10 if stay.weekday() in (4, 5) else (0.97 if stay.weekday() in (0, 1) else 1.0)
        demand = self.demand_index(info.province, stay)
        lead = max(0, (stay - observed).days)
        # Yüksek talepte konaklamaya yaklaştıkça fiyat artar, düşük talepte son dakika indirimi
        lead_effect = (demand - 45) / 100 * 0.18 * math.exp(-lead / 18)
        weekly_noise = (_rand(self.seed, sid, stay, observed.isocalendar()[1]) - 0.5) * 0.06
        price = base * season * weekday * (1 + (demand - 50) / 400) * (1 + lead_effect + weekly_noise)
        return max(25.0, price)

    def get_rates(self, hotel: HotelInfo | str, stay_date: date, observed: date) -> list[RateItem]:
        sid = hotel if isinstance(hotel, str) else hotel.source_id
        self._ensure(sid)
        info = self._hotels[sid]
        meta = self._meta[sid]
        fx = self.rates(observed)
        items = []
        n_types = len(info.room_names)
        for raw in info.room_names:
            cat = meta["cats"].get(raw, "other")
            share = {"standard": 0.45, "deluxe": 0.3, "family": 0.15, "suite": 0.06, "other": 0.1}[cat]
            inventory = max(2, round((info.room_count or 20) * share * (3 / max(n_types, 3))))
            demand = self.demand_index(info.province, stay_date)
            season = season_multiplier(meta["profile"], stay_date)
            occ_target = max(0.15, min(0.98, 0.25 + 0.38 * season + (demand - 50) / 160))
            lead = max(0, (stay_date - observed).days)
            sold_frac = occ_target * (1 - min(lead, 75) / 75) ** 0.8
            sold_frac += (_rand(self.seed, sid, raw, stay_date, "sold") - 0.5) * 0.1
            available = max(0, round(inventory * (1 - max(0.0, min(1.0, sold_frac)))))
            # Arada bir oda kapatma (stop-sell) - satış değil!
            if _rand(self.seed, sid, raw, stay_date, observed, "close") < 0.02:
                available = 0
            price_eur = self._true_price_eur(sid, raw, stay_date, observed)
            if available == 0:
                items.append(RateItem(raw, None, info.currency, 0))
                continue
            items.append(RateItem(raw, round(price_eur * fx[info.currency], 2), info.currency, available))
        return items

    # ------------------------------------------------------------------ konum / kur
    def lookup(self, name: str, address: str | None, province: str, district: str | None) -> PlaceInfo:
        dists = DISTRICTS.get(province, [])
        dist = next((d for d in dists if district and d["name"].lower() == district.lower()), dists[0] if dists else None)
        if not dist:
            return PlaceInfo(None, None, None)
        ang = _rand(self.seed, name, "pang") * 2 * math.pi
        rad = 0.003 + _rand(self.seed, name, "prad") * 0.02
        return PlaceInfo(
            place_id=f"demo-place-{hashlib.md5(name.encode()).hexdigest()[:10]}",
            lat=round(dist["lat"] + rad * math.sin(ang), 6),
            lng=round(dist["lng"] + rad * math.cos(ang), 6),
            types=["lodging"],
            rating=round(3.8 + _rand(name, "rating") * 1.1, 1),
            formatted_address=address,
        )

    def rates(self, day: date) -> dict[str, float]:
        # TRY'de hafif enflasyonist kayma (günlük ~%0.05)
        drift = 1 + (day - date(2026, 11, 1)).days * 0.0005
        return {
            "EUR": 1.0,
            "TRY": round(FX_BASE["TRY"] * drift, 4),
            "USD": round(FX_BASE["USD"] * (1 + (_rand("usd", day) - 0.5) * 0.01), 4),
            "GBP": round(FX_BASE["GBP"] * (1 + (_rand("gbp", day) - 0.5) * 0.01), 4),
        }
