"""Test altyapısı.

Varsayılan olarak geçici bir SQLite veritabanı kullanılır. PostgreSQL üzerinde
çalıştırmak için:  TEST_DATABASE_URL=postgresql+psycopg2://... pytest
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="otelradar-test-"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{(_tmp / 'test.db').as_posix()}")
os.environ["PASSWORD_ITERATIONS"] = "1000"
os.environ["DATA_PROVIDER"] = "demo"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["ADMIN_EMAIL"] = "admin@otelradar.local"
os.environ["ADMIN_PASSWORD"] = "Admin123!"
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import Hotel, User  # noqa: E402

HOTEL_EMAIL, HOTEL_PASSWORD = "otel@otelradar.local", "Demo1234!"
ADMIN_EMAIL, ADMIN_PASSWORD = "admin@otelradar.local", "Admin123!"
CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"|name="csrf_token" value="([^"]+)"')


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    Base.metadata.drop_all(bind=engine)
    init_db()
    from app.seed import seed_demo

    with SessionLocal() as db:
        result = seed_demo(db, scale=0.3, history_days=60, horizon=30)
    assert result.get("hotels", 0) > 10, result
    yield result
    engine.dispose()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def csrf_from(client: TestClient, url: str = "/giris") -> str:
    r = client.get(url)
    m = CSRF_RE.search(r.text)
    assert m, f"{url} sayfasında CSRF jetonu yok"
    return m.group(1) or m.group(2)


def login(client: TestClient, email: str, password: str):
    token = csrf_from(client)
    return client.post("/giris", data={"email": email, "password": password, "csrf_token": token, "next": ""},
                       follow_redirects=False)


class Browser:
    """Oturumlu istemci + CSRF jetonunu otomatik ekleyen POST yardımcısı."""

    def __init__(self, client: TestClient):
        self.client = client
        self._token: str | None = None

    def token(self) -> str:
        if self._token is None:
            self._token = csrf_from(self.client, "/fiyatlar")
        return self._token

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token())
        kw.setdefault("follow_redirects", False)
        return self.client.post(url, data=data, **kw)


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def hotel_browser():
    from app.main import app

    with TestClient(app) as c:
        r = login(c, HOTEL_EMAIL, HOTEL_PASSWORD)
        assert r.status_code == 303, r.text
        yield Browser(c)


@pytest.fixture
def admin_browser():
    from app.main import app

    with TestClient(app) as c:
        r = login(c, ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 303, r.text
        yield Browser(c)


@pytest.fixture
def demo_hotel(db) -> Hotel:
    user = db.execute(select(User).where(User.email == HOTEL_EMAIL)).scalar_one()
    return db.get(Hotel, user.hotel_id)
