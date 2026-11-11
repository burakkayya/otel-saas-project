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
      var dur = 900, from = target * 0.82, delay = parseInt(el.getAttribute("data-count-delay") || "0", 10);
      var fmt = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });
      if (delay) el.textContent = "€" + fmt.format(from);  // gecikmeli sayaç görünmeden önce başlangıç değerinde beklesin
      setTimeout(function () {
        var start = performance.now();
        function step(now) {
          var k = Math.min(1, (now - start) / dur), e = 1 - Math.pow(2, -10 * k);
          el.textContent = "€" + fmt.format(k < 1 ? from + (target - from) * e : target);
          if (k < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      }, delay);
    });

    // Görünür olunca açılan öğeler (ürün görüntüleri). JS ya da IntersectionObserver yoksa içerik zaten görünür kalır.
    var reveals = document.querySelectorAll(".reveal");
    if (reveals.length && !reduce) {
      if ("IntersectionObserver" in window) {
        root.classList.add("reveal-ready");
        var io = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } });
        }, { rootMargin: "0px 0px -12% 0px", threshold: 0.12 });
        reveals.forEach(function (el) { io.observe(el); });
      } else {
        reveals.forEach(function (el) { el.classList.add("in"); });
      }
    }

    // Sade / ayrıntılı görünüm (panel): tercih tarayıcıda saklanır
    var dens = document.querySelectorAll("[data-density]");
    if (dens.length) {
      dens.forEach(function (b) { if (b.parentNode) b.parentNode.hidden = false; });
      var applyDensity = function (v) {
        document.body.setAttribute("data-view", v);
        dens.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-density") === v ? "true" : "false"); });
      };
      var saved = null;
      try { saved = localStorage.getItem("or-view"); } catch (e) { /* depolama kapalı */ }
      // Kayıtlı tercih yoksa telefonda sade, geniş ekranda ayrıntılı açılır
      var narrow = window.matchMedia && window.matchMedia("(max-width: 560px)").matches;
      applyDensity(saved === "sade" || saved === "ayrinti" ? saved : (narrow ? "sade" : "ayrinti"));
      dens.forEach(function (b) {
        b.addEventListener("click", function () {
          var v = b.getAttribute("data-density");
          applyDensity(v);
          try { localStorage.setItem("or-view", v); } catch (e) { /* depolama kapalı */ }
          if (v === "ayrinti" && window.ORCharts) window.ORCharts.render();
        });
      });
    }

    // Çalışan iş varsa veri hattı bölgesini yokla: sayfa yenilenmez, odak ve kaydırma korunur
    (function poll() {
      var live = document.querySelector("[data-poll-while-running]");
      if (!live || !window.fetch || !window.DOMParser) return;
      setTimeout(function () {
        fetch(window.location.href, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.text() : null; })
          .then(function (html) {
            if (!html) return;
            var fresh = new DOMParser().parseFromString(html, "text/html").getElementById(live.id);
            if (!fresh) return;
            live.innerHTML = fresh.innerHTML;
            if (fresh.hasAttribute("data-poll-while-running")) poll(); else live.removeAttribute("data-poll-while-running");
          })
          .catch(function () { /* ağ hatası: bir sonraki ziyarette güncellenir */ });
      }, 4000);
    })();
  });
})();
