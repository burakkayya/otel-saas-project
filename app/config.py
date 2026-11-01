"""Uygulama ayarları. Tüm değerler ortam değişkenlerinden (.env) okunur."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Basit .env okuyucu (ek bağımlılık gerektirmez). Var olan ortam değişkenlerini ezmez."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "evet"}


@dataclass
class Settings:
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "OtelRadar"))
    timezone: str = field(default_factory=lambda: os.getenv("APP_TZ", "Europe/Istanbul"))
    environment: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "dev-secret-change-me"))
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}"
        )
    )
    # 'demo' = sentetik veri üreticisi, 'live' = gerçek API istemcileri
    data_provider: str = field(default_factory=lambda: os.getenv("DATA_PROVIDER", "demo"))
    password_iterations: int = field(default_factory=lambda: int(os.getenv("PASSWORD_ITERATIONS", "200000")))
    session_max_age: int = 60 * 60 * 12
    scheduler_enabled: bool = field(default_factory=lambda: _bool("SCHEDULER_ENABLED", False))
    secure_cookies: bool = field(default_factory=lambda: _bool("SECURE_COOKIES", False))

    # Pilot bölgeler
    pilot_provinces: tuple[str, ...] = ("Muğla", "Antalya")

    # Tarama ufku (kaç gün ileriye fiyat çekilecek)
    horizon_days: int = field(default_factory=lambda: int(os.getenv("HORIZON_DAYS", "60")))
    compset_size: int = 5

    # Harici API anahtarları
    rapidapi_key: str = field(default_factory=lambda: os.getenv("RAPIDAPI_KEY", ""))
    rapidapi_hotel_provider: str = field(default_factory=lambda: os.getenv("RAPIDAPI_HOTEL_PROVIDER", "makcorps"))
    rapidapi_host: str = field(default_factory=lambda: os.getenv("RAPIDAPI_HOST", ""))
    amadeus_client_id: str = field(default_factory=lambda: os.getenv("AMADEUS_CLIENT_ID", ""))
    amadeus_client_secret: str = field(default_factory=lambda: os.getenv("AMADEUS_CLIENT_SECRET", ""))
    amadeus_base_url: str = field(default_factory=lambda: os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com"))
    predicthq_token: str = field(default_factory=lambda: os.getenv("PREDICTHQ_TOKEN", ""))
    google_maps_key: str = field(default_factory=lambda: os.getenv("GOOGLE_MAPS_KEY", ""))
    fx_api_key: str = field(default_factory=lambda: os.getenv("FX_API_KEY", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-haiku-5-5"))

    # İlk kurulum yöneticisi
    admin_email: str = field(default_factory=lambda: os.getenv("ADMIN_EMAIL", "admin@otelradar.local"))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", "Admin123!"))

    @property
    def is_demo(self) -> bool:
        return self.data_provider != "live"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def configured_keys(self) -> dict[str, bool]:
        return {
            "RapidAPI (Makcorps/Caviar)": bool(self.rapidapi_key),
            "Amadeus": bool(self.amadeus_client_id and self.amadeus_client_secret),
            "PredictHQ": bool(self.predicthq_token),
            "Google Places": bool(self.google_maps_key),
            "Fixer / ExchangeRates": bool(self.fx_api_key),
            "LLM (oda eşleme)": bool(self.llm_api_key),
        }


settings = Settings()
