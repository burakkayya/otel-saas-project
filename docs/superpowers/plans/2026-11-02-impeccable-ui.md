# Impeccable arayüz iyileştirme turu: uygulama planı

> **Ajanlar için:** GEREKLİ ALT SKILL: superpowers:executing-plans (bu oturumda satır içi; kullanıcı yöntemi iş tanımında verdi).
> Adımlar `- [ ]` ile izlenir.

**Hedef:** `docs/UI_AUDIT.md` bulgularını (P1 tamamı, P2/P3'ün çoğu) mevcut kimliği koruyarak kapatmak.

**Mimari:** Değişikliklerin çoğu tasarım belirteçleri (`app/static/css/app.css` `:root` blokları) ve ortak makrolar
(`app/templates/partials/ui.html`) üzerinden yapılır. Böylece tek düzeltme tüm ekranlara yayılır. Ekran özel
düzeltmeler şablonlarda yapılır. Arka uca dokunulan yerler yalnızca şablona veri geçirme ve hata sayfalarıdır.

**Teknoloji:** FastAPI + Jinja2, kendi CSS'i, Chart.js 4 (yerel), pytest, Playwright.

**Spec:** `docs/UI_AUDIT.md`, `DESIGN.md`, `PRODUCT.md`

## Global kısıtlar

- Kimlik korunur: kireç beyazı zemin, liman laciverti menü, Ege mavisi aksiyon, begonvil yalnızca fırsat, Bricolage
  Grotesque + Instrument Sans, rakip radarı.
- Harici CDN yok.
- Türkçe metin ve biçim (€1.234, %12, 1 Kas Paz); negatif sayılarda U+2212 "−".
- Dürüstlük:
  - "ek kâr" ve "kurtarılan gelir" yok;
  - etki rakamları "tahmini" ve güven düzeyiyle verilir;
  - kalan oda düşüşü satış değildir;
  - demo uyarısı her ekranda bulunur.
- Grafikler:
  - tek y ekseni;
  - sabit seri sırası;
  - 2+ seride lejant;
  - kritik grafikte tablo görünümü;
  - durum rengi ikon ve etiketle birlikte.
- Erişilebilirlik:
  - WCAG AA kontrast;
  - görünür odak;
  - `prefers-reduced-motion` uyumu;
  - Türkçe ve açık form hataları.
- Testler:
  - mevcut 178 birim/entegrasyon + 7 E2E testi her zaman yeşil kalır;
  - yeni davranış için önce test yazılır.

## İnceleme odağı

1. Sistem koyu teması **ve** saklı tema tercihi olmayan ziyaretçi: hiçbir metin zeminde kaybolmamalı. Tarama betiği
   şimdiye kadar hep `or-theme` yazıyordu; Task 9'da tercih olmadan da ölçülecek.
2. 390 px'te yatay taşma sıfır olmalı. Bu, uzun otel adları ve 60 günlük tablolar için de geçerli.
3. Yönetici görünümü (impersonation): demo şeridi + yönetici şeridi + bildirim kutusu üst üste binmemeli.
4. Klavye ile mobil menü: kapalıyken sekme sırasında olmamalı, Esc ile kapanmalı.
5. Hata durumunda form gönderimi: kullanıcının girdisi kaybolmamalı, hata alanın yanında okunmalı.

---

### Task 1: Belirteçler ve temel erişilebilirlik (A-01, A-06, A-07, A-08, A-20, B-10, C-03)

**Files:** Modify `app/static/css/app.css`, `app/templates/partials/app_layout.html`

- [ ] Açık tema belirteçleri:
  - `--bg #f4f3ee`, `--surface-2 #faf9f5`, `--surface-3 #eeece5`;
  - `--line #dfdcd2`, `--line-2 #ebe8e0`;
  - `--muted #586878`;
  - `--good #17732f`, `--warn #8a5800`, `--bougain #a8285a`;
  - yeni: `--brand-fill`, `--brand-fill-hover`, `--focus`, `--on-bougain`.
- [ ] Koyu tema belirteçleri:
  - `--muted #9aabb9`, `--brand-fill #2f6fbd`, `--focus #6aa4e6`;
  - `--harbour #10283a`, `--harbour-2 #173550`;
  - `--bougain #e98bab`, `--on-bougain #0b1622`, `--info #7fb0ec`;
  - `--grid #2b3f51`.
  - Hem `@media` hem `[data-theme=dark]` bloğuna yazılır.
- [ ] Odak:
  - genel `:focus-visible` → `var(--focus)`;
  - koyu yüzeylerde (`.sidebar`, `.hero-rec`, `.auth-side`, `.rec-card`) `#8fd0ff`;
  - inputlarda 2 px halka;
  - `.choice:focus-within`.
- [ ] `table.data th.num` sağa hizalanır.
- [ ] `::selection`, `caret-color`, `accent-color` eklenir.
- [ ] Kenar menüdeki "Çıkış yap" düğmesi satır içi stil yerine `.sidebar-logout` sınıfını alır; hover zemini `rgba(255,255,255,.08)`.
- [ ] Doğrulama: `scripts/ui_snapshots.py` kontrast sayısı yalnızca bilinçli istisnalara düşmeli.

### Task 2: Demo uyarısı ve hata sayfaları (A-03, B-05, B-08)

**Files:** `ui.html` (`demo_banner(for_admin=False)` makrosu), `app_layout.html`, `public_layout.html`, `auth_layout.html`,
`errors/error.html`, `app/main.py` (`_viewer`, `_error`), `public/landing.html`
**Test:** `tests/integration/test_ui_quality.py`:
- `test_demo_banner_on_public_pages`
- `test_demo_banner_on_admin_pages`
- `test_demo_banner_on_error_pages`
- `test_forbidden_page_offers_way_back_for_signed_in_user`
- `test_not_found_page_for_visitor_links_home`

- [ ] Testler kırmızı çalıştırılır (20 hata görüldü).
- [ ] Makro uygulanır. Otel kullanıcısı kısa metni görür; `.env` notu yalnızca yönetimde. Hata sayfası `user` alır:
  - "Panele dön" / "Ana sayfaya dön";
  - `javascript:` yok.
- [ ] Tanıtım sayfasında demo modda "72 örnek tesis (demo)" yazılır.
- [ ] Testler yeşil; commit.

### Task 3: Formlar (A-04, A-05, A-14, A-18, B-18, B-19)

**Files:** `app.css`, yönetim şablonları (plans, users, costs, model, demand, compliance, system, hotel_detail),
`public/register.html`, `public/register_match.html`, `hotel/account.html`, `hotel/subscription.html`, `hotel/suggestions.html`,
`app/static/js/app.js`
**Test:**
- `test_*_form_fields_are_labelled`: herkese açık, otel, yönetim ve otel ayrıntısı sayfaları;
- `test_register_match_does_not_preselect_weak_candidate`: farklı ilçedeki %67'lik aday `checked` olmamalı.

- [ ] Etiketler `for`/`id` ile bağlanır; arama ve kanıt notuna `aria-label` verilir.
- [ ] `input:not([type])` stil alır; para ve ağırlık alanlarına `inputmode="decimal"`.
- [ ] `errors_box` alan bazlı hatalarla `aria-invalid` + `.error-text` destekler; hata/uyarı bildirimleri kendiliğinden kapanmaz.
- [ ] Eşleştirme ekranı yalnızca skor ≥ 0,85 **ve** ilçe eşitse ön seçim yapar; seçim yoksa radyo grubu `required` olur.
- [ ] KVKK metni: "okudum, bilgilendirildim". `.seg` gruplarında `role="group"`, etkin bağlantıda `aria-current`.

### Task 4: Renk anlamları ve hareket (A-09, B-01, B-02, B-03, B-11, B-12)

**Files:** `ui.html` (`change_badge`), `hotel/dashboard.html`, `hotel/suggestions.html`, `hotel/demand.html`, `app.css`, `charts.js`, `app.js`

- [ ] `change_badge`:
  - ≥+eşik → `badge hot` + yukarı ok ("Fiyat artırma fırsatı");
  - ≤−eşik → `badge down` (nötr) + aşağı ok;
  - küçük değişim → `.delta` + ok.
- [ ] Takvim:
  - `--cal-up: var(--bougain)`, `--cal-down: #4f6b85` (koyu temada #7d97ad);
  - renk gücü en fazla %45;
  - metin her zaman `--ink`.
- [ ] Yönetici görünümü şeridi bilgi mavisi; begonvil yalnızca fırsat, "çok yüksek talep" ve "bugün" için kalır.
- [ ] Hareket:
  - Chart.js animasyonu `reduce` iken `false`, değilse 250 ms;
  - sayfa giriş animasyonu ve kahraman şeridi kaldırılır;
  - radar taraması tek tur;
  - fiyat sayacı kaldırılır.
- [ ] Talep ısı takvimi: gün etiketleri .74rem; geçmiş günler opaklık yerine çizgili/soluk renkle gösterilir.

### Task 5: Duyarlı düzen (A-02, A-12, A-13, A-19, B-09, C-04)

**Files:** `public_layout.html`, `auth_layout.html`, `app.css`, `app.js`, `hotel/suggestions.html`, `hotel/dashboard.html`,
`hotel/competitors.html`, `hotel/room_types.html`

- [ ] Üst menü 560 px'te kısa CTA kullanır ve sarar.
- [ ] Giriş ekranında mobil üst bilgi (marka + tema düğmesi) gösterilir.
- [ ] `table.data.stack-sm`: ≤560 px'te her satır bir kart olur; hücreler `data-label` ile etiketlenir. Öneri listesi,
  "Bu hafta" ve oda tiplerinde uygulanır. Diğer tablolarda `.table-wrap` kenar solması kullanılır.
- [ ] Rakip tablosu: benzerlik dökümü ikinci satıra iner; aksiyon sütunu kesilmez.
- [ ] Mobil menü:
  - kapalıyken `visibility:hidden`;
  - düğmede `aria-expanded`/`aria-controls`;
  - Esc ile kapanır, odak düğmeye döner.
- [ ] Bildirimler ≤560 px'te üstte gösterilir.
- [ ] E2E testi `test_mobile_menu` yeşil kalır.

### Task 6: Dürüstlük ve metin (A-10, A-11, A-15, A-17, B-06, B-07, B-13, B-17, C-05)

**Files:** `hotel/dashboard.html`, `hotel/suggestion_detail.html`, `hotel/backtest.html`, `hotel/settings.html`,
`public/landing.html`, `public/pricing.html`, `admin/impact.html`, `admin/hotel_detail.html`, `admin/audit.html`, `admin/demand.html`,
`app/web.py` (yalnızca yeni süzgeçler: `signed`, `drivers`), `app/seed.py` (paket özellik metinleri)
**Test:**
- `test_backtest_does_not_call_inventory_drop_sales`: "Satış ilerlemesi" ve "Talep–satış" geçmez;
- `test_plan_features_match_limits`: "Sınırsız" yalnızca sınır yoksa geçer, e-posta maddesi "yakında" içerir;
- `test_signed_number_filter`.

- [ ] Kahraman alanda gerekçe sunumu:
  - tek cümle başlık + en fazla 3 etken çipi (`rationale` girdilerinden: medyan değişimi, talep, kalan oda, sezon, fiyat konumu);
  - güven rozeti fiyatın yanında.
- [ ] Backtest sütun adları değişir.
- [ ] Etki kartı "Anlamlı fark yok / Anlamlı fark" ile başlar; değer `tahmini … / oda-gece` biçiminde.
- [ ] Yönetim etkisi:
  - dönem ve ±2 SH aralığı;
  - nötr tonlu anlamlılık;
  - otel ayrıntısında da anlamlılık.
- [ ] Paket özellikleri sınırlarla tutarlı olur; e-posta seçenekleri "yakında" olarak işaretlenir.
- [ ] Ham kodlar Türkçe etiket haritalarıyla gösterilir.
- [ ] Radar lejantı eklenir.

### Task 7: Yönetim sağlamlaştırma (A-16, B-04, B-14, B-15, B-20)

**Files:** `admin/subscriptions.html`, `admin/invoices.html`, `admin/users.html`, `admin/mappings.html`, `admin/pipeline.html`,
`admin/dashboard.html`, `admin/audit.html`, `hotel/demand.html`, `hotel/performance.html`, `admin/hotel_detail.html`
**Test:** `test_admin_destructive_forms_confirm`: abonelik, fatura ve kullanıcı durum formlarında `data-confirm` bulunur;
kendi satırında devre dışı bırakma düğmesi yoktur.

- [ ] `data-confirm` sonuç metinleriyle eklenir; kendi hesabını devre dışı bırakma düğmesi gizlenir.
- [ ] Veri hattında yalnızca `daily_pipeline` birincil düğme olur.
- [ ] Boş durumlar `ui.empty` makrosuyla verilir.
- [ ] Talep, uyum, MRR ve fiyat geçmişi grafiklerine tablo görünümü eklenir.
- [ ] Otel ayrıntısında kategori renkleri sabit eşlenir: standard→1, deluxe→2, suite→3, family→4.

### Task 8: Performans ve altyapı (C-01, C-02, C-06, B-21)

**Files:** `base.html`, `app_layout.html`, `docker-compose.yml`, `Dockerfile`

- [ ] Chart.js ve `charts.js` `defer` ile yüklenir.
- [ ] Bricolage latin ve latin-ext yazı tipleri `preload` edilir.
- [ ] "İçeriğe geç" bağlantısı eklenir.
- [ ] CSS/JS sürüm parametresi artırılır.
- [ ] Docker:
  - web sağlık denetiminde `start_period: 240s`;
  - worker'da `healthcheck: disable: true`.

### Task 9: Doğrulama, belgeler, teslim

- [ ] `pytest tests/unit tests/integration -q` ve `pytest -m e2e tests/e2e -q` yeşil; `ruff check app tests scripts` temiz.
- [ ] `scripts/ui_snapshots.py --out docs/screenshots/after` çalıştırılır. Beklenen:
  - 0 konsol hatası (beklenen 403/404 hariç);
  - 0 taşma;
  - kontrast ihlali yalnızca belgelenmiş istisnalar.

  Ek olarak tema tercihi saklanmadan sistem koyu temasıyla bir tur daha çalıştırılır (`--no-stored-theme`).
- [ ] Her ekran için `/impeccable polish` geçişi: önce/sonra görüntüleri karşılaştırılır.
- [ ] `docs/UI_AUDIT.md` durum sütunu, `docs/YAPILANLAR.md` "Impeccable iyileştirme turu" bölümü ve `docs/ACIK_KONULAR.md` güncellenir.
- [ ] Kod incelemesi (`requesting-code-review`), dalın pushlanması, PR (`finishing-a-development-branch`). Merge için kullanıcıya sorulur.
