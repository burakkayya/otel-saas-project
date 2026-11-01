# Product

<!-- impeccable:product-schema 1 -->

> Kaynaklar: `docs/otel-fiyatlandirma-proje-dokumani.md` (v1.0), `docs/YAPILANLAR.md`, `docs/ACIK_KONULAR.md` ve
> 2 Kasım 2026 tarihli iş tanımı (kitle, ana iş ve ton orada kullanıcı tarafından verildi). Görüşme turu yapılmadı;
> kullanıcı tüm adımlar için önceden onay verdi. Belgeden çıkarılan ama kullanıcının ayrıca teyit etmediği maddeler
> *(çıkarım)* olarak işaretlidir.

## Platform

web

## Users

- **Butik otel ve pansiyon sahipleri** (Muğla ve Antalya pilot bölgeleri): gelir yöneticisi yok, fiyatı sahibi ya da
  resepsiyon belirler. Sabah kahvesiyle telefondan veya resepsiyon bilgisayarından bakar. *(kullanım anı: çıkarım)*
- **Resort gelir yöneticileri**: birden çok oda kategorisi ve uzun ufukla çalışır; masaüstünde, tabloları ve dışa
  aktarımı kullanır.
- **OtelRadar yöneticileri** (iç ekip): abonelikleri, veri hattını, API maliyetini, oda eşleme kuyruğunu ve yasal
  kontrol listesini yönetir.

Ana iş: **"Bu gecenin fiyatı ne olmalı ve neden?"** sorusuna her sabah tek bakışta güvenilir bir cevap almak.

## Product Purpose

Otelin hiçbir iç sistemine (PMS, kanal yöneticisi) bağlanmadan ve otelden manuel veri istemeden, halka açık fiyat ve
envanter verisiyle her oda tipi ve konaklama tarihi için **önerilen fiyat, taban, tavan ve gerekçe** üretmek. Fiyatı
otel kendi sisteminde uygular; ürün uygulanıp uygulanmadığını (uyum) ve kontrol grubuna göre tahmini etkiyi ölçer.

Başarı: otelin öneriyi anlaması, güvenmesi ve uygulaması; backtest ve kontrol grubu ölçümünün dürüstçe raporlanması.

## Positioning

Entegrasyon yok, veri girişi yok: rakip seti, oda tipi eşleme, talep skoru ve fiyat önerisi tamamen halka açık veriden.
Her rakam gerekçesiyle ve belirsizliğiyle birlikte gösterilir; ürün gelir vaat etmez, ölçer.

## Operating Context

- Pilot bölgeler Muğla ve Antalya; MVP demo veri modunda çalışır (`DATA_PROVIDER=demo`), otel adları ve etkinlikler kurgusal.
- Günlük veri hattı sabah çalışır; öneriler 7–90 günlük ufukta, oda kategorisi bazında (Standart, Deluxe, Suit, Aile).
- Otel öneriyi kendi PMS/kanal yöneticisine elle girer, isterse panelde "Uyguladım" diye işaretler; CSV dışa aktarım vardır.
- Yönetim paneli aynı uygulamadadır; yönetici bir otelin panelini "yönetici görünümü" ile görebilir.

## Capabilities and Constraints

- FastAPI + Jinja şablonları, kendi CSS tasarım sistemi (`app/static/css/app.css`), Chart.js yerel. Ayrı frontend yok.
- **Harici CDN yok**: yazı tipleri ve Chart.js yerel sunulur; uygulama internetsiz de tam çalışır.
- Arayüz dili Türkçe; sayı, para ve tarih biçimleri Türkçe (€1.234, %12, 1 Kas Paz). Tüm fiyatlar EUR'a normalize.
- Açık ve koyu tema; masaüstü, tablet ve 390 px mobil desteklenir.
- Rakip sayısı ve öneri ufku paketle sınırlı; abonelik fiyatları (€49 / €129 / €349) yer tutucu.
- Ödeme, e-posta gönderimi ve gerçek veri kaynağı henüz yok (bkz. `docs/ACIK_KONULAR.md`).

## Brand Commitments

- Ürün adı **OtelRadar** (çalışma adı, tescil kontrolü yapılmadı).
- Ton: **sakin, güven veren, Türkçe**. Abartı, aciliyet ve satış dili yok.
- Görsel kimlik kullanıcı tarafından korunmak üzere sabitlendi: kireç beyazı zemin, liman laciverti kenar menü, Ege mavisi
  aksiyon rengi, begonvil rengi yalnızca fırsat vurgusu için, Bricolage Grotesque + Instrument Sans, imza öğe rakip radarı.
  Ayrıntılar `DESIGN.md` içinde.

## Evidence on Hand

- Demo veri: 72 kurgusal otel (Muğla 34, Antalya 38), ~187.000 fiyat gözlemi, 8 abone otel.
- Gerçek müşteri, referans, vaka çalışması veya ölçülmüş gelir artışı **yok**. Bunlar uydurulmamalı.
- Demo veride öneri motoru bazı otellerde "bugünkü medyanı kopyala" kıyasını geçemiyor; bu arayüzde dürüstçe gösteriliyor.

## Product Principles

1. **Dürüstlük önce gelir.** Kesin gelir iddiası yok ("ek kâr", "kurtarılan gelir" yasak); tüm etki rakamları "tahmini"
   etiketli ve güven düzeyiyle; kalan oda düşüşü satış olarak sunulmaz; demo veri uyarısı her ekranda kalır.
2. **Önce cevap, sonra gerekçe.** Her ekran önce "ne yapmalıyım" sorusunu, ardından "neden" sorusunu cevaplar.
3. **Sakin yoğunluk.** Gelir yöneticisi için veri yoğun, butik otel sahibi için okunur; ikisi aynı ekranda katmanlanır.
4. **Uygulamayı kolaylaştır.** Öneri uygulanmazsa sonuç oluşmaz; uygulama ve işaretleme adımları sürtünmesiz olmalı.

## Accessibility & Inclusion

- WCAG 2.1 AA kontrast; görünür klavye odağı; `prefers-reduced-motion` tercihine uyum (grafik animasyonları dahil).
- Durum renkleri her zaman ikon ve metin etiketiyle birlikte; renk tek başına anlam taşımaz.
- Grafiklerde tek y ekseni, sabit sırada kategorik renkler, 2+ seride lejant, kritik grafiklerde tablo görünümü.
- Form hataları açık ve Türkçe.
