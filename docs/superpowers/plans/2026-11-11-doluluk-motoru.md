# Doluluk motoru, otomatik uygulama tespiti ve kârlılık geri beslemesi

Tarih: 11 Kasım 2026. Dal: `feat/doluluk-motoru`.

## İstek
- Abone otelin ve rakiplerin doluluğu öneri motorunun ana damarı olmalı.
- "Uyguladım" düğmesi kalkmalı; uygulanıp uygulanmadığını sistem tespit etmeli.
- Uygulanan önerilerin satışa ve gelire etkisi ölçülüp motor bu sonuçla beslenmeli.

## Gerçekçi sınır
Bir otelin kesin doluluğu yalnızca kendi PMS / kanal yöneticisi verisinde vardır. Rakipler için kesin doluluk
hiçbir yasal kaynakta yoktur (Lighthouse, STR gibi sağlayıcılar da tahmin ya da gönüllü veri kullanır). Bu yüzden
doluluk **tahmin** olarak üretilir, her zaman aralık ve güven düzeyiyle gösterilir.

## Yöntem: satış kanalı envanterinden doluluk tahmini
1. Her taramada oda tipi başına satışa açık oda sayısı (`available_rooms`) kaydedilir (rate shopping API'leri
   "kalan oda" bilgisini verir).
2. **Kanal kotası:** bir otelin aynı konaklama tarihi için gördüğümüz en yüksek açık oda toplamı. Uzak tarihlerde
   oda henüz satılmadığı için bu değer otelin o kanala açtığı kotaya yaklaşır. Konaklama tarihlerinin %90'lık
   dilimi alınır; aynı ayda yeterli tarih varsa ay bazında (sezon açılışları için).
3. **Tahmini doluluk** = 1 − (şu an açık oda / kanal kotası). Kanal payı ve toplam oda sayısı bu oranda
   sadeleşir; oda sayısı yalnızca satılan oda adedi ve gelir hesabında kullanılır.
4. Tüm oda tipleri kapalıysa "satışa kapalı" işaretlenir (dolu ya da stop-sell; ayırt edilemez).
5. Güven: gözlem sayısı ve kotanın kaç tarihten hesaplandığına göre; aralık ±6 / ±12 / ±20 puan.
6. Hız (pickup): son 7 günde aynı konaklama tarihi için doluluk değişimi.

## Motor
- Yeni girdiler: abone otelin tahmini doluluğu, rakiplerin medyan tahmini doluluğu.
- Göreli doluluk: abone rakiplerden doluysa fiyat yükselir, geride ise iner (ağırlık `occupancy`).
- Sıkışma: rakiplerin doluluğu %85'i aşınca ek artış; son 14 günde pazar %35'in altındaysa ek indirim
  (ağırlık `compression`).

## Uygulama tespiti
- Her (oda tipi, konaklama tarihi) için abone otelin satış kanalında gözlenen fiyatı öneriyle karşılaştırılır.
- Durumlar: uygulandı (tolerans içinde), kısmen (aradaki farkın en az yarısı kapandı), uygulanmadı, gözlenmedi.
  Sonuç `stay_outcomes` tablosunda tutulur. "Uyguladım" düğmesi ve uç noktası kaldırılır.

## Kârlılık ve geri besleme
- Her karar birimi için karar anındaki ve sonraki doluluk (abone ve rakip) ile tahmini RevPAR ve
  **RevPAR endeksi (RGI)** hesaplanır: abone RevPAR / rakip medyan RevPAR.
- Panelde uygulanan ve uygulanmayan günlerin endeksleri karşılaştırılır (tahmini, güven düzeyiyle).
- Haftalık ayar: fiyat artışı uygulanan günlerde abone rakiplere göre pay kaybediyorsa artış ağırlıkları
  %10 kısılır; pay kaybı yok ve pazar doluysa %10 açılır. İndirim pay getirmiyorsa indirim tavanı kısılır.
  Ağırlıklar varsayılanın 0,5–1,5 katı arasında kalır; her değişiklik denetim kaydına yazılır.
