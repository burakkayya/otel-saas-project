# Açık Konular, Riskler ve Sonraki Adımlar

Tarih: 1 Kasım 2026. Öncelik: **K** = canlıya geçmeden önce kritik, **Y** = yüksek, **O** = orta.
Yapılanlar için: [`YAPILANLAR.md`](YAPILANLAR.md).

## 1. Veri kaynakları ve hukuk

| # | Konu | Öncelik | Durum / ne yapılmalı |
|---|---|---|---|
| 1.1 | **Amadeus Self-Service kapandı.** Amadeus, self-service geliştirici portalını ve API anahtarlarını 17 Temmuz'da (2026) devre dışı bıraktığını duyurdu; Enterprise API'ler etkilenmiyor. Dokümandaki "uçuş arama trendi (Amadeus self-service)" varsayımı artık geçerli değil. | K | `AmadeusClient` kodda duruyor ama self-service anahtarı alınamaz. Seçenekler: Amadeus Enterprise sözleşmesi, başka bir uçuş arama/rezervasyon trendi kaynağı ya da talep skorunda uçuş ağırlığını (%45) etkinlik ve tatile dağıtmak. Karar verilene kadar canlı modda uçuş bileşeni **nötr (50)** çalışır; sahte veri kullanılmaz. |
| 1.2 | Makcorps / Caviar yanıt formatı doğrulanmadı (doküman açık soru #1, #2). | K | `live.py` savunmacı ayrıştırıcıyla yazıldı; alan adları `RATE_FIELD_CANDIDATES` ile ayarlanır. İlk gerçek yanıtla `tests/unit/test_live_clients.py` içindeki örnekler güncellenmeli. **Kalan oda bilgisi** hangisinde var test edilmeli; yoksa öneri motoru yalnızca fiyat sinyaliyle çalışır (kod buna hazır, `available_rooms` boş olabilir). Uç nokta yolları (`/city`, `/hotel`) ve tek istekte kaç tarih döndüğü netleşmeli. |
| 1.3 | Veri kaynaklarının yasal durumu ve ticari kullanım koşulları (doküman 9.1, 11). | K | Yönetim paneli → **Yasal kontrol listesi** 7 madde, hiçbiri tamamlanmadı. Her madde için yazılı kanıt notu zorunlu tutuldu. |
| 1.4 | PredictHQ Developer Plan'ın ticari kullanım kapsamı. | Y | Teyit edilmeli; uygun değilse ücretli plana geçiş maliyeti birim ekonomisine eklenmeli. |
| 1.5 | Google Places önbellekleme/saklama kısıtları (konum bir kez çekilip saklanıyor). | Y | Google kullanım koşullarına göre `lat/lng` saklama süresi ve `place_id` dışı alanların saklanması kontrol edilmeli. |
| 1.6 | KVKK: aydınlatma metni, gizlilik politikası, kullanım koşulları **taslak**. | K | Hukukçu onayı; VERBİS kaydı gerekip gerekmediği; veri işleme sözleşmesi (LLM ve barındırma sağlayıcıları için). |
| 1.7 | LLM ile oda eşleme hangi servisle yapılacak (doküman açık soru #6). | O | Kod Anthropic Messages API'si için yazıldı (`LLM_API_KEY`, `LLM_MODEL`); yalnızca oda adı gönderiliyor. Maliyet ve gizlilik değerlendirmesi yapılmalı. Anahtar yoksa belirsiz adlar "Diğer" + inceleme kuyruğu. |
| 1.8 | Booking.com ve aggregator verisinin ticari kullanımı. | K | Kaynak API'nin hangi OTA'lardan veri sağladığı ve yeniden kullanım hakkı yazılı olarak teyit edilmeli. |

## 2. Ürün ve iş modeli

| # | Konu | Öncelik | Durum |
|---|---|---|---|
| 2.1 | Abonelik fiyatları (€49 / €129 / €349) **yer tutucu**. | Y | Yönetim → API ve maliyet ekranındaki hesaplayıcı hazır; ama sağlayıcı birim fiyatları da yer tutucu. Gerçek fiyatlar girilince marjlar yeniden hesaplanmalı (doküman açık soru #3). |
| 2.2 | Tam bölge taraması maliyeti. | Y | Kontrol grubu (DiD) için tüm pilot bölge taranıyor (`scan_scope = all`). Maliyet yüksekse Sistem ekranından `compset` moduna geçilebilir; o zaman etki ölçümü yapılamaz. |
| 2.3 | Pilot otellerin bulunması (açık soru #4) ve kontrol grubu seçimi (#5). | Y | Kod tarafı hazır (±1 yıldız, aynı il). Bölge başına 10-15 kontrol oteli şartı arayüzde gösteriliyor; seçim kriterleri pilotla birlikte netleşmeli. |
| 2.4 | Öneri motorunun kalibrasyonu. | Y | Demo veride öneri bazı otellerde "bugünkü medyanı kopyala" kıyasını geçemiyor. Gerçek veriyle backtest yapılıp ağırlıklar (Yönetim → Öneri modeli → deneme backtest) ayarlanmalı. |
| 2.5 | Ödeme altyapısı yok. | O | Faturalar ve abonelik durumları elle yönetiliyor. iyzico / Stripe vb. entegrasyonu, e-fatura/e-arşiv. |
| 2.6 | E-posta gönderimi yok. | O | Parola sıfırlama talebi denetim kaydına düşüyor ama e-posta gitmiyor; "önemli öneri" ve haftalık özet e-postaları gönderilmiyor (panel bildirimi var). SMTP / transactional e-posta servisi seçilmeli. |
| 2.7 | Oda kategorisi sınırı ve öneri ufku paket bazında. | O | Rakip sayısı ve ufuk paketle sınırlı; oda kategorisi sınırı (`max_room_types`) henüz uygulanmıyor. |
| 2.8 | Ürün adı. | O | "OtelRadar" çalışma adıdır; marka tescil kontrolü yapılmadı. `APP_NAME` ile değişir. |

## 3. Algoritma ve veri

| # | Konu | Öncelik | Durum |
|---|---|---|---|
| 3.1 | Dini bayram ve okul tatili tarihleri yaklaşık. | Y | `app/services/calendar_tr.py` içinde 2025-2027 elle girildi. Diyanet ve MEB takvimiyle doğrulanmalı veya PredictHQ `public-holidays/school-holidays` kategorisinden alınmalı. |
| 3.2 | Vergi kapsamı normalizasyonu (KDV, konaklama vergisi) (doküman 9.1). | Y | **Yapılmadı.** Kaynağın fiyatları vergili mi vergisiz mi döndürdüğü netleşmeden normalize edilemez. Gelen fiyat olduğu gibi EUR'a çevriliyor. |
| 3.3 | Enflasyon kaynaklı kaymaların ayrıca izlenmesi. | O | Tüm fiyatlar EUR'a çevriliyor; TL bazlı ayrı enflasyon takibi yapılmıyor. |
| 3.4 | Oda tipi başına tek fiyat. | O | Aynı kategoride birden çok oda tipi varsa en ucuz satılabilir fiyat kullanılıyor; iptal koşulu / pansiyon tipi (oda-kahvaltı, her şey dahil) ayrımı yok. Resortlar için **pansiyon tipi** önemli; kaynak API'de varsa eklenmeli. |
| 3.5 | Gelişmiş zaman serisi modelleri. | O | Bilinçli olarak kapsam dışı (doküman 2.3); veri biriktikçe değerlendirilecek. |
| 3.6 | Uçuş talebi endeksinin aylık çözünürlüğü. | O | Amadeus analitiği aylıktı; yeni kaynak seçilince günlük/haftalık çözünürlük tercih edilmeli. |
| 3.7 | Geçmiş veri. | O | Gerçek veriyle backtest ve mevsim katsayısı için en az birkaç aylık birikim gerekir; ilk haftalarda katsayılar bölgesel ön bilgiye dayanır. |

## 4. Teknik

| # | Konu | Öncelik | Durum |
|---|---|---|---|
| 4.1 | Veritabanı göçleri (migration). | Y | Şimdilik `create_all` kullanılıyor. Canlıya geçmeden Alembic eklenmeli; şema değişiklikleri sürümlenmeli. |
| 4.2 | Docker imajı bu ortamda derlenemedi. | O | Geliştirme ortamında Docker Hub erişimi kapalı olduğu için `docker compose build` burada çalıştırılamadı; compose dosyası doğrulandı ve `scripts/start.sh` yerel PostgreSQL'e karşı başarıyla denendi. İlk `docker compose up --build` sizin makinenizde doğrulanmalı. |
| 4.3 | Harici sistemler için API kimlik doğrulaması. | O | JSON API şu an oturum çereziyle çalışıyor; PMS/kanal yöneticisi entegrasyonları (Faz 4) için API anahtarı / OAuth gerekir. |
| 4.4 | Giriş denemesi sınırlayıcısı bellek içi. | O | Tek süreçte doğru çalışır; birden çok sunucu kopyasında Redis vb. paylaşımlı depo gerekir. |
| 4.5 | Yedekleme, izleme, hata takibi. | O | PostgreSQL yedekleme planı, Sentry vb. hata takibi, uptime izleme kurulmalı. |
| 4.6 | Arka plan işleri web sürecinde. | O | Yönetim panelinden tetiklenen işler web sürecinde arka planda çalışıyor; uzun işler için kuyruk (RQ/Celery) düşünülebilir. Zamanlanmış işler ayrı `worker` servisinde. |
| 4.7 | Çoklu kullanıcı / otel zinciri. | O | Bir otele birden çok kullanıcı eklenebiliyor ama zincir (bir hesapta birden çok otel) yapısı yok. |
| 4.8 | Yazı tipleri ve Chart.js yerel. | — | İnternet bağlantısı olmadan da arayüz tam çalışır (Google Fonts bağımlılığı kaldırıldı). |

## 5. Doküman yol haritasına göre durum

- **Faz 1 (MVP):** veri katmanı, compset, oda eşleme, fiyat önerisi v1, panel, backtest raporu: **tamam** (demo veriyle).
  Talep verisi: PredictHQ istemcisi hazır; Amadeus için kaynak kararı gerekli (madde 1.1).
  Birim ekonomisi hesabı: araç hazır, gerçek fiyatlar girilmeli.
- **Faz 2:** ölçüm paneli ve kontrol grubu: **kod hazır**; pilot oteller ve gerçek veri gerekiyor.
- **Faz 3-4:** Antalya pilotu (kod iki ili de destekliyor), Türkiye geneli, PMS entegrasyonu, kesin ROI: açık.

## 6. Hemen yapılacaklar (önerilen sıra)

1. Makcorps ve Caviar için birer örnek yanıt alın; kalan oda bilgisini ve vergi kapsamını kontrol edin (1.2, 3.2).
2. Uçuş talebi için Amadeus yerine kaynak kararı verin (1.1).
3. Yasal kontrol listesini kanıtlarıyla doldurun (1.3, 1.6, 1.8).
4. Sağlayıcı birim fiyatlarını girip paket fiyatlarını birim ekonomisine göre belirleyin (2.1).
5. Alembic'i ekleyin, ardından `DATA_PROVIDER=live` ile Muğla'da sınırlı bir canlı tarama başlatın.
