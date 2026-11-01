"""Türkiye resmi tatilleri ve okul tatili dönemleri.

NOT: Dini bayram tarihleri (Ramazan/Kurban) Diyanet takvimine göre her yıl değişir.
Aşağıdaki 2026-2027 tarihleri yaklaşık değerlerdir; canlıya almadan önce resmi
takvimle doğrulanmalıdır (bkz. docs/ACIK_KONULAR.md).
"""
from __future__ import annotations

from datetime import date, timedelta


def _span(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


FIXED = {
    (1, 1): "Yılbaşı",
    (4, 23): "Ulusal Egemenlik ve Çocuk Bayramı",
    (5, 1): "Emek ve Dayanışma Günü",
    (5, 19): "Atatürk'ü Anma, Gençlik ve Spor Bayramı",
    (7, 15): "Demokrasi ve Milli Birlik Günü",
    (8, 30): "Zafer Bayramı",
    (10, 29): "Cumhuriyet Bayramı",
}

# Yaklaşık dini bayramlar (arife dahil değil)
RELIGIOUS: dict[date, str] = {}
for d in _span(date(2025, 3, 30), 3):
    RELIGIOUS[d] = "Ramazan Bayramı"
for d in _span(date(2025, 6, 6), 4):
    RELIGIOUS[d] = "Kurban Bayramı"
for d in _span(date(2026, 3, 20), 3):
    RELIGIOUS[d] = "Ramazan Bayramı"
for d in _span(date(2026, 5, 27), 4):
    RELIGIOUS[d] = "Kurban Bayramı"
for d in _span(date(2027, 3, 9), 3):
    RELIGIOUS[d] = "Ramazan Bayramı"
for d in _span(date(2027, 5, 16), 4):
    RELIGIOUS[d] = "Kurban Bayramı"

# Yaklaşık okul tatilleri (yaz + yarıyıl)
SCHOOL_BREAKS = [
    (date(2025, 6, 28), date(2025, 9, 7)),
    (date(2026, 1, 17), date(2026, 2, 1)),
    (date(2026, 6, 27), date(2026, 9, 6)),
    (date(2027, 1, 23), date(2027, 2, 7)),
    (date(2027, 6, 26), date(2027, 9, 12)),
]


def holiday_name(d: date) -> str | None:
    if (d.month, d.day) in FIXED:
        return FIXED[(d.month, d.day)]
    return RELIGIOUS.get(d)


def is_school_break(d: date) -> bool:
    return any(a <= d <= b for a, b in SCHOOL_BREAKS)


def holiday_score(d: date) -> float:
    """0-100 arası tatil skoru: resmi/dini tatil, köprü etkisi, okul tatili, hafta sonu."""
    score = 0.0
    name = holiday_name(d)
    if name:
        score += 70 if name in ("Ramazan Bayramı", "Kurban Bayramı") else 45
    else:
        # bayrama komşu günler (uzatılmış tatil etkisi)
        for delta in (-2, -1, 1, 2):
            n = holiday_name(d + timedelta(days=delta))
            if n in ("Ramazan Bayramı", "Kurban Bayramı"):
                score += 35 if abs(delta) == 1 else 20
                break
    if is_school_break(d):
        score += 20
    if d.weekday() in (4, 5):
        score += 15
    return min(score, 100.0)


def holidays_between(start: date, end: date) -> list[tuple[date, str]]:
    out = []
    d = start
    while d <= end:
        n = holiday_name(d)
        if n:
            out.append((d, n))
        d += timedelta(days=1)
    return out
