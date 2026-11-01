"""Komut satırı araçları.

    python -m app.cli init-db
    python -m app.cli seed [--scale 1.0] [--history 120] [--horizon 60]
    python -m app.cli reset-demo            # tüm tabloları silip demo veriyi yeniden kurar
    python -m app.cli run-job daily_pipeline
    python -m app.cli create-admin e-posta parola "Ad Soyad"
"""
from __future__ import annotations

import argparse
import sys
import time

from sqlalchemy import select


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="OtelRadar yönetim komutları")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="Tabloları oluşturur ve temel kayıtları ekler")
    for name in ("seed", "reset-demo"):
        p = sub.add_parser(name, help="Demo veriyi kurar")
        p.add_argument("--scale", type=float, default=1.0)
        p.add_argument("--history", type=int, default=120)
        p.add_argument("--horizon", type=int, default=60)
    rj = sub.add_parser("run-job", help="Bir veri hattı işini çalıştırır")
    rj.add_argument("name")
    ca = sub.add_parser("create-admin", help="Yönetici kullanıcı oluşturur")
    ca.add_argument("email")
    ca.add_argument("password")
    ca.add_argument("full_name", nargs="?", default="Yönetici")
    args = parser.parse_args(argv)

    from app.db import Base, SessionLocal, engine, init_db
    from app.seed import ensure_base

    if args.cmd == "reset-demo":
        Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as db:
        ensure_base(db)
        if args.cmd in ("seed", "reset-demo"):
            from app.seed import seed_demo

            t = time.time()
            print("Demo veri kuruluyor…")
            res = seed_demo(db, scale=args.scale, history_days=args.history, horizon=args.horizon, verbose=True)
            print(f"Bitti ({time.time() - t:.1f} sn): {res}")
        elif args.cmd == "run-job":
            from app.services.pipeline import JOBS, run_job

            if args.name not in JOBS:
                print(f"Bilinmeyen iş. Seçenekler: {', '.join(JOBS)}")
                return 2
            run = run_job(db, args.name, trigger="manual")
            print(f"{run.status}: {run.message}")
            return 0 if run.status == "success" else 1
        elif args.cmd == "create-admin":
            from app.models import User
            from app.security import hash_password, password_problems

            probs = password_problems(args.password)
            if probs:
                print(" ".join(probs))
                return 2
            if db.execute(select(User).where(User.email == args.email.lower())).scalar_one_or_none():
                print("Bu e-posta zaten kayıtlı.")
                return 2
            db.add(User(email=args.email.lower(), password_hash=hash_password(args.password), full_name=args.full_name, role="admin"))
            db.commit()
            print("Yönetici oluşturuldu.")
        else:
            print("Veritabanı hazır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
