# İlk canlı veri testi (24–25 Kasım 2026)

Amaç: gerçek API anahtarlarıyla sistemi uçtan uca denemek, API haklarını az ve kontrollü kullanmak.

## Kapsam ve harcanan istek

Bodrum, 25 otel, 21 günlük ufuk, ayrı SQLite veritabanı (`data/live-test/`, git dışında).

| Sağlayıcı | İstek | Not |
|---|---|---|
| LiteAPI `data/hotels` | 1 (+1 yoklama) | Bodrum'da 720 kayıt; ilk 25 alındı |
| LiteAPI `hotels/rates` | 22 + 22 (iki tam tarama) + 4 yoklama | Tarih başına tek istek, 25 otel birlikte |
| PredictHQ `events` | 6 + 1 yoklama | |
| Google Places | 1 yoklama | Canlı hatta çağrılmadı: LiteAPI konumu zaten veriyor |
| ECB kur | 1 | Anahtarsız |
| DataForSEO | 1 (reddedildi, ücret 0) | Hesap doğrulanmamış (40104) |

Hiç hatalı istek yok. LiteAPI anahtarı **sandbox**; yanıtlar `sandbox: true` taşıyor.

## Ne çalıştı

- Kayıt → otel eşleştirme (LiteAPI kaydı %100 ad benzerliğiyle bulundu) → rakip seti → öneri → panel.
- 25 otelden 6'sında fiyat geldi; 19'unda teklif yok (Bodrum'da kış kapanması olabilir; sandbox kaynaklı da olabilir).
- Oda tipi eşleme: 37 oda tipinin 29'u kategoriye oturdu, 8'i "Diğer" (LLM anahtarı yok).
- Konsolda hata yok; panel, pazar, talep, yönetim ekranları canlı veriyle açıldı.

## Bulunan ve düzeltilen sorunlar

1. **Veri yokken uydurma fiyat.** Rakip fiyatı da kendi fiyatı da olmayan günlerde motor sabit €80'den €73 öneriyordu
   (Suite için bile). Artık o gün için öneri üretilmiyor.
2. **Yanlış "Rakip medyanı".** Kategoride rakip fiyatı yokken ekranda otelin kendi fiyatı "Rakip medyanı" diye
   gösteriliyordu; başlık "benzer oteller €X civarında" diyordu. Artık "—" ve "Bu kategoride rakip fiyatı yok; öneri
   kendi fiyatınız, talep ve sezona dayanıyor".
3. **Fiyatı olmayan rakipler.** Satış kanalında hiç fiyatı gözlenmemiş oteller benzerlik puanıyla rakip setine
   giriyordu. Artık verisi olanlar önce seçiliyor (yakında başka aday yoksa yine girebilir).
4. **Yunanistan etkinlikleri.** Muğla'nın 80 km çemberi Rodos'u kapsıyor; Yunan maçları talep skorunu yükseltiyordu.
   PredictHQ sorgusu `country=TR` ile sınırlandı.
5. **Küçük maçlar "Yüksek talep".** Etki puanı `local_rank`'ten geliyordu (kadın basketbol ligi maçı 73). Artık genel
   `rank` kullanılıyor.
6. **Oda adında pansiyon/iade.** "Studio Oda - Bed & breakfast - İade Edilemez" gibi adlar aynı odayı onlarca tipe
   bölüyordu; ayıklanıyor.
7. **±%3 sınırı.** −2,996 "−%3,0 Koru" görünüyordu; fiil artık yuvarlanmış yüzdeyle veriliyor.
8. **Maliyet ekranı** LiteAPI'yi göstermiyordu; birim ekonomisine eklendi.
9. **Testler** yerel `.env`'deki gerçek anahtarları okuyordu; artık okumuyor.

## Açık kalanlar

- **Kalan oda yok.** Ne LiteAPI ne DataForSEO kalan oda veriyor. Doluluk, rezervasyon hızı ve pazar sıkışması sinyalleri
  canlı veride boş; motor fiyat, talep ve sezonla çalışıyor. Çok odalı sorgu (1/3/5/9 oda) sandbox'ta hiç kesilmedi,
  yani bu yöntemle oda sayısı tespit edilemedi. Canlı anahtarla bir kez daha denenmeli.
- **Sandbox verisi gerçek mi?** Canlı (production) anahtarla aynı otel ve tarihlerde karşılaştırılmalı.
- **Pansiyon tipi** (BB / HB / AI) karışık: oda adı başına en ucuz teklif alınıyor; her şey dahil ile oda-kahvaltı aynı
  kıyasa girebiliyor (ACIK_KONULAR 3.4).
- **Uçuş sinyali** hâlâ nötr (50); talep skorunun %45'i boşta.
- **DataForSEO** hesabı doğrulanmalı.
- **Hukuk:** LiteAPI'yi izleme amaçlı kullanmak, arama/rezervasyon oranı (5000:1) ve kullanım koşulları.

## Yeniden çalıştırma

```bash
DATABASE_URL=sqlite:///./data/live-test/live.db DATA_PROVIDER=live LITEAPI_CITIES="Muğla:Bodrum" \
LITEAPI_MAX_HOTELS_PER_CITY=25 HORIZON_DAYS=21 .venv/Scripts/python.exe -m app.cli run-job daily_pipeline
```

Bir tam tarama yaklaşık 22 LiteAPI ve 3 PredictHQ isteği harcar.
