"""Oda tipi eşleme: kural sözlüğü + (yalnızca belirsiz kayıtlar için) LLM.

Doküman 5.2: Her eşleme mapped_by (rule/llm/manual) ve confidence ile saklanır;
kıyaslama yalnızca aynı kategori içinde yapılır.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
                         "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c", "â": "a"})


def normalize(text: str) -> str:
    t = text.translate(_TR_MAP).lower()
    t = re.sub(r"[^a-z0-9+ ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# (kategori, desen, güven) — sıra önemlidir: aile > süit > deluxe > standart
RULES: list[tuple[str, str, float]] = [
    ("family", r"\b(family|aile|connecting|2\+2|2\+1|cocuklu)\b", 0.95),
    ("suite", r"\b(suite|suit|suiti|junior suite|honeymoon)\b", 0.95),
    ("deluxe", r"\b(deluxe|delux|deluks|premium|executive)\b", 0.92),
    ("deluxe", r"\b(superior|sea view|deniz manzarali)\b", 0.72),
    ("standard", r"\b(standard|standart|classic|klasik|economy|ekonomik|basic)\b", 0.93),
    ("standard", r"\b(double|twin|single|cift kisilik|tek kisilik|iki kisilik)\b", 0.7),
]


@dataclass
class MappingResult:
    category: str
    mapped_by: str
    confidence: float


def map_by_rules(raw_name: str) -> MappingResult | None:
    n = normalize(raw_name)
    for cat, pattern, conf in RULES:
        if re.search(pattern, n):
            return MappingResult(cat, "rule", conf)
    return None


def map_by_llm(raw_name: str, hotel_context: str = "") -> MappingResult | None:
    """Belirsiz oda adını LLM'e sorar. Anahtar yoksa None döner (kayıt incelemeye düşer)."""
    if not settings.llm_api_key:
        return None
    prompt = (
        "Bir otel oda adını şu kategorilerden birine eşle: standard, deluxe, suite, family, other. "
        'Yalnızca JSON döndür: {"category": "...", "confidence": 0.0-1.0}. '
        f"Otel bağlamı: {hotel_context}\nOda adı: {raw_name}"
    )
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": settings.llm_model, "max_tokens": 60,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=20,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        cat = data.get("category", "other")
        if cat not in ("standard", "deluxe", "suite", "family", "other"):
            cat = "other"
        return MappingResult(cat, "llm", round(float(data.get("confidence", 0.6)), 2))
    except Exception as exc:  # noqa: BLE001 - LLM hatası eşlemeyi durdurmamalı
        log.warning("LLM oda eşleme başarısız (%s): %s", raw_name, exc)
        return None


def map_room(raw_name: str, hotel_context: str = "", use_llm: bool = True) -> MappingResult:
    res = map_by_rules(raw_name)
    if res and res.confidence >= 0.7:
        return res
    if use_llm:
        llm = map_by_llm(raw_name, hotel_context)
        if llm:
            return llm
    if res:
        return res
    # Sözlük ve LLM sonuç vermedi: 'other', düşük güven -> admin inceleme kuyruğu
    return MappingResult("other", "rule", 0.30)


REVIEW_THRESHOLD = 0.75
