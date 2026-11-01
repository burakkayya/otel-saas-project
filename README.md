# OtelRadar: Otel Dinamik Fiyatlandırma ve Rakip Analizi (MVP)

Otelin hiçbir iç sistemine (PMS, kanal yöneticisi) bağlanmadan, halka açık fiyat ve envanter verisiyle
rakip analizi yapıp her oda tipi ve konaklama tarihi için **fiyat önerisi, taban, tavan ve gerekçe** üreten SaaS.
Pilot bölgeler: **Muğla ve Antalya**. Kaynak doküman: `otel-fiyatlandirma-proje-dokumani.md` (v1.0).

> Çalışma adı "OtelRadar"dır; `APP_NAME` ile değiştirilebilir (marka tescili kontrol edilmedi).

- Yapılanların tam listesi: [`docs/YAPILANLAR.md`](docs/YAPILANLAR.md)
- Açık kalan konular ve riskler: [`docs/ACIK_KONULAR.md`](docs/ACIK_KONULAR.md)

---

## Hızlı başlangıç

### A) Docker ile (önerilen)

```bash
cp .env.example .env          # Windows: copy .env.example .env
docker compose up --build
```

- Uygulama: http://localhost:8000
- API belgeleri: http://localhost:8000/api/docs
- Veritabanı arayüzü (isteğe bağlı): `docker compose --profile tools up adminer` → http://localhost:8080

İlk açılışta demo veri otomatik kurulur (72 otel, ~190.000 fiyat gözlemi, 8 abone; yaklaşık 1-2 dakika).
Verileri sıfırlamak için: `docker compose down -v && docker compose up --build`.

### B) Docker olmadan (VS Code)

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
set DATABASE_URL=sqlite:///./data/app.db      # PowerShell: $env:DATABASE_URL="sqlite:///./data/app.db"
python -m app.cli seed
python -m uvicorn app.main:app --reload
```

VS Code'da: **Çalıştır ve Hata Ayıkla → "OtelRadar: sunucuyu çalıştır (SQLite, demo)"**, ya da
**Terminal → Görevi Çalıştır** menüsündeki hazır görevler (Docker, testler, demo veri, lint).

### Demo hesapları

| Rol | E-posta | Parola |
|---|---|---|
| Otel (abone) | `otel@otelradar.local` (ve `otel2…otel8@otelradar.local`) | `Demo1234!` |
| Yönetici | `admin@otelradar.local` | `.env` içindeki `ADMIN_PASSWORD` (varsayılan `Admin123!`) |

**Üretime çıkmadan önce** `SECRET_KEY` ve `ADMIN_PASSWORD` değiştirilmeli, `SECURE_COOKIES=true` yapılmalıdır.

---

## Ekranlar

**Herkese açık:** tanıtım sayfası, paketler, giriş, 2 adımlı kayıt (otel adı + adres → OTA kaydıyla eşleştirme),
parola sıfırlama talebi, KVKK / gizlilik / kullanım koşulları taslakları, hata sayfaları.

**Otel paneli (`/panel`):** panel (bu gecenin önerisi, 60 günlük öneri/piyasa grafiği, talep, tahmini etki,
bildirimler), fiyat önerileri (liste + takvim ısı haritası, "Uyguladım" işaretleme, CSV), öneri ayrıntısı
(şelale grafiğiyle fiyatın nasıl oluştuğu, girdiler, rakip fiyatları, öneri geçmişi), pazar fiyat ızgarası
(fiyat / kalan oda), rakip seti (benzerlik puanı, harita, ekle/çıkar/onayla), talep ve sezon (bileşenli talep
skoru, etkinlikler, tatiller, mevsim katsayısı), uyum ve etki (uyum oranı, kontrol grubu DiD), backtest,
raporlar (CSV), oda tipleri (eşleme düzeltme), bildirimler, fiyat kuralları, abonelik (paket değiştir, faturalar,
iptal), hesabım, ilk kurulum sihirbazı.

**Yönetim paneli (`/admin`):** özet (MRR, aboneler, veri hattı, API kullanımı), oteller (liste + ayrıntı +
"otel paneline bak"), abonelikler, paketler, faturalar, kullanıcılar, veri hattı (işleri çalıştır, geçmiş),
API ve maliyet (birim ekonomisi hesaplayıcı), oda eşleme inceleme kuyruğu, öneri modeli (ağırlıklar + deneme
backtest), etki ölçümü (DiD), talep ve etkinlikler, yasal kontrol listesi, denetim kaydı, sistem ayarları.

---

## Mimari

```
app/
  main.py            FastAPI uygulaması, oturum, güvenlik başlıkları, hata sayfaları
  config.py          .env ayarları
  models.py          SQLAlchemy modelleri (dokümandaki 8 tablo + uygulama tabloları)
  web.py             şablon motoru, Türkçe biçimlendirme, yetki, CSRF
  routers/           public, auth, hotel (/panel), admin (/admin), api (/api/v1)
  services/
    providers/       demo (sentetik) ve live (RapidAPI, Amadeus, PredictHQ, Google Places, Fixer, ECB) istemcileri
    room_mapping.py  kural sözlüğü + (yalnızca belirsizler için) LLM
    compset.py       mesafe/yıldız/oda tipi/fiyat bandı puanlaması, elle ekleme, geri bildirim
    seasonality.py   aylık katsayı (gözlem + bölgesel ön bilgi)
    demand.py        talep skoru = %45 uçuş + %35 etkinlik + %20 tatil
    pricing.py       öneri motoru (taban/tavan zorunlu, gerekçe JSON, model sürümü)
    backtest.py      o gün bilinen veriyle geriye dönük test
    uptake.py        öneriye uyum (davranış ölçümü)
    roi.py           kontrol grubu fark-içinde-fark (her zaman "tahmini")
    costs.py         abone başına API maliyeti
    pipeline.py      zamanlanmış işler ve iş kaydı
  scheduler.py       APScheduler (Docker'da ayrı 'worker' servisi)
  seed.py, cli.py    demo veri ve komut satırı
  templates/, static/  arayüz (Jinja, kendi tasarım sistemi, Chart.js, yerel yazı tipleri)
tests/               birim, entegrasyon, tarayıcı (E2E) testleri
```

### Fiyat önerisi nasıl hesaplanır?

1. Rakip setindeki otellerin **aynı kategorideki** en uygun satılabilir oda fiyatı alınır (EUR'a çevrilmiş).
2. Dağılımın medyanı, otelin **konumlama endeksiyle** (son 60 günde fiyatınız / rakip medyanı) ölçeklenir.
3. Talep skoru, rakiplerde kalan oda sinyali ve sezon etkisiyle sınırlı bir ayarlama yapılır
   (strateji: temkinli ×0,6 / dengeli ×1 / agresif ×1,4; varsayılan sınır +%30 / −%25).
4. **Taban** = P25 × (1 − %taban), **tavan** = P90 × (1 + marj); yüksek sezonda marj artar, ölü sezonda öneri
   tabana yaklaşır. Otelin mutlak min/maks fiyatları her zaman geçerlidir. Öneri bu sınırların dışına çıkamaz.
5. Her öneri, gerekçe metni ve tüm girdileriyle `price_suggestions.rationale` (JSONB) alanına `model_version`
   etiketiyle kaydedilir.

Ağırlıklar yönetim panelinden değiştirilebilir; yayına almadan önce "deneme backtest" ile karşılaştırılır.

---

## Testler

```bash
pytest tests/unit tests/integration          # 178 test, ~25 sn (SQLite)
pytest --cov=app tests/unit tests/integration # kapsam ~%94
python -m playwright install chromium
pytest -m e2e tests/e2e                       # 7 gerçek tarayıcı testi (~50 sn)
```

PostgreSQL üzerinde çalıştırmak için:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://kullanici@localhost:5432/test_db pytest tests/unit tests/integration
```

## Yararlı komutlar

```bash
python -m app.cli init-db
python -m app.cli seed --scale 1.0 --history 120 --horizon 60
python -m app.cli reset-demo
python -m app.cli run-job daily_pipeline     # demand_refresh, suggestions, compset_rebuild, uptake, roi_did, backtest
python -m app.cli create-admin yeni@ornek.com Parola123 "Ad Soyad"
```

## Canlı veriye geçiş

`.env` içinde `DATA_PROVIDER=live` yapıp API anahtarlarını girin. Canlı modda anahtarı olmayan bileşen için
**sahte veri kullanılmaz**: fiyat kaynağı yoksa iş açık hatayla durur, uçuş/etkinlik yoksa nötr değer (50) ve
boş liste kullanılır, kur için anahtarsız ECB referans kurları kullanılır. Canlıya geçmeden önce
`docs/ACIK_KONULAR.md` ve yönetim panelindeki **Yasal kontrol listesi** tamamlanmalıdır.

Yazı tipleri (Bricolage Grotesque, Instrument Sans) SIL Open Font License ile `app/static/fonts` altında,
Chart.js MIT lisansıyla `app/static/vendor` altında yerel olarak sunulur.
