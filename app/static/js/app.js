/* Genel arayüz davranışları: tema, mobil menü, onay pencereleri, otomatik gönderim */
(function () {
  "use strict";
  var root = document.documentElement;

  function storedTheme() {
    try { return localStorage.getItem("or-theme"); } catch (e) { return null; }
  }
  function applyTheme(t) {
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t);
    else root.removeAttribute("data-theme");
  }
  applyTheme(storedTheme());

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dark = root.getAttribute("data-theme") === "dark" ||
          (!root.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
        var next = dark ? "light" : "dark";
        applyTheme(next);
        try { localStorage.setItem("or-theme", next); } catch (e) { /* depolama kapalı */ }
        document.dispatchEvent(new CustomEvent("themechange"));
      });
    });

    // Mobil menü: aria-expanded, dışarı tıklama ve Esc ile kapanma, kapanınca odak düğmeye döner
    var menu = document.querySelector("[data-menu]");
    if (menu) {
      var setOpen = function (open, returnFocus) {
        document.body.classList.toggle("nav-open", open);
        menu.setAttribute("aria-expanded", open ? "true" : "false");
        if (open) {
          var first = document.querySelector(".sidebar a, .sidebar button");
          if (first) setTimeout(function () { first.focus(); }, 50);
        } else if (returnFocus) {
          menu.focus();
        }
      };
      menu.addEventListener("click", function () { setOpen(!document.body.classList.contains("nav-open"), false); });
      document.addEventListener("click", function (e) {
        if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar") && !e.target.closest("[data-menu]")) {
          setOpen(false, false);
        }
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && document.body.classList.contains("nav-open")) setOpen(false, true);
      });
    }

    document.querySelectorAll("form[data-confirm]").forEach(function (f) {
      f.addEventListener("submit", function (e) {
        if (!window.confirm(f.getAttribute("data-confirm"))) e.preventDefault();
      });
    });

    document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
      el.addEventListener("change", function () { el.form && el.form.submit(); });
    });

    document.querySelectorAll("[data-check-all]").forEach(function (box) {
      box.addEventListener("change", function () {
        document.querySelectorAll(box.getAttribute("data-check-all")).forEach(function (c) { c.checked = box.checked; });
      });
    });

    // İl seçimine göre ilçe listesi (kayıt formu)
    var prov = document.querySelector("[data-province]");
    var dist = document.querySelector("[data-district]");
    if (prov && dist) {
      var map = JSON.parse(document.getElementById("district-map").textContent);
      var current = dist.getAttribute("data-current") || "";
      function fill() {
        var list = map[prov.value] || [];
        dist.innerHTML = '<option value="">İlçe seçin</option>' + list.map(function (d) {
          return '<option' + (d === current ? " selected" : "") + ">" + d + "</option>";
        }).join("");
      }
      prov.addEventListener("change", function () { current = ""; fill(); });
      fill();
    }

    // Bildirim kutuları: kapatma düğmesi; yalnızca başarı/bilgi mesajları 7 sn sonra kendiliğinden kapanır.
    // Hata ve uyarılar kullanıcı kapatana kadar kalır (WCAG 2.2.1).
    document.querySelectorAll("[data-toast]").forEach(function (t) {
      function hide() { t.classList.add("hide"); setTimeout(function () { t.remove(); }, 260); }
      var btn = t.querySelector("[data-toast-close]");
      if (btn) btn.addEventListener("click", hide);
      var calm = t.matches(".alert.success, .alert.info");
      if (calm && t.closest(".main")) setTimeout(hide, 7000);
    });

    // Paneldeki öneri fiyatı için tek seferlik sayaç animasyonu
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.querySelectorAll("[data-count]").forEach(function (el) {
      var target = parseFloat(el.getAttribute("data-count"));
      if (isNaN(target) || reduce) return;
      var start = performance.now(), dur = 700, from = target * 0.82;
      var fmt = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });
      function step(now) {
        var k = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - k, 3);
        el.textContent = "€" + fmt.format(from + (target - from) * e);
        if (k < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });

    // Çalışan iş varsa veri hattı sayfasını kısa aralıklarla yenile
    if (document.querySelector("[data-refresh-while-running]")) {
      setTimeout(function () { window.location.reload(); }, 4000);
    }
  });
})();
