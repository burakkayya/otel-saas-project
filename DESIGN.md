---
name: OtelRadar
description: Halka açık veriyle her sabah gerekçeli oda fiyatı önerisi; sakin, Ege kıyısı bir panel.
colors:
  limewash: "#f4f3ee"
  surface: "#ffffff"
  surface-2: "#faf9f5"
  surface-3: "#eeece5"
  ink: "#0f2233"
  ink-2: "#44566a"
  muted: "#586878"
  line: "#dfdcd2"
  line-2: "#ebe8e0"
  aegean: "#1f5fa8"
  aegean-hover: "#174d8a"
  aegean-soft: "#e6eef8"
  harbour: "#0f2b3d"
  harbour-2: "#163a51"
  harbour-ink: "#cfdde8"
  bougainvillea: "#a8285a"
  bougainvillea-soft: "#fbe9f0"
  good: "#17732f"
  warn: "#8a5800"
  bad: "#c53030"
  series-1: "#2a78d6"
  series-2: "#eb6834"
  series-3: "#1baf7a"
  series-4: "#eda100"
typography:
  display:
    fontFamily: "Bricolage Grotesque, Instrument Sans, system-ui, sans-serif"
    fontSize: "3.2rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Bricolage Grotesque, Instrument Sans, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Bricolage Grotesque, Instrument Sans, system-ui, sans-serif"
    fontSize: "1.02rem"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "Instrument Sans, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Instrument Sans, system-ui, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.3
  figure:
    fontFamily: "Bricolage Grotesque, Instrument Sans, system-ui, sans-serif"
    fontSize: "1.9rem"
    fontWeight: 700
    lineHeight: 1.1
    fontFeature: "tnum"
rounded:
  s: "6px"
  control: "8px"
  m: "10px"
  l: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  s: "8px"
  m: "12px"
  l: "18px"
  xl: "24px"
  xxl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.aegean}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-primary-hover:
    backgroundColor: "{colors.aegean-hover}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 11px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.l}"
    padding: "16px 20px 20px"
  sidebar:
    backgroundColor: "{colors.harbour}"
    textColor: "{colors.harbour-ink}"
    width: "248px"
  nav-item-active:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.harbour}"
    rounded: "{rounded.control}"
  badge-opportunity:
    backgroundColor: "{colors.bougainvillea-soft}"
    textColor: "{colors.bougainvillea}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  hero-recommendation:
    backgroundColor: "{colors.harbour}"
    textColor: "{colors.harbour-ink}"
    rounded: "{rounded.l}"
    padding: "24px 28px"
---

# Design System: OtelRadar

> Bu belge `/impeccable document` (tarama modu) ile `app/static/css/app.css`, `app/templates/partials/ui.html` ve
> `app/static/js/charts.js` dosyalarından çıkarıldı (2 Kasım 2026). Ön madde (frontmatter) normatiftir; düzyazı nasıl
> uygulanacağını anlatır. Koyu tema karşılıkları `app.css` içindeki `[data-theme="dark"]` bloğundadır.
> **Güncelleme (Impeccable turu, 2 Kasım 2026):** zemin sıcak kireç badanasına çekildi, `--muted` AA'ya getirildi,
> `--brand-fill`, `--focus`, `--on-bougain`, `--cal-up/--cal-down` belirteçleri eklendi; ayrıntı `docs/UI_AUDIT.md`.

## Overview

**Creative North Star: "Sabah İskelesi"**

Bodrum'da sabah yedide iskeleye inen bir otel sahibi düşünün: kireç badanalı duvarlar, laciverde dönük liman, berrak Ege
mavisi su ve bir köşede begonvil. OtelRadar'ın paneli bu sahnenin sakinliğini taşır. Zemin kireç beyazı ve sessizdir;
kenar menü ve "bu gecenin önerisi" kartı liman lacivertindedir, ekranda ağırlığı olan tek koyu kütle onlardır. Aksiyon
rengi Ege mavisidir; begonvil yalnızca fırsat (önerinin yukarı yönlü sapması, talepte sıçrama, bugünün işareti) için
açar ve nadir olduğu için dikkat çeker.

Yoğunluk "sakin yoğunluk"tur: gelir yöneticisinin istediği tablolar, ızgaralar ve grafikler oradadır ama her ekran önce
tek bir cevapla (önerilen fiyat, bant, gerekçe) açılır. Rakamlar Bricolage Grotesque ile iri ve tablo rakamlı
(tabular-nums), metin Instrument Sans ile sade ve okunurdur. Hareket tek seferlik ve kısadır; `prefers-reduced-motion`
tercihinde tamamen durur.

**Key Characteristics:**
- Kireç beyazı zemin, beyaz paneller, ince çizgiler; gölge neredeyse yok.
- Liman laciverti kenar menü ve kahraman öneri kartı; ekrandaki tek koyu kütleler.
- Ege mavisi tek aksiyon rengi; begonvil yalnızca fırsat vurgusu.
- İri, tablo rakamlı fiyatlar; Türkçe para/yüzde/tarih biçimi (€1.234, %12, 1 Kas Paz).
- İmza öğe: rakip radarı (oteliniz merkezde, rakipler gerçek kerteriz ve mesafeyle).

## Colors

Sakin ve tuzlu bir palet: nötrler hafif soğuk-gri, tek doygun aksiyon rengi, fırsat için tek sıcak vurgu.

### Primary
- **Ege Mavisi** (aegean): birincil düğmeler, bağlantılar, odak halkası, etkin sekme, seçili onay kutuları. Hover'da
  bir ton koyulaşır (aegean-hover). Açık tonu (aegean-soft) seçili satır ve odak gölgesi zeminidir.

### Secondary
- **Liman Laciverti** (harbour, harbour-2): kenar menü, kahraman öneri kartı, giriş sayfası yan paneli. Üzerindeki metin
  harbour-ink ve beyazdır. harbour-2 menü üzeri ve kart içi bölmelerdir.

### Tertiary
- **Begonvil** (bougainvillea, bougainvillea-soft): yalnızca fırsat vurgusu: önerinin %8+ yukarı sapması, "çok yüksek"
  talep, takvimde bugün ve etkinlik noktası, okunmamış sayacı, yönetici görünümü şeridi.

### Neutral
- **Kireç Beyazı** (limewash): sayfa zemini; hafif sıcak, badanalı duvar tonu. Lacivert menü ve Ege mavisiyle Ege kıyısı karşıtlığını kurar.
- **Beyaz Yüzey** (surface) ve **Kabuk** tonları (surface-2, surface-3): panel, tablo başlığı, iz (track) zeminleri.
- **Mürekkep** (ink, ink-2, muted): başlık/gövde, ikincil metin, yardımcı metin. Üçü de beyaz ve kireç zeminde AA
  (muted ≥4,6:1); koyu temada muted #9aabb9.
- **Çizgi** (line, line-2): panel kenarı ve tablo satır ayırıcıları.

### Data
- **Seriler** (series-1…4): grafiklerde sabit sırayla: 1 öneri (mavi), 2 mevcut fiyatınız (turuncu), 3 rakip medyanı
  (yeşil), 4 elle eklenen rakip / uyarı (amber). Sıralı ısı (seq-1…6) talep takvimi, ıraksak (div-pos/div-neg)
  pazar ızgarasında rakip fiyat farkı içindir.
- **Durum** (good, warn, bad, info + -soft zeminleri): rozet ve uyarılarda her zaman ikon ve metinle birlikte.

### Odak ve dolgu
- **Odak** (`--focus`): açık temada Ege mavisi, koyu temada #6aa4e6; lacivert yüzeylerde (#8fd0ff) açık halka.
- **Birincil dolgu** (`--brand-fill`): düğme zemini; koyu temada bağlantı renginden koyu (#2f6fbd) ki beyaz metin AA kalsın.

### Named Rules
**The Begonvil Rule.** Begonvil yalnızca fırsatı işaret eder (fiyat artırma fırsatı, çok yüksek talep, bugün); hata,
uyarı, düşüş, yönetici şeridi veya süsleme için kullanılmaz. Önerilen fiyat düşüşü nötr rozet + aşağı okla gösterilir. Bir ekranda
birkaç noktadan fazla begonvil varsa anlamını yitirmiştir.

**The Color-Never-Alone Rule.** Durum rengi tek başına anlam taşımaz; her rozet ve hücre ikon veya metinle birlikte gelir.

**The Fixed Series Rule.** Öneri her grafikte series-1, mevcut fiyat series-2, rakip medyanı series-3'tür. Sıra hiçbir
ekranda değişmez.

## Typography

**Display Font:** Bricolage Grotesque (yedek: Instrument Sans, system-ui)
**Body Font:** Instrument Sans (yedek: system-ui, Segoe UI, Roboto)

**Character:** Bricolage'ın hafif tuhaf, sıcak grotesk biçimleri fiyatlara ve başlıklara kişilik verir; Instrument Sans
yoğun tablo ve form metninde sakin ve nötr kalır. İkisi de yerel sunulur (SIL OFL), CDN yok.

### Hierarchy
- **Display** (700, 3.2rem / mobilde 2.5rem, 1.0): kahraman karttaki "bu gecenin önerisi" fiyatı; tanıtımda 3.8rem'e çıkar.
- **Headline** (650, 1.75rem, 1.2): sayfa başlıkları (uygulama üst çubuğunda 1.3rem).
- **Title** (650, ~1.02rem, 1.35): panel başlıkları.
- **Figure** (700, 1.9rem, tabular-nums): KPI değerleri, plan fiyatları, takvim fiyatları.
- **Body** (400, 15px, 1.55): gövde; tablolar .88rem; gerekçe metni en fazla 62ch.
- **Label** (600, .85rem): form etiketleri, tablo başlıkları (.8rem, ink-2).

### Named Rules
**The Tabular Price Rule.** Fiyat, yüzde ve sayı gösteren her hücre `tabular-nums` kullanır ve sağa hizalanır.

## Layout

Uygulama iki sütunludur: 248 px liman laciverti kenar menü ve en fazla 1440 px içerik. İçerik 28 px yan boşlukla, 18 px
ızgara aralığıyla akar (g-2, g-3, g-4, g-main-side = 2fr / 1fr). Her ekran üstte sabit (sticky) başlık çubuğu, altında
demo uyarı şeridi taşır. 1180 px altında 4'lü ızgara 2'ye, ana/yan düzen tek sütuna iner; 900 px altında kenar menü
çekmeceye dönüşür ve 16 px yan boşluk kullanılır; 560 px altında KPI'lar 2'li kalır, takvim hücreleri küçülür. Geniş
tablolar `.table-wrap` içinde yatay kayar; sayfa kendisi asla yatay kaymaz.

Herkese açık sayfalar 1280 px ortalanmış sütunda, `clamp(16px, 5vw, 64px)` yan boşlukla akar; bölümler 64 px dikey
aralıkla ve ince üst çizgiyle ayrılır.

## Elevation & Depth

Düz bir sistem: derinlik ton katmanlarıyla (zemin → beyaz panel → kabuk tonları) ve 1 px çizgilerle verilir. Gölge
yalnızca yüzen öğelerde vardır.

### Shadow Vocabulary
- **Fısıltı** (`box-shadow: 0 1px 2px rgba(15,34,51,.05), 0 4px 16px rgba(15,34,51,.04)`): seçili segment sekmesi ve
  tanıtım önizleme panelleri.
- **Yüzen** (`box-shadow: 0 12px 32px rgba(15,34,51,.18)`): bildirim kutuları (toast).
- **Kahraman** (`box-shadow: 0 24px 60px rgba(15,43,61,.25)`): yalnızca tanıtım sayfasındaki öneri kartı.

### Named Rules
**The Flat-By-Default Rule.** Paneller gölgesizdir; yükseklik yalnızca ekranın üstünde yüzen öğeler içindir.

## Shapes

Yumuşak ama gevşek olmayan köşeler: kontroller 8 px, kutular 10 px, paneller ve kahraman kart 16 px, rozetler tam yuvarlak.
Fiyat bandı göstergesinde öneri daire, mevcut fiyat 45° döndürülmüş kare (elmas), rakip medyanı ince dikey çizgidir; bu üç
biçim lejantlarda ve radarda (oteliniz = elmas) tutarlı kullanılır.

## Components

### Buttons
- **Shape:** 8 px köşe; küçük (sm) 7 px, büyük (lg) 10 px.
- **Primary:** Ege mavisi zemin, beyaz metin, 600 ağırlık, 8×14 px.
- **Hover / Focus:** bir ton koyu mavi; odakta 2 px Ege mavisi dış çizgi (outline) 2 px boşlukla.
- **Secondary / Ghost / Danger:** beyaz zemin + çizgi; şeffaf (ghost); kırmızı metinli tehlike düğmesi.

### Chips
- **Rozet:** tam yuvarlak, .76rem, 600; durum rozetleri -soft zemin + koyu ton metin + nokta veya ikon.
- **Segment sekmeleri (.seg):** kabuk zeminli kapsül içinde, seçili sekme beyaz ve fısıltı gölgeli.

### Cards / Containers
- **Corner Style:** 16 px (panel), 10 px (stat).
- **Background:** beyaz yüzey; yumuşak panel (soft) kabuk tonu.
- **Shadow Strategy:** yok (bkz. Flat-By-Default).
- **Border:** 1 px line.
- **Internal Padding:** başlık 16×20, gövde 16×20×20.

### Inputs / Fields
- **Style:** 1 px line, 8 px köşe, beyaz zemin, 9×11 px.
- **Focus:** kenar Ege mavisi + 3 px aegean-soft halka.
- **Error:** form üstünde kırmızı uyarı kutusu, maddeler halinde Türkçe hata listesi.

### Navigation
- **Kenar menü:** liman laciverti; grup başlıkları küçük ve soluk; öğeler 18 px çizgi ikon + metin; hover harbour-2;
  etkin öğe beyaz zemin, lacivert metin ve solda gök mavisi 4 px işaret. Mobilde soldan açılan çekmece.

### Kahraman öneri kartı (Signature)
Liman laciverti kart: solda "Bu gece, <oda>" etiketi ve iri öneri fiyatı + sapma çipi; ortada gerekçe cümlesi ve mevcut
fiyat / rakip medyanı / kalan oda; sağda fiyat bandı göstergesi ve "Gerekçeyi incele" / "Takvim" düğmeleri.

### Fiyat bandı göstergesi
Taban–tavan bandı (series-1 %22 dolgu), rakip medyanı (series-3 çizgi), mevcut fiyat (series-2 elmas) ve öneri
(series-1 daire) tek iz üzerinde. Her kullanımda yanında lejant bulunur.

### Rakip radarı (Signature)
Kare SVG: merkezde oteliniz (turuncu elmas), rakipler gerçek kerteriz ve karekök ölçekli mesafeyle numaralı dairelerde;
daire boyu benzerlik puanı, amber daire elle eklenen rakip. Kesikli mesafe halkaları ve kuzey işareti; isteğe bağlı yavaş
tarama (sweep) animasyonu hareket azaltma tercihinde durur. Yanında aynı numaralarla rakip listesi bulunur.

### Logo
Radar halkası (Otel'in O'su), 60° tarama dilimi (Ege mavisi; lacivert zeminde açık mavi) ve dilimin içinde bulunan otel
noktası (güneş sarısı `--sun` #f2b84b). Halka `currentColor` ile çizilir; her zeminde çalışır. Yazı: Bricolage 700.

### Deniz haritası zemini
Lacivert yüzeylerde (açılış, kapanış bandı, kahraman kart, giriş yan paneli) eş derinlik çizgileri deseni
(`app/static/img/chart-contours.svg`). Yalnızca lacivert üzerinde, düşük karşıtlıkla kullanılır.

### Hareket
- Tanıtımın tek odak anı açılıştaki radar taramasıdır; diğer bölümlerde yalnızca ürün görüntüleri açılır.
- Panelde hareket durum anlatır: grafik açılışı, bant işaretleri, sayfa geçişi (200 ms), etkin menü öğesinin kayması.
- Hepsi `prefers-reduced-motion` tercihinde kapalıdır; varsayılan durum her şeyin görünür olduğu durumdur.

### Güneş sarısı
`--sun` yalnızca lacivert zemin üzerindeki birincil çağrıda (açılış düğmesi, "Uyguladım", önerilen paket etiketi) ve
logodaki otel noktasında kullanılır. Açık zeminde birincil renk Ege mavisidir.

## Do's and Don'ts

### Do:
- **Do** her ekranı önce cevapla (öneri, bant, gerekçe), sonra ayrıntıyla aç.
- **Do** fiyat ve yüzdeleri Türkçe biçimle ve tabular-nums ile yaz (€1.234, %12, 1 Kas Paz); eksi için "−" kullan.
- **Do** her etki rakamını "tahmini" etiketi ve güven rozetiyle göster.
- **Do** grafiklerde tek y ekseni, sabit seri sırası, 2+ seride lejant ve kritik grafikte "Tablo olarak göster" kullan.
- **Do** demo veri şeridini her ekranda tut.

### Don't:
- **Don't** begonvili hata, uyarı veya süsleme için kullanma (bkz. The Begonvil Rule).
- **Don't** kalan oda düşüşünü satış olarak göster; "ek kâr", "kurtarılan gelir" gibi kesin gelir ifadeleri kullanma.
- **Don't** harici CDN'den yazı tipi, ikon veya betik yükleme.
- **Don't** çift y eksenli grafik çizme.
- **Don't** durum rengini ikon veya metin olmadan kullanma.
