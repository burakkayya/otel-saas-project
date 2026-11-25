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

---

# 2. bölüm: butik otel, kalan oda ve yeni kaynaklar (25 Kasım 2026)

Abone: **Dinc Pansiyon** (Bodrum merkez). Kapsam: pansiyona en yakın 25 otel (0–350 m), 21 günlük ufuk.
Ayrı veritabanı: `data/live-test/butik.db` (git dışında).

## Kalan oda nasıl bulundu

LiteAPI "kalan oda" alanı vermiyor; ama aynı otele **aynı oda tipinden N oda** istendiğinde, tip yeterli oda
yoksa teklif dönmüyor. Dinc Pansiyon, 5 Aralık:

| Sorgu | Sonuç |
|---|---|
| 1 oda | 6 oda tipi |
| 2 oda (tek tipten) | Economy, Luxury Balcony, Super Deluxe Sea View, Super Deluxe Family |
| 3 oda | yalnızca Economy |
| 4 oda | "no availability found" |

Yani o gece satış kanalında Economy'de en az 3, üç tipte 2, iki tipte 1 oda açık. 15 Temmuz 2027'de her tipten
yalnızca 1 oda vardı, Family hiç yoktu: yaz doluluğu görünüyor.

Sistemde: her tarih için önce 1 oda, sonra 2, 3, 5, 8 oda sorulur; merdivende yalnızca hâlâ oda veren oteller kalır ve
birden çok otel tek istekte sorulur. Değer **alt sınırdır** ve LiteAPI tedarikçisinin kontenjanıdır, otelin tüm odaları
değildir; 8 ve üstü "8" kaydedilir.

## Kaynaklar ve harcanan istek

| Kaynak | Ne için | İstek (tarama + yoklama) | Maliyet |
|---|---|---|---|
| LiteAPI | fiyat, oda tipi, kalan oda | 111 + ~12 | ücretsiz (oran sınırı 5000:1) |
| DataForSEO | Google fiyat takvimi, otel eşleştirme | 46 + 3 | ~0,30 $ |
| Travelpayouts | uçuş fiyat endeksi | 22 + 7 | ücretsiz |
| PredictHQ | etkinlik | 3 | plan dahilinde |
| ECB | kur | 1 | ücretsiz |
| SerpApi | yalnızca 1 yoklama | 1 | plan dahilinde |
| Google Places | kullanılmadı (konum LiteAPI'den) | 0 | – |

Hatalı istek yok. Tarama 9,6 dk sürdü; süreyi LiteAPI'nin istek başına ~5 sn yanıtı belirliyor.

## Sonuçlar

- 25 otelin 13'ünde fiyat var: 3'ü LiteAPI (oda tipi ve kalan oda ile), 10'u Google (kanal farkı düzeltilmiş).
  Kalan 12'si kışın kapalı ya da hiçbir kaynakta teklif yok.
- 591 fiyat gözleminin 368'inde kalan oda var (1–5 oda).
- Uçuş endeksi 29–72 arasında; 25 Kasım en yüksek (71,8).
- Panelde tahmini doluluk görünüyor ("sizde %0, rakiplerde %20"). Pansiyonun yakın ve uzak tarihlerde aynı sayıda odası
  açık olduğu için %0 çıkıyor; ufuk 21 gün olduğundan kota tahmini kaba.
- Dinc Pansiyon'un LiteAPI fiyatı (€98) çevresinden yüksek (Kale Hotel €28–35, The Hotel 48 €42–57, Google
  düzeltilmiş €28–55); konumlama endeksi üst sınırda (1,8). Motor kışın düşük talep nedeniyle %9–%14 indirim öneriyor.

## Bu testte bulunup düzeltilenler

1. **Tek rakip piyasa sayılıyordu:** deluxe kategoride tek rakip (€35) vardı, €126'lık odaya €32 (−%62) önerildi.
   Artık en az 2 rakip gerekir; kategoride konumlama yoksa standart odadaki konumlama kullanılır. Sonuç: −%13.
2. **Aynı kategoride tek fiyat:** €68 ve €96'lık iki standart odaya aynı €62 öneriliyordu. Artık her oda tipi
   kategorideki en ucuz odaya göre primini koruyor.
3. **"Benzer oteller €100 civarında"** rakip fiyatı değil, konumlamayla ölçeklenmiş düzeydi; metin "konumunuza göre piyasa
   düzeyi" oldu.
4. **Geçmişi olmayan rakipler** rakip setine öne alınıp geçmiş testini boşaltabiliyordu; artık önce geçmişi olanlar.

## Açık kalanlar

- LiteAPI anahtarı sandbox: kalan oda yönteminin canlı anahtarla teyidi.
- Google fiyatının kanal farkı oranı yalnızca 3 otelden hesaplandı; oynak olabilir.
- Tarama süresi (paralelleştirme), 60 günlük ufukta ~3 kat istek.
- SerpApi kodda kullanılmıyor (yedek kaynak olabilir).
- Hukuk: LiteAPI (izleme amaçlı kullanım, oran), DataForSEO (Google verisi), Travelpayouts (satış ortaklığı dışı kullanım).
