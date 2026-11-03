# Arayüz denetimi (Impeccable critique + audit)

Tarih: 2 Kasım 2026 · Dal: `feat/impeccable-ui` · Kapsam: 45 ekran (herkese açık 11, otel paneli 17, yönetim 17)

## Yöntem

- **Critique, çift ajanlı:** Değerlendirme A (tasarım incelemesi) üç ayrı alt ajanla yürütüldü: herkese açık, otel paneli,
  yönetim. Değerlendirme B (dedektör + tarayıcı kanıtı) dördüncü, yalıtılmış bir alt ajanla yürütüldü. A, B'nin
  bulgularını görmeden tamamlandı.
- **Kanıt:** `scripts/ui_snapshots.py` her ekranı açık/koyu tema × 1440/390 px'te (180 görünüm) Playwright ile gezdi. Ölçülenler:
  - konsol hataları,
  - yatay taşma,
  - WCAG kontrastı,
  - adsız öğeler,
  - etiketsiz alanlar.

  Ham veri `docs/screenshots/before/report.json` içinde. `impeccable detect` hem kaydedilen HTML'ler hem de
  `app/templates` üzerinde çalıştırıldı.
- **Önem:** P0 engelleyici · P1 büyük (erişilebilirlik, dürüstlük, ana iş) · P2 orta · P3 cila.
- **Durum sütunu:** ✅ kapatıldı · ⏳ kısmen · ➖ bilinçli olarak ertelendi (gerekçesiyle).

## Sağlık puanları (Nielsen, önce)

| Alan | Puan | Bant |
|---|---|---|
| Herkese açık | 24/40 | Kabul edilebilir |
| Otel paneli | 26/40 | Kabul edilebilir |
| Yönetim paneli | 22/40 | Kabul edilebilir |

**Tasarım özgüllüğü:**
- **Güçlü (koru):**
  - kahraman "Bu gece" kartı,
  - fiyat bandı göstergesi (öneri ●, mevcut ◆, medyan |),
  - "Fiyat nasıl oluştu?" şelalesi,
  - pazar ısı ızgarası,
  - rakip radarı,
  - "Ne iddia ettiğimizi de, etmediğimizi de" bölümü,
  - backtest'te dürüst "öneri 5,7 puan daha kötü" satırı.
- **Zayıf:**
  - KPI + sparkline şablonu,
  - genel SaaS plan kartları,
  - auth ekranlarında duvar kâğıdına dönen radar,
  - koyu temada kaybolan liman laciverti paneller.

## Dedektör özeti (B)

| Kural | Sayı | Karar |
|---|---|---|
| low-contrast | 549 | Gerçek. Kaynağı ağırlıkla `--muted` (#758596, beyazda 3,78:1). |
| undersized-ui-text | 77 | Gerçek. Talep ısı takviminde 10,5 px gün etiketleri. |
| overused-font | 46 | **Yanlış pozitif.** Instrument Sans markanın sabitlenmiş yazı tipi. |
| side-tab | 46 | Kahraman kartın alt kenarındaki 5 px degrade şerit. Kaldırıldı. |
| repeating-stripes-gradient | 45 | **Yanlış pozitif.** Kesikli seri lejant örneği. |
| cramped-padding | 23 | Bilinçli. Tablolar panel kenarına yaslı (`.flush`). |
| skipped-heading | 3 | Gerçek. Veri hattı, talep ve takvim sayfalarında başlık seviyesi atlanıyor. |

**Tarayıcı ölçümleri:**
- JS hatası yok.
- Herkese açık 7 sayfada 390 px'te **111 px yatay taşma** var.
- Kontrast ihlali olan görünüm sayısı:
  - açık temada 300,
  - koyu temada 128.
- 56 etiketsiz form alanı var; hepsi yönetim panelinde.

---

## P1: büyük bulgular

| ID | Ekran(lar) | Bulgu | Düzeltme | Komut | Durum |
|---|---|---|---|---|---|
| A-01 | tüm ekranlar | `--muted` #758596 beyazda 3,78:1, zeminde 3,49:1. Etkilenen metinler: kırıntı, KPI altı, ipuçları, zaman damgaları, alt bilgi. | Belirteç #586878 (≥4,6:1). Koyu temada #9aabb9. | colorize | ✅ |
| A-02 | herkese açık 7 sayfa | 390 px'te üst menü 111 px taşıyor. | Kısa CTA ("Ücretsiz dene"), menü sarması, 560 px kırılımı. | adapt | ✅ |
| A-03 | herkese açık, giriş, kayıt, hata sayfaları | **Demo veri uyarısı yok** (dürüstlük kuralı). Tanıtım sayfası 72 kurgusal tesisi "izliyoruz" diye gerçekmiş gibi sunuyor. | Tek `ui.demo_banner` makrosu ile her düzende uyarı. Demo modda "72 örnek tesis (demo)" yazılsın. | harden, clarify | ✅ |
| A-04 | kayıt, hesap, abonelik, yönetim formlarının çoğu | `type` niteliği olmayan inputlar stil almıyor. Tarayıcı varsayılanıyla çiziliyorlar ve paketler/model ekranında panelden taşıyorlar. | `input:not([type])` seçicisi, `min-width:0`, gerekli yerde `inputmode="decimal"`. | harden, polish | ✅ |
| A-05 | yönetim (8 ekran, 56 alan) | Form etiketleri alanlara bağlı değil. | `for`/`id` eşlemesi; arama ve kanıt notu için `aria-label`. | harden | ✅ |
| A-06 | tüm ekranlar | Klavye odağı zayıf. Lacivert menü ve kahraman kart üstünde #1f5fa8 halka 2,27:1. Inputlar `outline:none` ile 1,17:1 halka kullanıyor. | `--focus` belirteci, koyu yüzeylerde açık halka, inputlarda 2 px halka, `.choice:focus-within`. | harden | ✅ |
| A-07 | koyu tema | Birincil düğmede beyaz/#4b8fdc 3,35:1. Menü sayacında 3,33:1. `badge.info` 4,01:1. Kahraman kart ve kenar menü zeminle birleşiyor (#0a141c / #0d1720). | `--brand-fill` (#2f6fbd), `--on-bougain`, `--info` #7fb0ec, yükseltilmiş liman laciverti #10283a. | colorize | ✅ |
| A-08 | herkese açık, sistem koyu teması | Marka yazısı `var(--harbour)` ile çiziliyor. Saklı tema tercihi yoksa okunmuyor (1,03:1). | `color: var(--ink)` | colorize | ✅ |
| A-09 | öneriler, takvim, panel, tanıtım | **Renk anlamları çatışıyor.** Önerilen fiyat düşüşü alarm kırmızısıyla gösteriliyor. Begonvil ise fırsat dışında da kullanılıyor: yönetici görünümü şeridi, "Bugün" çizgisi, KPI'lar. | Düşüş: nötr rozet + ok. Artış fırsatı: begonvil + ok. Takvim: begonvil ↔ gri-mavi. Yönetici şeridi: bilgi mavisi. | colorize | ✅ |
| A-10 | panel kahraman alanı, öneri ayrıntısı | Gerekçe 7 eşit ağırlıklı cümlecikten oluşan tek paragraf. Asıl etken ("konumlama endeksi") jargonun içinde kayboluyor. Güven rozeti kahraman alanda yok. | Gerekçeyi madde madde ayır (en etkili 3 madde). "Fiyat konumunuz" gibi sade etiketler kullan. Güven rozetini fiyatın yanına taşı. | clarify, typeset | ✅ |
| A-11 | backtest | Kalan oda düşüşü "Satış ilerlemesi" ve "Talep–satış korelasyonu" adlarıyla sunuluyor (**dürüstlük kuralı**). | "Kalan oda düşüşü (vekil)" ve "Talep–kalan oda düşüşü ilişkisi". | clarify | ✅ |
| A-12 | öneriler, panel "Bu hafta", oda tipleri, uyum, yönetim tabloları (390 px) | Telefonda Öneri, Fark, Uyguladım ve Güven sütunları ekran dışında kalıyor. Kaydırılabileceğine dair ipucu yok. | ≤560 px'te satırlar etiketli kartlara dönüşsün (`data-label`). Diğer tablolarda kenar solması + kaydırma ipucu. | adapt | ✅ öneri, bu hafta, oda tipleri kart; diğer tablolar kenar ipucu |
| A-13 | rakipler (1440) | Onay/ret düğmeleri panel kenarında kesiliyor. | Benzerlik dökümü ikinci satıra; `min-width`'ler gevşetilsin. | layout | ✅ |
| A-14 | kayıt eşleştirme | ≥%50 eşleşmede ilk aday (farklı ilçe) **önceden seçili** geliyor. Yanlış otele bağlanma riski var. | Yalnızca ≥%85 eşleşme **ve** aynı ilçe varsa önceden seç; yoksa seçim zorunlu olsun. İlçe belirgin gösterilsin. | harden | ✅ |
| A-15 | tanıtım, paketler | Paket iddiaları veriyle çelişiyor: "Sınırsız oda kategorisi" (gerçekte 8), "Günlük e-posta özeti" (e-posta altyapısı yok), "5 rakip / 60 gün" (paketlere göre 5–12 / 30–90). | Özellik maddeleri paket sütunlarından üretilsin. E-posta "yakında" olarak işaretlensin. Sayılar aralık olarak verilsin. | clarify | ⏳ metinler sınırlarla tutarlı ve eski varsayılanlar taşınıyor; maddeler hâlâ serbest metin (sütunlardan üretilmiyor) |
| A-16 | yönetim: abonelik, fatura, kullanıcı, eşleme, iş çalıştırma | Geri alınamaz işlemlerde onay yok. Yönetici kendi hesabını devre dışı bırakma düğmesini görüyor. | `data-confirm` ile sonucu açıklayan metin; kendi satırında düğme gizlensin. | harden | ✅ |
| A-17 | yönetim etki, otel ayrıntısı | "Tahmini toplam" dönemsiz ve aralıksız tek nokta değer. Kayıp değerin yanında yeşil "Anlamlı" ve "Yüksek güven" rozetleri var. | Dönem ve ±2 SH aralığı. Anlamlılık ve güven nötr/bilgi tonunda. Otel ayrıntısında da anlamlılık gösterilsin. | clarify | ✅ |
| A-18 | tüm formlar | Hatalar yalnızca özet kutusunda; alan düzeyinde ilişki yok. Hata bildirimleri 7 sn'de kayboluyor (WCAG 2.2.1). | Hata/uyarı kutuları kendiliğinden kapanmasın. `aria-invalid` ve alan altı hata metni. Hata özeti alana bağlansın. | harden | ⏳ bildirimler kalıcı, eşleştirme seçimi zorunlu; alan bazlı `aria-invalid` yönlendiricilerde yok |
| A-19 | mobil menü | Kapalı çekmecedeki bağlantılar sekme sırasında kalıyor. `aria-expanded` ve Esc ile kapatma yok. | Kapalıyken `visibility:hidden`, `aria-expanded`/`aria-controls`, Esc, odağın geri dönmesi. | harden | ✅ |
| A-20 | sol menü "Çıkış yap" | Üzerine gelindiğinde metin zeminle 1,2:1. | Kenar menüye özel hayalet hover. | polish | ✅ |

## P2: orta bulgular

| ID | Ekran(lar) | Bulgu | Düzeltme | Komut | Durum |
|---|---|---|---|---|---|
| B-01 | tüm grafikler | Chart.js animasyonu `prefers-reduced-motion` tercihini yok sayıyor. | Tercih varsa `animation:false`, yoksa 250 ms. | animate | ✅ |
| B-02 | tüm uygulama | Her sayfada kademeli giriş animasyonu (orkestralı yükleme); radar taraması sonsuz döngüde. | Sayfa animasyonu kaldırılsın; radar tek tur taransın (tek "imza anı"). | animate, quieter | ✅ |
| B-03 | panel kahraman | Alt kenarda dekoratif degrade şerit (dedektör: side-tab). | Kaldırılsın. | quieter | ✅ |
| B-04 | talep, uyum, yönetim MRR, otel ayrıntısı | Kritik grafiklerde tablo görünümü yok. Otel ayrıntısında kategori renkleri sabit sırada değil. | `details.table-view` eklensin; renkler kategori anahtarına göre atansın. | harden | ✅ |
| B-05 | demo şeridi | Metin geliştiriciye hitap ediyor (".env"). 390 px'te 3 satır kaplıyor. | Otel kullanıcısına kısa metin; `.env` notu yalnızca yönetim panelinde. | clarify | ✅ |
| B-06 | panel | "Önümüzdeki 60 gün" rozetleri aslında 30 günü sayıyor. Tahmini etki kartında birim ve dönem yok; anlamsız fark büyük puntoyla öne çıkıyor. | Rozet etiketi doğru gün sayısını yazsın. Kart "Anlamlı fark yok" ile başlasın, değer küçük ve birimiyle verilsin. | clarify | ✅ |
| B-07 | ayarlar, paketler | E-posta bildirimi seçeneği ve "Günlük e-posta özeti" vaadi var; altyapı yok (dürüstlük). | Seçenek "yakında" olarak işaretlensin. | clarify | ✅ |
| B-08 | hata sayfaları | 403 sayfası oturum açmış kullanıcıya "14 gün ücretsiz dene" gösteriyor. Geri dönüş `javascript:history.back()` ile yapılıyor. | `user` şablona geçsin; "Panele dön" birincil aksiyon olsun. | clarify | ✅ |
| B-09 | giriş/kayıt mobil | ≤900 px'te yan panelle birlikte marka, ana sayfa bağlantısı ve tema düğmesi de kayboluyor. | Kompakt mobil üst bilgi. | adapt | ✅ |
| B-10 | tablolar | `th.num` sağa hizalanmıyor (özgüllük sorunu). | `table.data th.num`. | polish | ✅ |
| B-11 | talep ısı takvimi | Gün etiketleri 10,5 px. Geçmiş günler opaklıkla soluklaştırıldığı için 2,05:1. | ≥11,5 px; geçmiş renkle ifade edilsin. | typeset | ✅ |
| B-12 | öneri takvimi | Beyaz metin kırmızı karışımda 2,7–4,0:1. | Renk gücü üst sınırı %45 ve koyu metin. | colorize | ✅ |
| B-13 | yönetim | Ham kodlar ekranda: `active`, `festivals`, `impersonate_hotel`, iş anahtarları. Inputlarda noktalı ondalık ("49.0"). | Türkçe etiket haritaları, virgüllü ondalık. | clarify | ⏳ iş adları, abonelik durumu Türkçe; denetim işlem kodları ve etkinlik kategorileri hâlâ ham |
| B-14 | yönetim | Veri hattı ekranında 7 birincil düğme var ve sayfa 4 sn'de bir yeniden yükleniyor (odak ve kaydırma sıfırlanıyor). | Yalnızca günlük iş birincil kalsın; yenilemeden önce sayfa görünür ve etkileşimsiz olsun. | harden | ⏳ tek birincil düğme; 4 sn'lik tam sayfa yenileme duruyor |
| B-15 | yönetim | Boş durumlar tutarsız ("Kayıt yok."). Kullanıcı aramasında sonuç yoksa boş tablo kalıyor. | `ui.empty` makrosu ve bir sonraki adım önerisi. | onboard | ✅ veri hattı, denetim, kullanıcı araması |
| B-16 | hoş geldiniz | Rakip seti adımı yalnızca rakip var diye "tamam" sayılıyor. "İyi satışlar!" satış dili taşıyor. | Adım durumu gerçek işaretlere bağlansın; sakin bir kapanış metni. | onboard | ➖ hoş geldiniz adımlarının gerçek durumu ertelendi |
| B-17 | radar | Lejant yok; nokta numaraları ~7 px. Panelde adlar yalnızca fareyle görünüyor. | Lejant (Oteliniz ◆, otomatik rakip, sizin eklediğiniz), daha büyük numara. | clarify | ✅ |
| B-18 | KVKK kutusu | "okudum ve kabul ediyorum": aydınlatma metni kabul edilmez, bilgilendirme içindir. | "okudum, bilgilendirildim". | clarify | ✅ |
| B-19 | `.seg` sekmeleri | `role="tablist"` var ama sekme rolleri yok. | `role="group"` + `aria-current`. | harden | ✅ |
| B-20 | yönetim panosu | "-0,0 puan" ASCII tire ile yazılıyor. Grafik ipuçlarında da tire var. | İşaretli sayı süzgeci (U+2212); grafik biçimleyicisi. | polish | ✅ |
| B-21 | gezinme | Atlama bağlantısı yok; her sayfanın meta açıklaması aynı. | "İçeriğe geç" bağlantısı. | harden | ⏳ atlama bağlantısı ve theme-color var; sayfa başına meta açıklaması yok |

## P3: cila

| ID | Bulgu | Düzeltme | Durum |
|---|---|---|---|
| C-01 | Chart.js (210 KB) grafik olmayan sayfalarda da engelleyici yükleniyor. | `defer`. | ✅ |
| C-02 | Bricolage ve latin-ext yazı tipleri önden yüklenmiyor (ş, ğ, İ her sayfada). | `preload`. | ✅ |
| C-03 | Tarayıcı yüzeyleri (seçim, imleç, `accent-color`) temasız. | `::selection`, `caret-color`, `accent-color`. | ✅ |
| C-04 | Sağ alt köşedeki bildirim mobilde kahraman düğmeleri kapatıyor; yönetici görünümünde şeritle aynı mesajı yineliyor. | Mobilde üste alınsın; yinelenen mesaj kaldırılsın. | ⏳ mobilde üstte; yönetici görünümündeki yinelenen mesaj duruyor |
| C-05 | Sohbet bağlamında "compset", "LLM", "MAPE", "Backtest" gibi terimler. | Sade Türkçe; teknik terim ikinci planda. | ⏳ 'compset' → 'rakip seti', gerekçede jargon kalktı; MAPE/Backtest adları duruyor |
| C-06 | Docker: web sağlık denetimi tohumlama bitmeden "unhealthy" oluyor; worker HTTP sunmadığı hâlde aynı denetimi devralıyor. | `start_period` uzatılsın, worker'da sağlık denetimi kapatılsın. | ✅ |
| C-07 | Tablolarda `<caption>`/`scope` yok; pazar ızgarasında satır başlıkları `td`. | `th scope="row"`. | ➖ tablo başlık/scope ertelendi |

## Sonuç (iyileştirme sonrası)

| Ölçüt | Önce | Sonra |
|---|---|---|
| Konsol hatası veya yatay taşma olan görünüm (180) | 18 (7 sayfada 111 px taşma) | **0** |
| Kontrast ihlali olan görünüm (180, saklı tema) | 170 | **0** |
| Kontrast ihlali, sistem koyu teması (90, saklı tercih yok) | ölçülmemişti | **0** |
| Etiketsiz form alanı | 56 | **0** |
| Demo uyarısı olmayan ekran | 11 | **0** |
| Testler (birim + entegrasyon / E2E) | 178 / 7 | **287 / 9** |

Ham ölçümler: `docs/screenshots/before/report.json`, `docs/screenshots/after/report.json`. Görüntüler aynı adla iki
klasörde (`<grup>-<ekran>-<1440|390>-<light|dark>.jpg`).

## Bilinçli olarak korunanlar

- Instrument Sans + Bricolage Grotesque (dedektör "overused-font" uyarısı yanlış pozitif; marka kararı).
- Pazar ızgarasında ıraksak mavi/kırmızı ölçek: lejantı "sizden ucuz / pahalı" olarak etiketli, geleneksel ve renk körlüğüne
  dayanıklı bir çift; alarm anlamı taşımıyor.
- Öneri motorunun gerekçe metni (`pricing.py`) değişmedi; birim testleri bu metne bağlı. Sadeleştirme sunum katmanında yapıldı.

## Gözden geçirme ve onay

İş tanımı, bu belgenin brainstorming ile gözden geçirilmesini ve planın onaydan sonra yazılmasını istiyor. Kullanıcı aynı
mesajda "Bütün bölümleri yap … tüm izinleri veriyorum" diyerek ara onay kapılarını önceden verdi. Bu nedenle plan
(`docs/superpowers/plans/2026-11-02-impeccable-ui.md`) beklemeden yazıldı ve uygulandı. Kapsam: P1'in tamamı, P2 ve P3'ün
mümkün olan en büyük kısmı. Kalanlar `docs/ACIK_KONULAR.md` içinde.
