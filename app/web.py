"""Web katmanı yardımcıları: şablon motoru, biçimlendiriciler, oturum, yetki ve CSRF."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import AuditLog, Hotel, Notification, User
from app.security import csrf_valid, get_csrf_token

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
MONTHS_LONG = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


# ----------------------------------------------------------------------------- biçimlendirme
def fmt_number(value: Any, digits: int = 0) -> str:
    if value is None or value == "":
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    s = f"{v:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_eur(value: Any, digits: int = 0) -> str:
    if value is None:
        return "—"
    v = float(value)
    return f"−€{fmt_number(abs(v), digits)}" if v < 0 and round(abs(v), digits) > 0 else f"€{fmt_number(abs(v), digits)}"


def fmt_pct(value: Any, digits: int = 1, sign: bool = False) -> str:
    if value is None:
        return "—"
    v = float(value)
    prefix = "+" if sign and v > 0 else ("−" if v < 0 else "")
    return f"{prefix}\u2060%\u2060{fmt_number(abs(v), digits)}"


def fmt_signed(value: Any, digits: int = 1) -> str:
    """İşaretli sayı: +2,0 / −5,7; yuvarlanınca sıfır olan değer işaretsiz yazılır."""
    if value is None:
        return "—"
    v = float(value)
    if round(abs(v), digits) == 0:
        return fmt_number(0, digits)
    return ("+" if v > 0 else "−") + fmt_number(abs(v), digits)


AUDIT_LABELS = {
    "login": "Giriş", "register": "Kayıt", "password_changed": "Parola değiştirildi",
    "password_reset_requested": "Parola sıfırlama talebi", "password_reset_by_admin": "Parola yönetici tarafından sıfırlandı",
    "impersonate_hotel": "Yönetici otel paneline baktı", "hotel_updated": "Otel güncellendi", "settings_updated": "Fiyat kuralları güncellendi",
    "competitor_added": "Rakip eklendi", "competitor_removed": "Rakip çıkarıldı", "competitor_confirmed": "Rakip onaylandı",
    "competitor_rejected": "Rakip reddedildi", "compliance_updated": "Yasal kontrol güncellendi", "event_created": "Etkinlik eklendi",
    "event_deleted": "Etkinlik silindi", "invoice_status": "Fatura durumu değişti", "job_triggered": "İş elle çalıştırıldı",
    "model_updated": "Öneri modeli güncellendi", "plan_changed": "Paket değiştirildi", "plan_created": "Paket oluşturuldu",
    "plan_updated": "Paket güncellendi", "provider_cost_updated": "Sağlayıcı maliyeti güncellendi",
    "room_type_bulk_approve": "Oda eşlemeleri toplu onaylandı", "room_type_mapped": "Oda tipi eşlendi",
    "subscription_canceled": "Abonelik iptal edildi", "subscription_updated": "Abonelik güncellendi",
    "suggestion_applied": "Öneri uygulandı", "suggestion_ignored": "Öneri yok sayıldı", "suggestion_reset": "Öneri işareti kaldırıldı",
    "weights_tuned": "Motor ağırlıkları sonuçlara göre ayarlandı",
    "suggestions_regenerated": "Öneriler yeniden hesaplandı", "system_settings": "Sistem ayarları değişti",
    "user_created": "Kullanıcı oluşturuldu", "user_toggled": "Kullanıcı durumu değişti",
}
EVENT_CATEGORY_LABELS = {"festivals": "Festival", "concerts": "Konser", "conferences": "Konferans", "expos": "Fuar",
                         "sports": "Spor", "community": "Yerel etkinlik", "public-holidays": "Resmi tatil",
                         "school-holidays": "Okul tatili", "performing-arts": "Sahne sanatları"}


def rationale_drivers(r: dict | None, limit: int = 3) -> list[dict]:
    """Öneri gerekçesini (price_suggestions.rationale) sade Türkçe etkenlere ayırır, en etkili olan başta.

    Her etken: {"text": ..., "dir": "up" | "down" | "flat"}. Sunum katmanıdır; motorun gerekçe metnine dokunmaz.
    """
    if not r:
        return []
    adj = r.get("adjustments_pct") or {}
    out: list[tuple[float, dict]] = []
    pi = r.get("position_index")
    if pi is not None and abs(float(pi) - 1) >= 0.05:
        pct = round(float(pi) * 100)
        out.append((abs(float(pi) - 1) * 100, {"dir": "down" if pi < 1 else "up",
                    "text": f"Fiyat konumunuz: geçmişte rakip medyanının %{pct} düzeyinde"}))
    mc = r.get("comp_median_change_7d_pct")
    if mc is not None and abs(float(mc)) >= 1:
        out.append((abs(float(mc)), {"dir": "up" if mc > 0 else "down",
                    "text": f"Rakip fiyatları 7 günde %{abs(float(mc)):.0f} {'arttı' if mc > 0 else 'azaldı'}"}))
    else:
        out.append((0.5, {"dir": "flat", "text": "Rakip fiyatları 7 gündür yatay"}))
    if r.get("demand_level"):
        d = float(adj.get("demand") or 0)
        out.append((abs(d) + 0.4, {"dir": "up" if d > 0 else "down" if d < 0 else "flat",
                    "text": f"Talep {str(r['demand_level']).lower()} ({float(r.get('demand_score') or 0):.0f}/100)"}))
    own_o, comp_o = r.get("own_occ"), r.get("comp_occ")
    if comp_o is not None:
        a = float(adj.get("occupancy") or 0) + float(adj.get("compression") or 0)
        if own_o is not None:
            text = f"Tahmini doluluk: sizde %{float(own_o) * 100:.0f}, rakiplerde %{float(comp_o) * 100:.0f}"
        else:
            text = f"Rakiplerin tahmini doluluğu %{float(comp_o) * 100:.0f}"
        out.append((abs(a) + 0.45, {"dir": "up" if a > 0 else "down" if a < 0 else "flat", "text": text}))
    inv = float(r.get("inventory_pressure") or 0)
    if abs(inv) >= 0.15:
        out.append((abs(float(adj.get("inventory") or 0)) + 0.3, {"dir": "up" if inv > 0 else "down",
                    "text": "Rakiplerde kalan oda hızla azalıyor" if inv > 0 else "Rakiplerde boş oda artıyor"}))
    if r.get("season_label"):
        s = float(adj.get("season") or 0)
        out.append((abs(s) + 0.2, {"dir": "up" if s > 0 else "down" if s < 0 else "flat", "text": str(r["season_label"])}))
    if r.get("clamped") == "floor":
        out.append((100.0, {"dir": "flat", "text": "Öneri taban fiyatınıza dayandı"}))
    elif r.get("clamped") == "ceiling":
        out.append((100.0, {"dir": "flat", "text": "Öneri tavan fiyatınıza dayandı"}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in out[:limit]]


def fmt_date(value: Any, style: str = "short") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        if style == "datetime":
            aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            local = aware.astimezone(ZoneInfo(settings.timezone))
            return f"{local.day} {MONTHS[local.month - 1]} {local.year} {local:%H:%M}"
        value = value.date()
    if style == "day":
        return f"{value.day} {MONTHS[value.month - 1]} {DAYS[value.weekday()]}"
    if style == "long":
        return f"{value.day} {MONTHS_LONG[value.month - 1]} {value.year}"
    if style == "month":
        return f"{MONTHS_LONG[value.month - 1]} {value.year}"
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def ago(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - value).total_seconds()
    if secs < 60:
        return "az önce"
    if secs < 3600:
        return f"{int(secs // 60)} dk önce"
    if secs < 86400:
        return f"{int(secs // 3600)} sa önce"
    return f"{int(secs // 86400)} gün önce"


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


def to_json(value: Any) -> Markup:
    """<script type=application/json> içinde güvenle kullanılacak JSON."""
    s = json.dumps(value, cls=_Enc, ensure_ascii=False)
    s = s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(s)


def spark_path(values: list, width: int = 120, height: int = 32, area: bool = False) -> str:
    """Küçük çizgi grafik (sparkline) için SVG yol verisi. Boş değerler atlanır."""
    pts = [(i, float(v)) for i, v in enumerate(values or []) if v is not None]
    if len(pts) < 2:
        return ""
    n = max(len(values) - 1, 1)
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1.0
    pad = 2
    coords = [(round(i / n * width, 1), round(pad + (1 - (v - lo) / span) * (height - 2 * pad), 1)) for i, v in pts]
    d = "M" + " L".join(f"{x},{y}" for x, y in coords)
    if area:
        d += f" L{coords[-1][0]},{height} L{coords[0][0]},{height} Z"
    return d


def initials(name: str | None) -> str:
    words = [w for w in (name or "").replace("&", " ").split() if w[:1].isalpha()]
    return ("".join(w[0] for w in words[:2]) or "?").upper()


def hue_for(name: str | None) -> int:
    """İsimden sabit bir renk tonu (avatar arka planı için)."""
    return sum(ord(c) for c in (name or "")) * 37 % 360


templates.env.filters.update(combine=lambda a, b: {**(a or {}), **(b or {})}, spark=spark_path, initials=initials, hue=hue_for,
    num=fmt_number, eur=fmt_eur, pct=fmt_pct, signed=fmt_signed, dt=fmt_date, ago=ago, json=to_json,
)
templates.env.globals.update(settings=settings, today=date.today, rationale_drivers=rationale_drivers,
                             AUDIT_LABELS=AUDIT_LABELS, EVENT_CATEGORY_LABELS=EVENT_CATEGORY_LABELS)


def _sample_radar():
    from app.routers.public import sample_radar

    return sample_radar()


# ----------------------------------------------------------------------------- yetki
class LoginRequired(Exception):
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


class Forbidden(Exception):
    pass


class CsrfError(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        request.session.pop("user_id", None)
        return None
    return user


def require_user(request: Request, user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise LoginRequired(str(request.url.path))
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise Forbidden()
    return user


class HotelContext:
    def __init__(self, user: User, hotel: Hotel, impersonating: bool):
        self.user, self.hotel, self.impersonating = user, hotel, impersonating


def require_hotel(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)) -> HotelContext:
    if user.role == "admin":
        hid = request.session.get("view_hotel_id")
        hotel = db.get(Hotel, hid) if hid else None
        if hotel is None:
            raise Forbidden()
        return HotelContext(user, hotel, True)
    if not user.hotel_id:
        raise Forbidden()
    hotel = db.get(Hotel, user.hotel_id)
    if hotel is None:
        raise Forbidden()
    return HotelContext(user, hotel, False)


async def csrf_protect(request: Request) -> None:
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = request.headers.get("x-csrf-token")
        if not token:
            form = await request.form()
            token = form.get("csrf_token")
        if not csrf_valid(request.session, token):
            raise CsrfError()


# ----------------------------------------------------------------------------- yanıtlar
def flash(request: Request, message: str, level: str = "success") -> None:
    msgs = request.session.get("flash", [])
    msgs.append({"message": message, "level": level})
    request.session["flash"] = msgs


def redirect(url: str, request: Request | None = None, message: str | None = None, level: str = "success") -> RedirectResponse:
    if request is not None and message:
        flash(request, message, level)
    return RedirectResponse(url, status_code=303)


def render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    session = request.session
    base = {
        "request": request,
        "csrf_token": get_csrf_token(session),
        "flashes": session.pop("flash", []),
        "path": request.url.path,
        "is_demo": settings.is_demo,
    }
    if template.startswith("public/") and "radar_sample" not in ctx:
        base["radar_sample"] = _sample_radar()
    base.update(ctx)
    return templates.TemplateResponse(request, template, base, status_code=status_code)


def audit(db: Session, request: Request | None, user: User | None, action: str, entity: str | None = None,
          entity_id: Any = None, details: dict | None = None) -> None:
    ip = request.client.host if request is not None and request.client else None
    db.add(AuditLog(user_id=user.id if user else None, action=action, entity=entity,
                    entity_id=str(entity_id) if entity_id is not None else None, details=details, ip=ip))


def unread_count(db: Session, hotel_id: int) -> int:
    return db.execute(select(func.count(Notification.id)).where(
        Notification.hotel_id == hotel_id, Notification.is_read.is_(False))).scalar() or 0


def paginate(total: int, page: int, per_page: int) -> dict:
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    return {"page": page, "pages": pages, "total": total, "per_page": per_page,
            "offset": (page - 1) * per_page, "has_prev": page > 1, "has_next": page < pages}
