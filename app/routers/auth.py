"""Giriş, çıkış, kayıt (otel eşleştirmeli) ve parola sıfırlama ekranları."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Hotel, Plan, User, utcnow
from app.security import login_limiter, password_problems, verify_password
from app.services.onboarding import complete_registration, find_candidates
from app.services.providers.demo import DISTRICTS
from app.web import audit, csrf_protect, current_user, redirect, render

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _safe_next(url: str | None, default: str) -> str:
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return default


def home_for(user: User) -> str:
    return "/admin" if user.role == "admin" else "/panel"


@router.get("/giris")
def login_page(request: Request, next: str | None = None, user: User | None = Depends(current_user)):
    if user:
        return redirect(home_for(user))
    return render(request, "public/login.html", next=next or "", email="")


@router.post("/giris", dependencies=[Depends(csrf_protect)])
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form(""),
          db: Session = Depends(get_db)):
    email = email.lower().strip()
    key = f"{request.client.host if request.client else '-'}:{email}"
    if login_limiter.is_blocked(key):
        return render(request, "public/login.html", status_code=429, next=next, email=email,
                      error="Çok fazla başarısız deneme. Lütfen 5 dakika sonra tekrar deneyin.")
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        login_limiter.register_failure(key)
        return render(request, "public/login.html", status_code=401, next=next, email=email,
                      error="E-posta veya parola hatalı.")
    login_limiter.reset(key)
    request.session.clear()
    request.session["user_id"] = user.id
    user.last_login_at = utcnow()
    audit(db, request, user, "login", "user", user.id)
    db.commit()
    return redirect(_safe_next(next, home_for(user)))


@router.post("/cikis", dependencies=[Depends(csrf_protect)])
def logout(request: Request):
    request.session.clear()
    return redirect("/giris", request, "Oturumunuz kapatıldı.", "info")


def _register_ctx(db: Session, **extra) -> dict:
    plans = list(db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)).scalars())
    districts = {p: [d["name"] for d in ds] for p, ds in DISTRICTS.items()}
    return {"plans": plans, "provinces": list(settings.pilot_provinces), "districts": districts, **extra}


@router.get("/kayit")
def register_page(request: Request, paket: str | None = None, otel: str | None = None, db: Session = Depends(get_db),
                  user: User | None = Depends(current_user)):
    if user:
        return redirect(home_for(user))
    form = request.session.get("pending_registration") or {"plan_code": paket or "profesyonel"}
    if otel and otel.strip():  # tanıtım sayfasındaki "otelinizin adı" kutusundan gelen ön doldurma
        form = {**form, "hotel_name": otel.strip()[:120]}
    return render(request, "public/register.html", form=form, errors=[], **_register_ctx(db))


@router.post("/kayit", dependencies=[Depends(csrf_protect)])
def register(
    request: Request,
    hotel_name: str = Form(...), address: str = Form(""), province: str = Form(...), district: str = Form(""),
    star_rating: str = Form(""), full_name: str = Form(...), email: str = Form(...),
    plan_code: str = Form("profesyonel"), kvkk: str = Form(""), db: Session = Depends(get_db),
):
    form = {"hotel_name": hotel_name.strip(), "address": address.strip(), "province": province, "district": district,
            "star_rating": star_rating, "full_name": full_name.strip(), "email": email.lower().strip(),
            "plan_code": plan_code}
    errors = []
    if len(form["hotel_name"]) < 3:
        errors.append("Otel adı en az 3 karakter olmalı.")
    if province not in settings.pilot_provinces:
        errors.append("Şu anda yalnızca Muğla ve Antalya bölgelerinde hizmet veriyoruz.")
    if not EMAIL_RE.match(form["email"]):
        errors.append("Geçerli bir e-posta adresi girin.")
    elif db.execute(select(User).where(User.email == form["email"])).scalar_one_or_none():
        errors.append("Bu e-posta adresiyle kayıtlı bir hesap zaten var.")
    if len(form["full_name"]) < 3:
        errors.append("Yetkili adı soyadı gerekli.")
    if not kvkk:
        errors.append("KVKK aydınlatma metnini onaylamanız gerekiyor.")
    if not db.execute(select(Plan).where(Plan.code == plan_code, Plan.is_active.is_(True))).scalar_one_or_none():
        errors.append("Geçerli bir paket seçin.")
    if errors:
        return render(request, "public/register.html", status_code=422, form=form, errors=errors, **_register_ctx(db))
    request.session["pending_registration"] = form
    # Parola çerez tabanlı oturumda tutulmaz; ikinci adımda (eşleştirme) belirlenir.
    return redirect("/kayit/eslestir")


@router.get("/kayit/eslestir")
def match_page(request: Request, db: Session = Depends(get_db)):
    form = request.session.get("pending_registration")
    if not form:
        return redirect("/kayit")
    cands = find_candidates(db, form["hotel_name"], form["province"], form.get("district") or None)
    return render(request, "public/register_match.html", form=form, candidates=cands, errors=[])


@router.post("/kayit/tamamla", dependencies=[Depends(csrf_protect)])
def complete(request: Request, hotel_choice: str = Form(...), password: str = Form(...),
             password2: str = Form(...), db: Session = Depends(get_db)):
    form = request.session.get("pending_registration")
    if not form:
        return redirect("/kayit")
    errors = password_problems(password)
    if password != password2:
        errors.append("Parolalar eşleşmiyor.")
    if db.execute(select(User).where(User.email == form["email"])).scalar_one_or_none():
        errors.append("Bu e-posta adresiyle kayıtlı bir hesap zaten var.")
    hotel_id = None
    if hotel_choice != "new":
        try:
            hotel_id = int(hotel_choice)
        except ValueError:
            errors.append("Geçersiz otel seçimi.")
        else:
            h = db.get(Hotel, hotel_id)
            if h is None or h.is_subscriber:
                errors.append("Bu otel kaydı başka bir hesaba bağlı.")
    if errors:
        cands = find_candidates(db, form["hotel_name"], form["province"], form.get("district") or None)
        return render(request, "public/register_match.html", status_code=422, form=form, candidates=cands, errors=errors)
    star = int(form["star_rating"]) if str(form.get("star_rating") or "").isdigit() else None
    user, hotel = complete_registration(
        db, full_name=form["full_name"], email=form["email"], password=password, plan_code=form["plan_code"],
        hotel_id=hotel_id, hotel_name=form["hotel_name"], address=form["address"], province=form["province"],
        district=form.get("district") or None, star_rating=star,
    )
    audit(db, request, user, "register", "hotel", hotel.id, {"plan": form["plan_code"], "matched": bool(hotel_id)})
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    return redirect("/panel/hos-geldiniz", request, "Hesabınız oluşturuldu. 14 günlük deneme süreniz başladı!")


@router.get("/sifremi-unuttum")
def forgot_page(request: Request):
    return render(request, "public/forgot.html", sent=False)


@router.post("/sifremi-unuttum", dependencies=[Depends(csrf_protect)])
def forgot(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    # E-posta gönderimi henüz bağlı değil (bkz. docs/ACIK_KONULAR.md). Hesap varlığı sızdırılmaz.
    user = db.execute(select(User).where(User.email == email.lower().strip())).scalar_one_or_none()
    if user:
        audit(db, request, user, "password_reset_requested", "user", user.id)
        db.commit()
    return render(request, "public/forgot.html", sent=True)
