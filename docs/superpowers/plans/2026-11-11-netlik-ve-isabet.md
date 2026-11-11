# Netlik ve isabet turu

Tarih: 11 Kasım 2026. Dal: `feat/netlik-ve-isabet`.

## İncelenen ürünler ve çıkarılan dersler

| Ürün | Ne yapıyor | Bizde karşılığı |
|---|---|---|
| RoomPriceGenie | Tarihe tıklayınca tek cümlelik neden ("Behind expected occupancy…", "Your minimum price is holding you back"); beklenen doluluk ve beklenen pickup ile karşılaştırma; ±%4 içindeki değişiklikleri "aynı kalır" sayıyor; açıklamalar hazır senaryolardan, üretken yapay zekâ yok | Ana neden başlığı, "Koru" bandı (±%3), kendi sınırının öneriyi tuttuğunu söyleme, beklenen doluluk |
| PriceLabs | Pacing: gelecekteki tarihin doluluğu, referans tarihlerin **aynı rezervasyon penceresindeki** doluluğuyla kıyaslanır; pickup; beklenen geliri en çoklayan fiyat | Kalan güne göre beklenen doluluk eğrisi (pace) |
| Lighthouse | Renkli takvim, pace görünümü, öneri kırılımı, tek tıkla uygulama | Tek fiil rozetleri; pace çizgisi doluluk grafiğinde |
| happyhotel, TakeUp, Lybra | Etkenleri ve ağırlıklarını gösterme; her değişiklik sonrası gözlem penceresi | Etken listesi ve şelale zaten var; sonuç ölçümü `stay_outcomes` ile yapılıyor |

Ortak bulgu (RoomPriceGenie 2026 anketi, satıcı kaynağı): otelci fiyatın neden değiştiğini anlamazsa öneriyi sorguluyor ya da eziyor.

## Motor

1. **Rezervasyon hızı (pace).** Otelin son 90 gündeki sonuçlanmış konaklama günlerinden, kalan güne göre beklenen
   doluluk eğrisi çıkarılır (hafta içi ve hafta sonu ayrı; kova medyanları; sezon katsayısı oranıyla düzeltme).
   Doluluk beklenenin 20 puan önündeyse +%7, gerisindeyse −%7 (`pace` ağırlığı). Göreli doluluk ağırlığı 0,08'den
   0,05'e indi (iki sinyal aynı şeyi iki kez saymasın).
2. **Benzerlik ağırlıklı rakip dağılımı.** Medyan ve yüzdelikler ağırlıklı hesaplanır: ağırlık = 0,5 + benzerlik
   skoru; otelin onayladığı ya da elle eklediği rakip ×1,25.
3. **Tek fiil.** Her öneri `raise` / `lower` / `hold` / `set` taşır. Öneri mevcut fiyata ±%3'ten yakınsa "Koru".
4. **Ana neden başlığı.** Senaryo kodu + tek cümle. Başlık her zaman fiille aynı yöndedir; yönü uyan sinyal yoksa
   fiyatın pazara göre konumu söylenir. Otelin kendi minimum/maksimum fiyatı öneriyi tutuyorsa bu söylenir ve sınır
   olmasa çıkacak fiyat verilir.
5. Model sürümü `v1.2-pace`. Yönetim formu kaydedilirken formda olmayan ağırlıklar artık korunuyor.

## Ekranlar

- **Panel:** kahraman alanda ana neden başlığı; hemen altında **"Önce bunlara bakın"** (önümüzdeki 21 günde en
  öncelikli 5 gün: tarih, fiil, eski → yeni fiyat, neden). Öncelik = fark × satılacak oda payı × tarihe yakınlık.
  Doluluk bölümü "Ayrıntılı" görünüme alındı; grafiğe "normalde beklenen" çizgisi eklendi.
- **Fiyat önerileri:** sütunlar 9'dan 7'ye indi (Talep, Rakip medyanı ve Fark kalktı; "Ne yapmalı" ve "Neden"
  geldi). Başlık "N gün yükseltin, M gün indirin, K gün koruyun". "Koru" satırları soluk. Süzgeç artık
  "değişiklik gerekenler".
- **Öneri ayrıntısı:** fiil rozeti, ana neden başlığı, bu tarihte beklenen doluluk.

## Yapılmayanlar (veri gerektiriyor)

- Fiyat esnekliği ve beklenen geliri en çoklayan fiyat: dönüşüm verisi yok. `stay_outcomes` biriktikçe
  "fiyat değişimi → rakiplere göre doluluk değişimi" eğrisi çıkarılabilir.
- Hafta günü katsayısı ayrı bir çarpan olarak eklenmedi: rakip medyanı ve pace eğrisi hafta sonunu zaten taşıyor.
