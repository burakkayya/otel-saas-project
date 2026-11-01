"""Yönetim paneli: tüm ekranlar ve işlemler."""
import re

import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    ComplianceItem,
    Event,
    Hotel,
    Invoice,
    JobRun,
    Plan,
    ProviderCost,
    RoomType,
    Subscription,
    User,
)

PAGES = ["/admin", "/admin/oteller", "/admin/oteller?q=Bodrum&il=Muğla&abone=evet", "/admin/oteller?abone=hayir&sayfa=2",
         "/admin/aboneler", "/admin/aboneler?durum=active", "/admin/paketler", "/admin/faturalar", "/admin/faturalar?durum=paid",
         "/admin/kullanicilar", "/admin/kullanicilar?q=otel", "/admin/veri-hatti", "/admin/veri-hatti?is=seed_demo",
         "/admin/api-maliyet", "/admin/api-maliyet?abone=50&rakip=8&ufuk=90&tarama=2&tarih_basina=30&ortak=40",
         "/admin/oda-eslemeleri", "/admin/oda-eslemeleri?filtre=tum", "/admin/oda-eslemeleri?filtre=suite",
         "/admin/oda-eslemeleri?filtre=manual", "/admin/model", "/admin/etki", "/admin/talep", "/admin/talep?il=Antalya",
         "/admin/uyumluluk", "/admin/denetim", "/admin/sistem"]


@pytest.mark.parametrize("url", PAGES)
def test_admin_pages_render(admin_browser, url):
    r = admin_browser.get(url)
    assert r.status_code == 200, r.text[:500]
    assert "Beklenmeyen bir hata" not in r.text


def test_hotel_detail_and_update(admin_browser, db):
    h = db.execute(select(Hotel).where(Hotel.is_subscriber.is_(False))).scalars().first()
    assert admin_browser.get(f"/admin/oteller/{h.id}").status_code == 200
    assert admin_browser.get("/admin/oteller/999999").status_code == 404
    r = admin_browser.post(f"/admin/oteller/{h.id}", {"star_rating": "5", "room_count": "77", "hotel_type": "resort",
                                                     "district": h.district, "is_active": "1"})
    assert r.status_code == 303
    db.expire_all()
    h2 = db.get(Hotel, h.id)
    assert (h2.star_rating, h2.room_count, h2.hotel_type, h2.is_active) == (5, 77, "resort", True)


def test_impersonation(admin_browser, db):
    h = db.execute(select(Hotel).where(Hotel.is_subscriber.is_(True))).scalars().first()
    r = admin_browser.post(f"/admin/oteller/{h.id}/panel")
    assert r.status_code == 303 and r.headers["location"] == "/panel"
    page = admin_browser.get("/panel")
    assert page.status_code == 200 and "Yönetici görünümü" in page.text and h.name in page.text
    # yönetici görünümünde hesap değiştirilemez
    r = admin_browser.post("/panel/hesap", {"full_name": "X Y Z"})
    assert r.status_code == 303
    assert admin_browser.post("/admin/panel-cik").status_code == 303
    assert admin_browser.get("/panel").status_code == 403


def test_plan_crud(admin_browser, db):
    r = admin_browser.post("/admin/paketler", {"code": "kurumsal", "name": "Kurumsal", "price": "999", "target": "Zincir",
                                               "max_competitors": "20", "max_room_types": "10", "horizon_days": "120",
                                               "features": "A\nB"})
    assert r.status_code == 303
    p = db.execute(select(Plan).where(Plan.code == "kurumsal")).scalar_one()
    assert p.features == ["A", "B"] and float(p.monthly_price_eur) == 999
    r = admin_browser.post(f"/admin/paketler/{p.id}", {"name": "Kurumsal+", "price": "1099,5", "max_competitors": "20",
                                                       "max_room_types": "10", "horizon_days": "120", "features": "A",
                                                       "sort_order": "9"})
    assert r.status_code == 303
    db.expire_all()
    p = db.get(Plan, p.id)
    assert p.name == "Kurumsal+" and float(p.monthly_price_eur) == 1099.5 and not p.is_active
    # yinelenen kod reddedilir
    r = admin_browser.post("/admin/paketler", {"code": "kurumsal", "name": "X", "price": "1"})
    assert "benzersiz" in admin_browser.get(r.headers["location"]).text


def test_subscription_and_invoice_update(admin_browser, db):
    sub = db.execute(select(Subscription).where(Subscription.status == "active")).scalars().first()
    r = admin_browser.post(f"/admin/aboneler/{sub.id}", {"status": "past_due", "plan_id": sub.plan_id})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Subscription, sub.id).status == "past_due"
    admin_browser.post(f"/admin/aboneler/{sub.id}", {"status": "active", "plan_id": sub.plan_id})
    assert admin_browser.post(f"/admin/aboneler/{sub.id}", {"status": "bozuk", "plan_id": sub.plan_id}).status_code == 400
    inv = db.execute(select(Invoice)).scalars().first()
    assert admin_browser.post(f"/admin/faturalar/{inv.id}", {"status": "failed"}).status_code == 303
    db.expire_all()
    assert db.get(Invoice, inv.id).status == "failed"


def test_user_management(admin_browser, db):
    h = db.execute(select(Hotel).where(Hotel.is_subscriber.is_(True))).scalars().first()
    r = admin_browser.post("/admin/kullanicilar", {"email": "Personel@Test.local", "full_name": "Personel", "role": "hotel",
                                                   "hotel_id": str(h.id), "password": "Parola123"})
    assert r.status_code == 303
    u = db.execute(select(User).where(User.email == "personel@test.local")).scalar_one()
    assert admin_browser.post(f"/admin/kullanicilar/{u.id}/durum").status_code == 303
    db.expire_all()
    assert not db.get(User, u.id).is_active
    r = admin_browser.post(f"/admin/kullanicilar/{u.id}/parola")
    page = admin_browser.get("/admin/kullanicilar").text
    assert "geçici parola" in page.lower()
    # zayıf parola reddedilir
    r = admin_browser.post("/admin/kullanicilar", {"email": "z@test.local", "full_name": "Z", "role": "admin", "password": "123"})
    assert "en az 8" in admin_browser.get(r.headers["location"]).text
    # yönetici kendini kapatamaz
    me = db.execute(select(User).where(User.email == "admin@otelradar.local")).scalar_one()
    admin_browser.post(f"/admin/kullanicilar/{me.id}/durum")
    db.expire_all()
    assert db.get(User, me.id).is_active


def test_trigger_job_runs_in_background(admin_browser, db):
    r = admin_browser.post("/admin/veri-hatti/calistir", {"job": "uptake"})
    assert r.status_code == 303
    run = db.execute(select(JobRun).where(JobRun.job_name == "uptake").order_by(JobRun.id.desc())).scalars().first()
    assert run is not None and run.status in ("success", "running")
    assert admin_browser.post("/admin/veri-hatti/calistir", {"job": "yok"}).status_code == 400


def test_provider_cost_update(admin_browser, db):
    r = admin_browser.post("/admin/api-maliyet/rapidapi", {"unit_cost_eur": "0,002", "monthly_fee_eur": "25",
                                                           "included_requests": "1000", "notes": "Pro plan", "enabled": "1"})
    assert r.status_code == 303
    db.expire_all()
    pc = db.get(ProviderCost, "rapidapi")
    assert float(pc.unit_cost_eur) == 0.002 and float(pc.monthly_fee_eur) == 25
    assert admin_browser.post("/admin/api-maliyet/yok", {"unit_cost_eur": "1", "monthly_fee_eur": "1"}).status_code == 404


def test_mapping_review(admin_browser, db):
    rt = db.execute(select(RoomType).where(RoomType.category == "other")).scalars().first()
    assert admin_browser.post(f"/admin/oda-eslemeleri/{rt.id}", {"category": "suite"}).status_code == 303
    db.expire_all()
    assert db.get(RoomType, rt.id).mapped_by == "manual"
    others = [r.id for r in db.execute(select(RoomType).where(RoomType.reviewed.is_(False))).scalars()][:3]
    r = admin_browser.post("/admin/oda-eslemeleri/toplu-onay", {"ids": [str(i) for i in others]})
    assert r.status_code == 303
    db.expire_all()
    assert all(db.get(RoomType, i).reviewed for i in others)


def test_model_settings_and_trial_backtest(admin_browser, db):
    page = admin_browser.get("/admin/model?deneme=1&demand=0.02&inventory=0.06&season=0.04")
    assert page.status_code == 200 and "Yayındaki" in page.text and "Önerilen" in page.text
    bad = admin_browser.post("/admin/model", {"demand": "5", "inventory": "0", "season": "0", "max_up": "0.3",
                                              "max_down": "0.25", "version": "v"})
    assert "0 ile 1" in admin_browser.get(bad.headers["location"]).text
    ok = admin_browser.post("/admin/model", {"demand": "0.06", "inventory": "0.06", "season": "0.04", "max_up": "0.3",
                                             "max_down": "0.25", "version": "v1.1-test"})
    assert ok.status_code == 303
    from app.services.pricing import current_model_version, load_weights

    db.expire_all()
    assert current_model_version(db) == "v1.1-test" and load_weights(db)["demand"] == 0.06


def test_impact_run(admin_browser, db):
    h = db.execute(select(Hotel).where(Hotel.is_subscriber.is_(True))).scalars().first()
    assert admin_browser.post(f"/admin/etki/{h.id}").status_code == 303


def test_event_crud(admin_browser, db):
    r = admin_browser.post("/admin/talep/etkinlik", {"province": "Muğla", "name": "Test Kongresi", "category": "conferences",
                                                      "start_date": "2026-12-01", "end_date": "2026-12-03", "impact": "70"})
    assert r.status_code == 303
    ev_id = db.execute(select(Event.id).where(Event.name == "Test Kongresi")).scalar_one()
    bad = admin_browser.post("/admin/talep/etkinlik", {"province": "Muğla", "name": "X", "start_date": "2026-12-05",
                                                        "end_date": "2026-12-01", "impact": "70"})
    assert "geçersiz" in admin_browser.get(bad.headers["location"]).text
    assert admin_browser.post(f"/admin/talep/etkinlik/{ev_id}/sil").status_code == 303
    assert db.execute(select(Event.id).where(Event.id == ev_id)).scalar_one_or_none() is None


def test_compliance_requires_evidence(admin_browser, db):
    it = db.execute(select(ComplianceItem)).scalars().first()
    r = admin_browser.post(f"/admin/uyumluluk/{it.id}", {"is_done": "1", "evidence_note": ""})
    assert "kanıt" in admin_browser.get(r.headers["location"]).text
    db.expire_all()
    assert not db.get(ComplianceItem, it.id).is_done
    admin_browser.post(f"/admin/uyumluluk/{it.id}", {"is_done": "1", "evidence_note": "Sözleşme PDF, Drive/Hukuk"})
    db.expire_all()
    assert db.get(ComplianceItem, it.id).is_done


def test_system_settings_and_audit(admin_browser, db):
    assert admin_browser.post("/admin/sistem", {"scan_scope": "compset", "horizon_days": "45"}).status_code == 303
    from app.services.pipeline import get_setting

    db.expire_all()
    assert get_setting(db, "scan_scope") == "compset" and get_setting(db, "horizon_days") == 45
    admin_browser.post("/admin/sistem", {"scan_scope": "all", "horizon_days": "30"})
    assert db.execute(select(AuditLog).where(AuditLog.action == "system_settings")).first()
    page = admin_browser.get("/admin/denetim?islem=system_settings").text
    assert "system_settings" in page
    assert re.search(r"admin@otelradar\.local", page)
