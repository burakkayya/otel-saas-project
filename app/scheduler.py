"""APScheduler ile zamanlanmış işler (SCHEDULER_ENABLED=true iken uygulama içinde çalışır).

Docker Compose'da ayrı bir 'worker' servisi bu modülü `python -m app.scheduler` ile çalıştırır;
böylece web sunucusu birden fazla süreçle ölçeklense bile işler bir kez çalışır.
"""
from __future__ import annotations

import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler, BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal, init_db
from app.services.pipeline import run_job

log = logging.getLogger(__name__)
TZ = "Europe/Istanbul"

SCHEDULE = [
    ("daily_pipeline", CronTrigger(hour=5, minute=30, timezone=TZ)),
    ("demand_refresh", CronTrigger(hour="*/6", minute=10, timezone=TZ)),
    ("uptake", CronTrigger(hour=14, minute=0, timezone=TZ)),
    ("roi_did", CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=TZ)),
    ("backtest", CronTrigger(day_of_week="mon", hour=7, minute=30, timezone=TZ)),
]

SCHEDULE_LABELS = {
    "daily_pipeline": "Her gün 05:30",
    "demand_refresh": "6 saatte bir",
    "uptake": "Her gün 14:00",
    "roi_did": "Pazartesi 07:00",
    "backtest": "Pazartesi 07:30",
}


def _run(name: str) -> None:
    with SessionLocal() as db:
        run = run_job(db, name, trigger="schedule")
        log.info("İş %s: %s (%s)", name, run.status, run.message)


def _configure(s):
    for name, trig in SCHEDULE:
        s.add_job(_run, trig, args=[name], id=name, replace_existing=True, max_instances=1, coalesce=True)
    return s


def start_scheduler() -> BackgroundScheduler:
    s = _configure(BackgroundScheduler(timezone=TZ))
    s.start()
    return s


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    for _ in range(30):
        try:
            init_db()
            break
        except Exception:  # noqa: BLE001 - veritabanı henüz hazır değil
            time.sleep(2)
    _configure(BlockingScheduler(timezone=TZ)).start()
