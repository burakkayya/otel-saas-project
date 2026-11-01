# Otel Dinamik Fiyatlandırma ve Rakip Analiz SaaS: Proje Dokümanı

Sürüm: 1.0
Tarih: 2026-10-29
Kapsam: Şimdiye kadar konuşulan tüm kararlar, kısıtlar, mimari, veri modeli, MVP planı ve açık riskler.

---

## 1. Proje Özeti

Otelin hiçbir iç sistemine (PMS, Channel Manager) bağlanmadan, otelden manuel veri istemeden çalışan, halka açık fiyat ve envanter verisiyle rakip analizi yapıp fiyat önerisi veren bir SaaS ürünüdür. Abone otel web sitesine üye olur, paket seçer ve günlük fiyat önerilerini alır.

**Nihai hedef (vizyon):** Türkiye genelinde tüm konaklama tesislerini kapsayan, abonelerin gelirini (RevPAR) artıran, ölçülebilir sonuç üreten bir fiyat öneri platformu.

**İlk sürüm hedefi (MVP):** Muğla ve Antalya pilot bölgelerinde, compset + oda tipi eşleme + fiyat önerisi + talep sinyali + backtest raporu. Süre: 1 ay. Geliştirici: tek kişi, ağırlıklı kodlama.

---

## 2. Kısıtlar

### 2.1 Orijinal mimari kurallar (ürün şartnamesinden)

| Kural | Açıklama | Durum |
|---|---|---|
| Sistem entegrasyonu yok | Abonenin PMS/Channel Manager'ına bağlantı yok | Geçerli |
| Manuel girdi yok | Otelden doluluk, satış, rakip fiyatı istenmez | Geçerli |
| Scraping yok | Yalnızca yasal, bireysel geliştirici erişimli resmi API'ler | Kullanıcı yasal durumu teyit etti. Yazılı kanıt saklanmalı (bkz. 9.1) |
| %100 Türkiye kapsamı | Tüm tesisler listelenebilmeli | Vizyon olarak kalır. MVP kapsamı değil (bkz. 2.3) |

### 2.2 Kullanıcı tarafından netleştirilen kararlar

- Hedef müşteri kitlesi: butik otel ve pansiyonlar, orta ölçek oteller, zincir ve resort oteller (vizyonda hepsi, MVP'de pilot bölge ile sınırlı).
- MVP kapsamı: compset + oda tipi eşleme + fiyat önerisi + talep verisi (Amadeus, PredictHQ).
- Geliştirici: tek kişi, ağırlıklı kodlama.
- Pilot bölgeler: Muğla ve Antalya.
- MVP süresi: 1 ay.
- Teknik yapı: Kullanıcı karar vermedi, asistan önerdi (bkz. 4).
- ROI paneli: Otelin verisini beklemeden, API üzerinden teyit edilen satışlara dayanarak şimdilik yapılacak. Ancak ana iddia olarak sunulmayacak (bkz. 6).

### 2.3 Bilinçli olarak kapsam dışı bırakılanlar (MVP)

- Türkiye geneli kapsam (yalnızca Muğla ve Antalya)
- PMS / Channel Manager entegrasyonu
- Oda kapanma ve kayıp tespiti üzerinden kesin gelir hesabı
- Otelin kendi satış verisine dayanan ROI
- Frontend framework'ü (FastAPI + basit şablonlar yeterli)
- Karmaşık zaman serisi modelleri (ilk aşamada ortalama ve yüzdelik yaklaşımı)

---

## 3. Ürün Akışı (Abone Otel Açısından)

1. **Kayıt ve paket seçimi:** Otel adı ve adresi girilir. Başka veri istenmez.
2. **Otomatik profil:** Google Places'ten konum, yıldız sınıfı ve tip çekilir. Oda sayısı mümkünse alınır.
3. **Compset:** Sistem 5 rakip önerir. Otel listeyi değiştirebilir.
4. **Günlük tarama:** Rakiplerin fiyat, oda tipi ve kalan oda verisi toplanır. Oda tipleri Standard, Deluxe, Suite, Family kategorilerine eşlenir.
5. **Talep sinyali:** Uçuş arama trendi (Amadeus), etkinlik ve tatil skoru (PredictHQ) hesaplanır.
6. **Öneri:** Her oda tipi ve stay date için önerilen fiyat, taban ve tavan ile gerekçesiyle gösterilir.
   Örnek: "Rakip medyan fiyat bu hafta %12 arttı, talep skoru yüksek, öneri +%8, taban X, tavan Y."
7. **Uygulama ve ölçüm:** Otel fiyatı kendi sisteminde değiştirir. Sistem fiyat takibi yapar ve sonuçları raporlar.

**Önemli sınır:** Sistem otelin PMS'ine bağlı olmadığı için fiyatı otel kendisi uygular. Öneri ne kadar iyi olursa olsun, uygulanmazsa sonuç oluşmaz. Ürünün başarısı hem algoritmaya hem de otelin kullanım alışkanlığına bağlıdır.

---

## 4. Teknik Mimari

### 4.1 Teknoloji yığını (öneri)

| Katman | Teknoloji | Gerekçe |
|---|---|---|
| Dil | Python 3.12 | Veri ve analiz ekosistemi |
| Web/API | FastAPI | Hafif, hızlı, tek kişi için yeterli |
| Veritabanı | PostgreSQL | İlişkisel model, zaman serisi için yeterli, JSONB desteği |
| Veri işleme | pandas | Mevsimsel katsayı ve ortalama hesapları |
| Zamanlama | APScheduler veya cron | Günlük ve saatlik veri çekme |
| Oda eşleme | Kural sözlüğü + LLM (yalnızca belirsiz kayıtlar) | Maliyet ve gecikmeyi düşük tutar |
| Arayüz | Jinja şablonları veya basit FastAPI sayfaları | Ayrı frontend gerektirmez |

### 4.2 Veri akışı

```
[RapidAPI: Makcorps/Caviar] ──┐
[Amadeus: uçuş arama trendi] ─┼─► Veri çekme (zamanlı) ─► PostgreSQL (ham veri)
[PredictHQ: etkinlik/tatil] ──┤                               │
[Google Places: konum (1 kez)]┘                               ▼
[Fixer/ExchangeRates: kur] ──────────────────────► Normalizasyon (EUR, oda eşleme)
                                                              │
                                                              ▼
                                  Compset ─► Fiyat öneri motoru ─► Öneri kayıtları
                                                              │
                                                              ▼
                                  Panel + backtest raporu + davranış takibi
```

### 4.3 Kullanılacak API'ler

| Amaç | Servis | Not |
|---|---|---|
| Otel fiyat, oda tipi, envanter | Makcorps veya Caviar (RapidAPI) | Ana veri kaynağı. Maliyeti en çok bu belirler. Hangisinin kalan oda bilgisi verdiği doğrulanmalı. |
| Uçuş arama talebi | Amadeus for Developers | Kullanıcı, self-service kapsamında bu verinin açık olduğunu belirtti. Yazılı teyit ve ticari kullanım koşulu saklanmalı. |
| Etkinlik ve tatil talebi | PredictHQ (Developer Plan) | Demand Impact Score için |
| Konum ve mesafe | Google Places, Distance Matrix | Bir kez çekilip saklanır. Google'ın önbellekleme ve saklama kısıtlarını kontrol edin. |
| Kur dönüşümü | Fixer.io veya ExchangeRatesAPI | Ortak para birimi (EUR) |

### 4.4 Maliyet uyarısı

Her otel için günlük birkaç istek, 100 otelde aylık istek sayısını hızla artırır. Abonelik fiyatı, birim maliyet (abone başına API maliyeti) hesaplanmadan belirlenmemelidir. İlk iş olarak bir maliyet tablosu çıkarılmalıdır.

---

## 5. Algoritma

### 5.1 Compset (rakip belirleme)

- Kaynak: Google Places konumu, yıldız sınıfı, tip ve oda sayısı (varsa)
- Puanlama: mesafe, yıldız farkı, oda tipi benzerliği, fiyat bandı yakınlığı
- Çıktı: 5 rakip, her biri için benzerlik skoru
- Abone manuel değişiklik yapabilir (`is_manual` alanı ile izlenir)
- Yakın rakip yoksa (izole otel): coğrafi yarıçap genişletilir, bölgesel talep skoru ağırlıklandırılır

### 5.2 Oda tipi eşleme

1. Kural sözlüğü: deluxe, suite, family, standard ve Türkçe karşılıkları
2. Belirsiz kayıtlar için LLM (yalnızca bu kayıtlar gönderilir)
3. Her eşleme `mapped_by` (rule, llm, manual) ve `confidence` ile saklanır
4. Kıyaslama yalnızca aynı kategori içinde yapılır

### 5.3 Mevsimsel katsayı

- MVP: geçmiş fiyat verisinden ay veya haftalık ortalama ve yüzdelik yaklaşımı
- Bölge bazlı: Bodrum (yaz yoğun), Kapadokya (dönemsel), Antalya (uzun sezon)
- Ölü sezonda taban fiyata yaklaşım, yüksek sezonda marj çarpanı artışı
- Veri birikince daha gelişmiş modeller değerlendirilir

### 5.4 Fiyat önerisi

- Girdiler: rakip medyan ve dağılımı, kalan oda sinyali, talep skoru, mevsim katsayısı
- Çıktılar: önerilen fiyat, taban, tavan, gerekçe (JSON)
- Taban ve tavan kuralları zorunludur. Öneri bu sınırların dışına çıkamaz.
- "Maksimum kâr" hedefi, ödeme istekliliği üst sınırının tahmini olarak uygulanır. Bu üst sınır ilk sürümde yalnızca rakip fiyat dağılımından türetilir. Dönüşüm verisi olmadığı için gerçek istekliliği ölçülmez. Bu, panelde açıkça belirtilmelidir.
- Her öneri `model_version` ile kaydedilir.

---

## 6. ROI ve Başarı Ölçümü (Revize)

Önceki taslakta yer alan "Satış Tespiti" ve "Kar Hesaplaması" yöntemi, kesin gelir iddiası olarak sunulmayacaktır. Gerekçe:

- Kalan oda sayısındaki düşüş bir satışın kanıtı değildir. Oda kapatma, başka kanal satışı, overbooking veya stop-sell aynı görüntüyü oluşturur.
- Fiyatın öneriyle eşleşmesi tesadüf de olabilir. Otelin fiyatı uygulaması, sistemin satışa etkisini kanıtlamaz.
- Otel bu rakamları sorguladığında savunulamaz.

### 6.1 Kabul edilen yaklaşım

**a) Öneriye uyum kaydı (davranış takibi, gelir iddiası değil)**
Otelin gözlenen fiyatı, önerinin ±%X tolerans bandında mı? Bu, sistemin kullanım oranını gösterir. `applied_observations` tablosunda tutulur.

**b) Kontrol grubu karşılaştırması (ana kanıt)**
Abone otelin ADR ve doluluk gelişimi, aynı bölgedeki abone olmayan benzer otellerle karşılaştırılır. Yöntem: fark-içinde-fark (difference-in-differences). Ölçüm için bölge başına en az 10-15 kontrol oteli gerekir. Aksi halde sonuç gürültülüdür.

**c) Etiketleme**
Panelde tüm rakamlar "tahmini etki" olarak etiketlenir. "Sıfırdan kurtarılan gelir" ve "ek kâr" gibi kesin gelir ifadeleri kullanılmaz. Her `roi_estimates` kaydı `is_estimate = TRUE` ile tutulur.

### 6.2 Başarı metrikleri

- Backtest: geçmiş verilerde önerilerin gerçekleşen doluluk ve gelirle uyumu (MVP'nin kanıtı)
- Pilot: abone ve kontrol grubu arasında RevPAR ve ADR gelişimi
- Compset isabeti: otelin "bu rakip gerçekten bizimle yarışır" dediği oran

Pilotta somut bir artış görülürse "ölçülmüş %X RevPAR artışı (tahmini, kontrol grubuna göre)" olarak sunulabilir.

---

## 7. Veri Modeli (PostgreSQL)

Şema taslağı aşağıdadır. `rate_snapshots` ve `inventory_events` tabloları, API yanıt formatı netleştikten sonra kesinleştirilecektir.

```sql
-- Oteller
CREATE TABLE hotels (
  id            BIGSERIAL PRIMARY KEY,
  source_id     TEXT UNIQUE,          -- RapidAPI/Makcorps tarafındaki otel kimliği
  name          TEXT NOT NULL,
  province      TEXT NOT NULL,        -- 'Muğla', 'Antalya'
  district      TEXT,
  lat           NUMERIC(9,6),
  lng           NUMERIC(9,6),
  star_rating   SMALLINT,
  room_count    INT,                  -- mümkünse, değilse NULL
  is_subscriber BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Oda tipleri (ham isim + standart kategori)
CREATE TABLE room_types (
  id            BIGSERIAL PRIMARY KEY,
  hotel_id      BIGINT NOT NULL REFERENCES hotels(id),
  raw_name      TEXT NOT NULL,
  category      TEXT CHECK (category IN ('standard','deluxe','suite','family','other')),
  mapped_by     TEXT CHECK (mapped_by IN ('rule','llm','manual')),
  confidence    NUMERIC(3,2),
  UNIQUE (hotel_id, raw_name)
);

-- Fiyat ve envanter gözlemleri (ham zaman serisi)
CREATE TABLE rate_snapshots (
  id              BIGSERIAL PRIMARY KEY,
  room_type_id    BIGINT NOT NULL REFERENCES room_types(id),
  stay_date       DATE NOT NULL,
  observed_at     TIMESTAMPTZ NOT NULL,
  price_original  NUMERIC(12,2),
  currency        CHAR(3),
  price_eur       NUMERIC(12,2),
  available_rooms INT,                -- kalan oda (API'de varsa)
  source          TEXT NOT NULL
);
CREATE INDEX ON rate_snapshots (room_type_id, stay_date, observed_at);

-- Rakip seti
CREATE TABLE competitor_sets (
  hotel_id             BIGINT NOT NULL REFERENCES hotels(id),
  competitor_hotel_id  BIGINT NOT NULL REFERENCES hotels(id),
  rank                 SMALLINT NOT NULL,
  similarity_score     NUMERIC(4,3),
  is_manual            BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (hotel_id, competitor_hotel_id)
);

-- Fiyat önerileri (her çalıştırmada kayıt, model sürümüyle)
CREATE TABLE price_suggestions (
  id              BIGSERIAL PRIMARY KEY,
  room_type_id    BIGINT NOT NULL REFERENCES room_types(id),
  stay_date       DATE NOT NULL,
  suggested_price NUMERIC(12,2) NOT NULL,
  price_floor     NUMERIC(12,2),
  price_ceiling   NUMERIC(12,2),
  rationale       JSONB,              -- rakip medyanı, talep skoru, katsayı
  model_version   TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Öneriye uyum takibi (ROI değil, davranış)
CREATE TABLE applied_observations (
  id              BIGSERIAL PRIMARY KEY,
  room_type_id    BIGINT NOT NULL REFERENCES room_types(id),
  stay_date       DATE NOT NULL,
  observed_at     TIMESTAMPTZ NOT NULL,
  observed_price  NUMERIC(12,2),
  suggestion_id   BIGINT REFERENCES price_suggestions(id),
  within_tolerance BOOLEAN,           -- önerinin ±%X bandında mı
  UNIQUE (room_type_id, stay_date, observed_at)
);

-- Envanter değişim olayları
CREATE TABLE inventory_events (
  id            BIGSERIAL PRIMARY KEY,
  room_type_id  BIGINT NOT NULL REFERENCES room_types(id),
  stay_date     DATE NOT NULL,
  observed_at   TIMESTAMPTZ NOT NULL,
  prev_count    INT,
  new_count     INT,
  event_type    TEXT CHECK (event_type IN ('drop','closed','reopen','unchanged'))
);

-- ROI tahminleri (her zaman tahmin olarak işaretli)
CREATE TABLE roi_estimates (
  id                      BIGSERIAL PRIMARY KEY,
  hotel_id                BIGINT NOT NULL REFERENCES hotels(id),
  period_start            DATE NOT NULL,
  period_end              DATE NOT NULL,
  method                  TEXT NOT NULL,        -- 'control_group_did', 'suggestion_uptake'
  estimated_revenue_delta NUMERIC(14,2),
  control_group_size      INT,
  confidence              TEXT CHECK (confidence IN ('low','medium','high')),
  is_estimate             BOOLEAN NOT NULL DEFAULT TRUE,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 8. Yol Haritası

### Faz 1: MVP (1 ay, Muğla öncelikli)

| Hafta | İş | Çıktı |
|---|---|---|
| 1 | Veri katmanı: PostgreSQL şeması, Muğla otel envanteri, günlük fiyat ve oda çekme, Google Places konum verisi (tek sefer) | Çalışan veri hattı |
| 2 | Compset (puanlama) ve oda tipi eşleme | Her otel için 5 rakip, eşlenmiş oda tipleri |
| 3 | Fiyat önerisi v1: rakip dağılımı, kalan oda sinyali, sınırlı mevsim katsayısı, taban ve tavan | Günlük öneri kayıtları |
| 4 | Basit panel, backtest raporu. Süre kalırsa Amadeus ve PredictHQ talep verisi | Backtest raporu, demo |

Kayma durumunda öncelik sırası: backtest > fiyat önerisi > compset > talep verisi > panel. Talep verisi ilk kesilecek kalemdir.

### Faz 2 (sonraki 1-2 ay)

- Muğla'da 5-10 pilot otel
- Talep verisi (Amadeus, PredictHQ) entegrasyonu
- Ölçüm paneli ve kontrol grubu (bölge başına 10-15 otel)

### Faz 3

- Antalya'nın eklenmesi
- Otel sınıflarına göre genişleme (butik, orta ölçek, resort)

### Faz 4

- Ekip büyümesi
- Türkiye geneli kapsam
- Entegrasyon seçenekleri (PMS bağlantısı, otelin kendi satış verisi)
- Otel satış verisi paylaştığında kesin ROI paneli

---

## 9. Riskler ve Açık Sorular

### 9.1 Riskler

| Risk | Etki | Önlem |
|---|---|---|
| Veri kaynağının hukuki durumu | Yüksek | Yasal teyidin yazılı kanıtı saklanmalı. Booking.com ve aggregator kullanım koşulları ayrıca okunmalı. |
| Amadeus veri erişimi ve ticari kullanım | Orta | Self-service kapsamı ve ticari kullanım koşulu yazılı olarak doğrulanmalı. |
| Tek kişi ve 1 aylık süre | Yüksek | Kapsam sert sınırlandı. Talep verisi ilk kesilecek kalem. |
| API maliyeti ölçeklenmesi | Yüksek | Birim ekonomisi hesaplanmadan abonelik fiyatı belirlenmez. |
| Kalan oda verisinin API'de olmaması | Yüksek | Makcorps ve Caviar yanıtları test edilmeli. Yoksa fiyat sinyali ile çalışılır. |
| ROI iddiasının otel tarafından itirazı | Yüksek | Tahmini etiketi, kontrol grubu yöntemi, backtest. |
| Küçük pansiyonların OTA'da olmaması | Orta | Kapsam OTA'da listelenen tesislerle sınırlıdır. Pazarlama dilinde açıkça belirtilmeli. |
| Kur ve enflasyon oynaklığı | Orta | Tüm fiyatlar EUR'a normalize edilir. Enflasyon kaynaklı kaymalar ayrıca izlenir. |
| Vergi karşılaştırma bozukluğu (KDV, konaklama vergisi) | Orta | Rakip fiyatları aynı vergi kapsamına normalize edilir. |
| Öneriyi otelin uygulamaması | Yüksek | Ürün deneyimi ve otel onboarding süreci tasarlanmalı. |

### 9.2 Açık sorular

1. Makcorps mu Caviar mı kullanılacak? Hangisinin kalan oda bilgisi verdiği test edilmeli.
2. Örnek API yanıtı paylaşılacak mı? (`rate_snapshots` ve `inventory_events` buna göre kesinleşecek.)
3. Abonelik fiyatı ve paket yapısı ne olacak? Birim maliyet tablosu çıkarılmadan belirlenemez.
4. Pilot oteller nasıl bulunacak? (Muğla'da 5-10 otel ile görüşme planı.)
5. Kullanılacak kontrol grubu nasıl seçilecek? (Bölge başına 10-15 benzer otel.)
6. Oda eşleme için LLM hangi servis olacak? Maliyet ve gizlilik değerlendirmesi gerekir.

---

## 10. Başarı Kriterleri

### MVP (1 ay) başarılı sayılır eğer:

- Muğla'da compset ve oda tipi eşleme çalışıyor
- Her otel için günlük fiyat önerisi, taban, tavan ve gerekçe üretiliyor
- Backtest raporu üretiliyor ve önerilerin geçmiş verilerle uyumu ölçülüyor
- API maliyeti ölçülmüş ve birim ekonomisi hesaplanmış

### Pilot (Faz 2) başarılı sayılır eğer:

- Abone otellerde öneriye uyum oranı ölçülüyor
- Kontrol grubuna göre RevPAR veya ADR farkı istatistiksel olarak gözlemlenebiliyor (ya da gözlemlenemediği açıkça raporlanıyor)

---

## 11. Yasal ve Teyit Kontrol Listesi

- [ ] Veri kaynağı (Makcorps / Caviar) kullanım koşulları yazılı olarak kaydedildi
- [ ] Booking.com ve aggregator verilerinin ticari kullanım durumu teyit edildi
- [ ] Amadeus self-service, Flight Search Volume erişimi ve ticari kullanım koşulları teyit edildi
- [ ] PredictHQ Developer Plan ticari kullanım kapsamı teyit edildi
- [ ] Google Places ve Distance Matrix önbellekleme ve saklama kısıtları kontrol edildi
- [ ] Kişisel veri (otel yetkilisi iletişim bilgisi) için KVKK uyumu değerlendirildi
- [ ] Abonelik sözleşmesi ve gizlilik politikası hazırlandı

---

## 12. Sonraki Adımlar

1. Yukarıdaki teyit listesini tamamlayın (özellikle veri kaynağı ve Amadeus).
2. Makcorps veya Caviar için örnek yanıt alın.
3. Hafta 1 başlar: PostgreSQL şeması, Muğla veri çekme iskeleti.
