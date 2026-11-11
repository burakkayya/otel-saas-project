# Yapılanlar

Tarih: 1 Kasım 2026 · Kaynak: `otel-fiyatlandirma-proje-dokumani.md` (v1.0)

Bu belge, proje dokümanındaki MVP kapsamının nasıl hayata geçirildiğini ve dokümana göre bilinçli olarak
yapılan farklılıkları listeler. Açık kalan konular için: [`ACIK_KONULAR.md`](ACIK_KONULAR.md).

## 1. Teknoloji yığını (doküman 4.1)

| Katman | Dokümandaki öneri | Uygulanan |
|---|---|---|
| Dil | Python 3.12 | Python 3.12 (Docker); 3.13 ile de test edildi |
| Web/API | FastAPI | FastAPI + Jinja şablonları (ayrı frontend yok) |
| Veritabanı | PostgreSQL | PostgreSQL 16 (Docker). Geliştirme/test için SQLite da desteklenir |
| Veri işleme | pandas | **Kullanılmadı.** Ortalama/yüzdelik hesapları standart kütüphaneyle yapıldı; bağımlılık ve imaj boyutu küçüldü. Gelişmiş modellerde eklenebilir |
| Zamanlama | APScheduler veya cron | APScheduler, Docker'da ayrı `worker` servisi |
| Oda eşleme | Kural + LLM | Kural sözlüğü (TR/EN) + yalnızca belirsiz kayıtlar için LLM (anahtar varsa) |
| Arayüz | Basit şablonlar | Kendi tasarım sistemi, açık/koyu tema, mobil uyum, Chart.js grafikleri |

## 2. Veri modeli (doküman 7)

Dokümandaki 8 tablonun tamamı aynı alanlarla oluşturuldu: `hotels`, `room_types`, `rate_snapshots`,
`competitor_sets`, `price_suggestions`, `applied_observations`, `inventory_events`, `roi_estimates`.
Dokümana eklenen alanlar: `hotels.address/hotel_type/place_id/is_active`, `room_types.reviewed`,
`competitor_sets.distance_km/components/feedback`, `price_suggestions.user_action`, `roi_estimates.details`.

Uygulamanın çalışması için eklenen tablolar: `users`, `plans`, `subscriptions`, `invoices`, `hotel_settings`,
`notifications`, `compset_feedback` (compset isabeti), `demand_signals`, `events`, `fx_rates`, `job_runs`,
`api_usage`, `provider_costs`, `app_settings`, `compliance_items`, `audit_logs`.

## 3. Algoritmalar (doküman 5)

- **Compset (5.1):** puan = %40 mesafe + %25 yıldız + %15 oda tipi benzerliği + %20 fiyat bandı. 5 rakip;
  izole otelde yarıçap 5 → 12 → 30 → 80 km genişler. Elle eklenen rakipler korunur (`is_manual`), otelin
  "rakibimiz değil" dediği oteller bir daha önerilmez. Onay oranı "compset isabeti" olarak raporlanır.
- **Oda tipi eşleme (5.2):** Türkçe karakter normalizasyonlu kural sözlüğü; belirsiz adlar için LLM;
  `mapped_by` + `confidence` saklanır; güveni 0,75 altı kayıtlar yönetim inceleme kuyruğuna düşer;
  kıyaslama yalnızca aynı kategori içinde yapılır.
- **Mevsim katsayısı (5.3):** gözlenen aylık ortalama / genel ortalama; veri az olan aylarda bölgesel ön bilgi
  (Bodrum yaz yoğun, Antalya uzun sezon, Kapadokya dönemsel) ile harmanlanır.
- **Fiyat önerisi (5.4):** rakip medyanı ve dağılımı, kalan oda sinyali, talep skoru, mevsim katsayısı; taban ve
  tavan zorunlu; "maksimum kâr" P90 tabanlı ödeme istekliliği tahmini olarak uygulanır ve panelde dönüşüm
  verisi olmadığı açıkça yazılır; her öneri `model_version` ile kaydedilir.
  **Dokümana ek:** "konumlama endeksi" (otelin tarihsel fiyatı / rakip medyanı). Bu olmadan bir pansiyona
  resort fiyatı önerilebiliyordu (ilk denemede +%117 öneri görüldü).
- **Talep skoru:** %45 uçuş arama endeksi + %35 etkinlik etkisi + %20 tatil takvimi (resmi tatiller, bayramlar,
  köprü günleri, okul tatili, hafta sonu).

## 4. ROI ve başarı ölçümü (doküman 6, revize)

- Kalan oda düşüşü hiçbir yerde **satış** olarak sayılmıyor; arayüzde "satış ilerlemesi vekili" olarak ve
  uyarıyla gösteriliyor.
- **Öneriye uyum (6.1a):** gözlenen fiyat, gözlemden en az 1 saat önce üretilmiş son önerinin ±%tolerans
  bandında mı? `applied_observations` tablosu. Gelir iddiası değil, davranış ölçüsü olarak etiketli.
- **Kontrol grubu (6.1b):** fark-içinde-fark; abonelik öncesi 8 hafta ve sonrası; aynı ilde ±1 yıldız
  abone olmayan oteller; standart hata ile anlamlılık testi; 10'dan az kontrol oteli veya anlamsız sonuçta
  güven "düşük".
- **Etiketleme (6.1c):** tüm `roi_estimates` kayıtları `is_estimate = TRUE`; arayüzde "tahmini etki"; "ek kâr"
  veya "kurtarılan gelir" ifadesi hiçbir yerde yok (testle doğrulanıyor).
- **Backtest (6.2):** as_of = konaklama − öncül gün; yalnızca o gün bilinen veriyle öneri; gerçekleşen
  (konumlamaya göre ölçeklenmiş) piyasa medyanıyla MAPE, "bugünkü medyanı kopyala" kıyas yöntemi, yön isabeti,
  bant isabeti, talep–satış korelasyonu. Demo veride öneri bazı otellerde kıyası geçemiyor; bu dürüstçe
  gösteriliyor ve yönetim panelindeki deneme backtest ile ağırlıklar ayarlanabiliyor.

## 5. Ekranlar

**Herkese açık (8):** tanıtım, paketler, giriş, kayıt (2 adım: bilgiler → OTA kaydıyla eşleştirme), parola
sıfırlama talebi, KVKK, gizlilik, kullanım koşulları, hata sayfaları.

**Otel paneli (16):** panel, ilk kurulum, fiyat önerileri (liste/takvim), öneri ayrıntısı (şelale grafiği),
pazar fiyatları (fiyat/kalan oda ızgarası), rakip seti (harita, ekle/çıkar/onayla), talep ve sezon, oda tipleri,
uyum ve etki, backtest, raporlar (3 CSV), bildirimler, fiyat kuralları, abonelik, hesabım.

**Yönetim paneli (16):** özet, oteller, otel ayrıntısı (+ otel paneline yönetici olarak bakma), abonelikler,
paketler, faturalar, kullanıcılar (geçici parola), veri hattı, API ve maliyet (birim ekonomisi hesaplayıcı),
oda eşleme kuyruğu (toplu onay), öneri modeli (deneme backtest), etki ölçümü, talep ve etkinlikler, yasal
kontrol listesi (kanıt notu zorunlu), denetim kaydı, sistem ayarları (tarama kapsamı, ufuk).

**JSON API:** `/api/v1/me`, `/suggestions`, `/market`, `/demand`, `/admin/overview`; belgeler `/api/docs`.

## 5b. Görsel tasarım katmanı (2. tur)

- **Rakip radarı:** oteliniz merkezde; rakipler gerçek kerteriz ve mesafelerine göre (karekök ölçek) yerleşir,
  nokta büyüklüğü benzerlik puanı, sarı noktalar elle eklenen rakipler. Panelde, rakip setinde, tanıtım ve giriş
  sayfalarında kullanılır.
- **Fiyat bandı göstergesi:** taban–tavan bandı, öneri, mevcut fiyat ve rakip medyanı tek çizgide; panel
  kahraman alanında, haftalık tabloda, öneri listesinde ve öneri ayrıntısında.
- **KPI kutuları:** renkli ikon çipleri ve küçük eğilim grafikleri (sparkline).
- **Halka göstergeler:** öneriye uyum ve compset isabeti.
- **Isı haritaları:** pazar ızgarasında rakip fiyatının sizinkine göre farkı (ıraksak mavi/kırmızı), talep
  sayfasında 3 aylık talep takvimi (sıralı mavi, etkinlik günleri işaretli).
- **Grafikler:** öneri çizgisinin altında renk geçişi, fareyle dikey kılavuz çizgi, talep grafiğinde "Bugün"
  işareti.
- **Diğer:** otel adlarından otomatik renkli avatarlar, kayan bildirim kutuları (kendiliğinden kapanır),
  etkin menü vurgusu, tek seferlik sayfa açılış animasyonu ve öneri fiyatı sayacı (hareket azaltma tercihine
  uyar), yönetim panelinde 14 günlük veri hattı sağlık şeridi, tanıtım sayfasında ürün önizlemesi.
- Açık/koyu tema ve 390 px mobil genişlikte tüm ekranlar ekran görüntüsüyle kontrol edildi.

## 6. Veri sağlayıcıları

- **Demo sağlayıcı:** 72 kurgusal otel (Muğla 34, Antalya 38), deterministik fiyat/kalan oda/talep/kur üretimi,
  ara sıra oda kapatma (stop-sell) simülasyonu. Arayüzde her sayfada "Demo veri modu" uyarısı var.
- **Canlı istemciler:** RapidAPI (Makcorps/Caviar), Amadeus, PredictHQ, Google Places (New), Fixer, ECB.
  Yeniden deneme, hata kaydı, istek sayacı. Canlı modda eksik anahtar için sahte veriye düşülmez.
- **İstek sayacı:** demo modda bile "gerçek API kullanılsaydı yapılacak istek" sayılır; birim ekonomisi bu
  sayılarla ölçülür.

## 7. Güvenlik

PBKDF2-SHA256 parola özeti, oturum çerezi (HttpOnly, SameSite=Lax, üretimde Secure), tüm POST'larda CSRF,
giriş denemesi sınırı (5 deneme / 5 dk), açık yönlendirme koruması, rol ayrımı (otel / yönetici), başka otelin
verisine erişim engeli, güvenlik başlıkları, denetim kaydı, parola sıfırlamada hesap varlığı sızdırmama.

## 8. Testler (hepsi geçiyor)

| Takım | Sayı | Kapsam |
|---|---|---|
| Birim | 60 | oda eşleme, fiyat motoru, takvim, sezon, güvenlik, biçimlendirme, maliyet, demo ve canlı API istemcileri (sahte HTTP ile) |
| Entegrasyon | 118 | tüm servisler, tüm sayfalar (otel 19, yönetim 26), tüm form işlemleri, yetki, CSRF, kayıt akışı, CSV, JSON API, CLI, veri hattı işleri |
| Tarayıcı (E2E) | 7 | gerçek Chromium: tüm menü sayfaları, grafiklerin çizildiği, JS hatası olmadığı, tema, mobil menü, kayıt, yönetim akışları |

- SQLite **ve PostgreSQL 16** üzerinde 178/178 geçti; kod kapsamı ~%94.
- Tam ölçekli demo (72 otel, ~187.000 gözlem) PostgreSQL'de ~70 sn'de kuruluyor; günlük veri hattı ~4 sn;
  sayfalar 0,1 sn altında, backtest ekranı ~2,5 sn.
- Mobil (390 px) genişlikte tüm otel ve yönetim sayfalarında yatay taşma olmadığı otomatik kontrol edildi.

## 9. Geliştirme ortamı

- `docker-compose.yml`: `db` (PostgreSQL 16), `web` (ilk açılışta demo veri), `worker` (zamanlayıcı),
  isteğe bağlı `adminer`. `scripts/start.sh` yerel PostgreSQL'e karşı denendi.
- `.vscode/`: hata ayıklama yapılandırmaları, görevler (Docker, testler, demo veri, lint), önerilen eklentiler.
- `ruff` ile lint temiz.

## 10. Impeccable iyileştirme turu (2 Kasım 2026)

Dal `feat/impeccable-ui`. Süreç:
- `/impeccable init` → `PRODUCT.md`
- `/impeccable document` → `DESIGN.md` + `.impeccable/design.json`
- 45 ekran için çift ajanlı critique + audit → `docs/UI_AUDIT.md`
- plan → `docs/superpowers/plans/2026-11-02-impeccable-ui.md`

Mevcut kimlik korundu: kireç beyazı, liman laciverti, Ege mavisi, begonvil, Bricolage + Instrument Sans, rakip radarı.

**Tasarım sistemi (colorize, harden):**
- Zemin sıcak kireç badanasına çekildi.
- `--muted` WCAG AA'ya getirildi (3,78 → ≥4,6:1).
- Koyu temada birincil düğme dolgusu, begonvil üstü metin ve bilgi rengi düzeltildi; liman laciverti yüzeyler zeminden ayrışıyor.
- Yeni belirteçler: `--focus`, `--brand-fill`, `--on-bougain`, `--cal-up/--cal-down`.
- Görünür odak halkası (lacivert yüzeylerde açık renk). `::selection`, `caret-color` ve `accent-color` temaya bağlandı.

**Renk anlamları:**
- Önerilen fiyat düşüşü alarm kırmızısıyla değil, nötr rozet ve okla gösteriliyor.
- Begonvil yalnızca fiyat artırma fırsatı için kullanılıyor.
- Öneri takvimi begonvil ↔ gri-mavi ölçeğe geçti; ısı hücrelerinin metni her tonda AA.

**Dürüstlük (doküman 6):**
- Demo veri uyarısı artık **her ekranda**: tanıtım, giriş, kayıt ve hata sayfaları dahil.
- Tanıtımda demo modda "72 örnek (kurgusal) tesis" yazıyor.
- Backtest'te kalan oda düşüşü artık "satış" diye adlandırılmıyor.
- Etki kartı "anlamlı fark var/yok" ile başlıyor. Yönetimde ±2 SH aralığı, dönem ve nötr tonlu anlamlılık gösteriliyor.
- Paket maddeleri sınırlarla tutarlı ("Sınırsız" yerine 8 oda kategorisi). E-posta maddeleri "yakında" olarak işaretli.
  Eski varsayılan maddeler açılışta otomatik taşınıyor.

**Ana iş: "bu gecenin fiyatı ne olmalı ve neden":**
- Panel kahraman alanında 7 cümlecikli paragrafın yerini "Neden bu fiyat?" başlığı altında en etkili 3 etken aldı
  (`rationale_drivers`, sade Türkçe).
- Güven rozeti fiyatın yanında. Öneri listesinde de aynı sade etkenler var.

**Formlar ve erişilebilirlik:**
- 56 etiketsiz yönetim alanı etiketlendi.
- `type` niteliği olmayan inputlar artık stil alıyor.
- Hata ve uyarı bildirimleri kendiliğinden kapanmıyor.
- Kayıt eşleştirmede zayıf veya başka ilçedeki aday önceden seçilmiyor.
- KVKK onay metni "bilgilendirildim" oldu. Segment sekmelerinde `aria-current` var.
- Mobil menüde `aria-expanded`, Esc ile kapanma ve odak yönetimi var. "İçeriğe geç" bağlantısı eklendi.
- Atlanan başlık seviyeleri düzeltildi.

**Duyarlı düzen (adapt):**
- Herkese açık sayfalardaki 111 px mobil taşma giderildi.
- Öneri listesi, "Bu hafta" ve oda tipleri 560 px altında etiketli kartlara dönüşüyor.
- Yatay kayan tablolarda kenar ipucu var.
- Giriş ekranının mobil üst bilgisi düzenlendi.
- Mobilde üst çubuk yapışkan değil, bildirimler üstte.
- Rakip tablosunun aksiyonları artık kesilmiyor.

**Grafikler ve hareket (animate, quieter):**
- Chart.js `prefers-reduced-motion` tercihine uyuyor.
- Orkestralı sayfa animasyonu ve kahraman kart şeridi kaldırıldı. Radar tek tur tarıyor.
- 6 kritik grafiğe "Tablo olarak göster" eklendi (`ui.chart(..., table=True)`).
- Otel ayrıntısında kategori renkleri sabit sırada.
- Grafik ipuçlarında da gerçek eksi işareti (−) kullanılıyor.
- Radar lejantı eklendi. Uzak rakipler ölçeği bozmuyor.

**Yönetim (harden, onboard):**
- Abonelik, fatura, kullanıcı ve toplu eşleme işlemleri sonucu açıklayan onay istiyor. Yönetici kendini devre dışı bırakamıyor.
- Veri hattında tek birincil aksiyon var; iş adları Türkçe.
- Boş durumlar sonraki adımı öneriyor. Fiyatlar virgüllü ondalıkla düzenleniyor.

**Performans ve altyapı (optimize):**
- Yazı tipleri önden yükleniyor, Chart.js `defer` ile geliyor.
- Docker'da web sağlık denetimi tohumlama süresini (240 sn) bekliyor. Worker'daki anlamsız HTTP denetimi kapatıldı;
  ilk `docker compose up --build` bu makinede doğrulandı (ACIK_KONULAR 4.2).

**Doğrulama:**
- `scripts/ui_snapshots.py` 45 ekranı açık/koyu tema ve 1440/390 px'te gezdi. Görüntüler `docs/screenshots/before` ve `after` altında.
- Sonra: 180 görünümde 0 konsol hatası, 0 yatay taşma, 0 kontrast ihlali, 0 etiketsiz alan. Saklı tercih olmadan
  sistem koyu temasında (90 görünüm) da 0.
- Testler: **287 birim/entegrasyon** (178 mevcut + 109 yeni, `tests/integration/test_ui_quality.py`) ve **9 E2E**
  (7 mevcut + mobil menü klavyesi, 390 px sığma). `ruff` temiz.

## 11. Profesyonel arayüz turu (11 Kasım 2026)

Dal `feat/pro-redesign`. Kimlik aynı kaldı (kireç beyazı, liman laciverti, Ege mavisi, begonvil yalnızca fırsat, Bricolage +
Instrument Sans, rakip radarı); tanıtım yüzeyleri ve panelin ana anları güçlendirildi.

**Marka:**
- Yeni logo işareti: radar halkası (Otel'in O'su), tarama dilimi ve dilimin bulduğu otel noktası. Favicon aynı çizimden.
- Deniz haritası eş derinlik çizgileri: lacivert yüzeylerin zemin deseni.
- İkisi de `scripts/make_brand_assets.py` ile üretiliyor.

**Tanıtım ve paketler (`app/static/css/site.css`):**
- Açılış: "Bu gecenin fiyatını tahmin etmeyin. Bilin." başlığı, otel adı kutusu (`/kayit?otel=` ile kayıt formunu dolduruyor)
  ve odak anı: radar bir tur tarar, ışın rakibe ulaştıkça fiyatı belirir, ardından öneri kartı oluşur.
- Dört soru bölümü (ne fiyat, rakipler, talep, neden), panel görüntüsü, kurulum adımları, "Sonuç iddia edilmez. Ölçülür."
  bölümü, paketler ve kapanış çağrısı.
- Ürün görüntüleri çalışan uygulamadan `scripts/make_product_shots.py` ile üretiliyor (`app/static/img/shots`).
- Paketler sayfası: öne çıkan paket, simgeli karşılaştırma tablosu, açılır SSS.
- Metin iddialı ama doğru: uydurma müşteri sayısı, referans ya da kesin gelir vaadi yok (testle korunuyor).

**Panel:**
- Kahraman alan önce ne yapılacağını söylüyor ("fiyatınızı €79 düzeyinden €71 düzeyine indirin"), sonra nedenini;
  "Uyguladım" düğmesi orada.
- "Sade / Ayrıntılı" görünüm seçimi: sade görünüm öneri, hafta ve radarı gösterir; tercih tarayıcıda saklanır.
- Öneri ayrıntısında da sade etkenler ve güven rozeti var.

**Grafikler:**
- Fiyat grafiğinde fırsat günleri (öneri %8+ yukarıda) begonvil noktayla işaretli.
- Cuma ve cumartesi geceleri gölgeli; talep grafiklerinde "yüksek talep" eşiği çizgiyle gösteriliyor.
- İpucunda öneri ile mevcut fiyatın farkı yazıyor.

**Hareket (hepsi `prefers-reduced-motion` tercihinde kapalı):**
- Sayfalar arası geçiş (View Transitions): içerik yumuşakça değişir, menü yerinde kalır, etkin menü öğesi yeni yerine kayar.
- Çizgi grafikler soldan sağa açılır, çubuklar sırayla yükselir, şelale adımları sırayla uzar.
- Fiyat bandı işaretleri yerine kayar; KPI eğilim çizgileri bir kez çizilir.

**Doğrulama:**
- 293 birim/entegrasyon (yeni: `tests/integration/test_pro_redesign.py`) ve 11 E2E testi yeşil; `ruff` temiz.
- 180 görünümde 0 konsol hatası, 0 taşma, 0 kontrast ihlali, 0 etiketsiz alan (`docs/screenshots/after`, güncel durum).
- `scripts/record_tour.py` 45 ekranı gezip sınayarak tur videosu kaydediyor.
