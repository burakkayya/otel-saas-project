/* Grafik katmanı (Chart.js 4).
   Kullanım: <canvas data-chart="price" data-source="json-script-id"></canvas>
   Renkler CSS değişkenlerinden okunur; tema değişince grafikler yeniden çizilir. */
(function () {
  "use strict";
  var instances = [];

  var reduceMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function alpha(hex, a) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var n = parseInt(h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }
  var nf0 = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });
  var nf1 = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 });
  var MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
  var DAYS = ["Paz", "Pzt", "Sal", "Çar", "Per", "Cum", "Cmt"];

  function fmt(v, unit) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    // Türkçe biçim: işaret başta ve gerçek eksi (U+2212) — sunucu süzgeçleriyle aynı (−€18, −%5)
    var sign = v < 0 ? "−" : "", a = Math.abs(v);
    if (unit === "eur") return sign + "€" + nf0.format(a);
    if (unit === "pct") return sign + "%" + nf1.format(a);
    if (unit === "score") return sign + nf0.format(a);
    return sign + nf1.format(a);
  }
  function dateLabel(iso, withDay) {
    if (!iso || iso.length < 10 || iso[4] !== "-") return iso;
    var d = new Date(iso + "T00:00:00");
    return d.getDate() + " " + MONTHS[d.getMonth()] + (withDay ? " " + DAYS[d.getDay()] : "");
  }
  function color(key) { return css("--" + key) || key; }

  function baseOptions(unit, opts) {
    opts = opts || {};
    var ink2 = css("--ink-2"), grid = css("--grid"), axis = css("--axis"), surface = css("--surface"), ink = css("--ink");
    return {
      responsive: true, maintainAspectRatio: false, animation: reduceMotion && reduceMotion.matches ? false : { duration: 250 },
      interaction: { mode: opts.mode || "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: surface, titleColor: ink, bodyColor: ink2, borderColor: css("--line"), borderWidth: 1,
          padding: 10, boxPadding: 4, usePointStyle: true,
          callbacks: {
            title: function (items) { return items.length ? dateLabel(items[0].label, true) : ""; },
            label: function (ctx) {
              if (ctx.dataset.hideInTooltip) return null;
              var v = ctx.parsed.y !== undefined ? ctx.parsed.y : ctx.parsed;
              if (opts.horizontal) v = ctx.parsed.x;
              return " " + ctx.dataset.label + ": " + fmt(v, ctx.dataset.unit || unit);
            }
          }
        }
      },
      scales: {
        x: {
          stacked: !!opts.stacked, grid: { display: false }, border: { color: axis },
          ticks: { color: axis, maxRotation: 0, autoSkipPadding: 18, font: { size: 11 },
            callback: function (val) {
              var l = this.getLabelForValue(val);
              return opts.horizontal ? fmt(val, unit) : dateLabel(l, false);
            } }
        },
        y: {
          stacked: !!opts.stacked, beginAtZero: !!opts.zero, grid: { color: grid, drawTicks: false }, border: { display: false },
          suggestedMax: opts.max, max: opts.hardMax,
          ticks: { color: axis, padding: 8, font: { size: 11 },
            callback: function (val) { return opts.horizontal ? this.getLabelForValue(val) : fmt(val, unit); } }
        }
      }
    };
  }

  var builders = {
    /* Fiyat önerisi grafiği: öneri, mevcut fiyat, rakip medyanı + P25-P75 bandı (tek eksen, EUR) */
    price: function (d) {
      var s1 = color("series-1"), s2 = color("series-2"), s3 = color("series-3");
      var ds = [
        { label: "Rakip P25", data: d.p25, borderWidth: 0, pointRadius: 0, fill: false, hideInTooltip: true, spanGaps: true },
        { label: "Rakip P25–P75 aralığı", data: d.p75, borderWidth: 0, pointRadius: 0, backgroundColor: alpha(s3, 0.14),
          fill: "-1", hideInTooltip: true, spanGaps: true },
        { label: "Rakip medyanı", data: d.median, borderColor: s3, borderWidth: 2, pointRadius: 0, tension: .25, spanGaps: true },
        { label: "Mevcut fiyatınız", data: d.own, borderColor: s2, borderWidth: 2, pointRadius: 0, borderDash: [5, 4], tension: .25, spanGaps: true },
        { label: "Önerilen fiyat", data: d.suggested, borderColor: s1, borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 5,
          pointBackgroundColor: s1, pointHoverBorderColor: css("--surface"), pointHoverBorderWidth: 2, tension: .3, spanGaps: true,
          fill: d.suggestedFill ? "origin" : false,
          backgroundColor: function (c) { return vgrad(c.chart, s1, .18, 0); } }
      ];
      if (d.floor && d.showBounds) {
        ds.push({ label: "Taban", data: d.floor, borderColor: alpha(s1, .45), borderWidth: 1, pointRadius: 0, borderDash: [2, 3] });
        ds.push({ label: "Tavan", data: d.ceiling, borderColor: alpha(s1, .45), borderWidth: 1, pointRadius: 0, borderDash: [2, 3] });
      }
      return { type: "line", data: { labels: d.labels, datasets: ds }, options: baseOptions("eur") };
    },
    /* Genel çizgi: {labels, unit, series:[{label, data, color, dash, fill}]} */
    line: function (d) {
      var ds = d.series.map(function (s) {
        var c = color(s.color || "series-1");
        var ds = { label: s.label, data: s.data, borderColor: c, backgroundColor: alpha(c, .12), borderWidth: s.width || 2,
          pointRadius: s.points ? 3 : 0, pointHoverRadius: 5, borderDash: s.dash ? [5, 4] : [], tension: .25,
          fill: !!s.fill, spanGaps: true, unit: s.unit,
          pointHoverBorderColor: css("--surface"), pointHoverBorderWidth: 2 };
        if (s.fill) ds.backgroundColor = function (cx) { return vgrad(cx.chart, c, .22, 0); };
        return ds;
      });
      return { type: "line", data: { labels: d.labels, datasets: ds },
        options: baseOptions(d.unit, { zero: d.zero, max: d.max, hardMax: d.hardMax }) };
    },
    /* Çubuk: {labels, unit, stacked, horizontal, series:[{label,data,color}], sequential:true} */
    bar: function (d) {
      var seq = ["seq-2", "seq-3", "seq-4", "seq-5", "seq-6"].map(color);
      var ds = d.series.map(function (s) {
        var bg = color(s.color || "series-1");
        if (s.colors) bg = s.colors.map(color);
        if (d.sequential) {
          bg = s.data.map(function (v) {
            var max = d.max || 100;
            return seq[Math.max(0, Math.min(4, Math.floor((v || 0) / max * 5)))];
          });
        }
        return { label: s.label, data: s.data, backgroundColor: bg, borderRadius: 4, borderSkipped: "start",
          borderColor: css("--surface"), borderWidth: d.stacked ? { top: 2 } : 0, maxBarThickness: 28, unit: s.unit };
      });
      var o = baseOptions(d.unit, { stacked: d.stacked, horizontal: d.horizontal, zero: true, max: d.max, hardMax: d.hardMax });
      if (d.horizontal) {
        o.indexAxis = "y";
        o.interaction = { mode: "nearest", intersect: true, axis: "y" };
        o.scales.x.ticks.callback = function (v) { return fmt(v, d.unit); };
        o.scales.x.grid = { color: css("--grid") };
        o.scales.y.grid = { display: false };
        o.scales.y.ticks.callback = function (v) { return this.getLabelForValue(v); };
        o.plugins.tooltip.callbacks.title = function (items) { return items.length ? items[0].label : ""; };
      }
      if (d.categoryLabels) {
        o.scales.x.ticks.callback = function (v) { return this.getLabelForValue(v); };
        o.plugins.tooltip.callbacks.title = function (items) { return items.length ? items[0].label : ""; };
      }
      return { type: "bar", data: { labels: d.labels, datasets: ds }, options: o };
    },
    /* Konum: otel merkezde, rakipler enlem/boylama göre */
    map: function (d) {
      var s1 = color("series-1"), s2 = color("series-2");
      var pts = d.points.map(function (p) { return { x: p.lng, y: p.lat, name: p.name, self: p.self }; });
      var o = baseOptions("", { mode: "nearest" });
      o.interaction = { mode: "nearest", intersect: true };
      o.scales.x.ticks.callback = function (v) { return Number(v).toFixed(2) + "°D"; };
      o.scales.y.ticks.callback = function (v) { return Number(v).toFixed(2) + "°K"; };
      o.scales.x.grid = { color: css("--grid") };
      o.plugins.tooltip.callbacks = { title: function () { return ""; }, label: function (ctx) { return " " + ctx.raw.name; } };
      return { type: "scatter", data: { datasets: [
        { label: "Rakipler", data: pts.filter(function (p) { return !p.self; }), backgroundColor: s1, pointRadius: 7, pointHoverRadius: 9,
          borderColor: css("--surface"), borderWidth: 2 },
        { label: "Oteliniz", data: pts.filter(function (p) { return p.self; }), backgroundColor: s2, pointRadius: 10, pointHoverRadius: 12,
          pointStyle: "rectRot", borderColor: css("--surface"), borderWidth: 2 }
      ] }, options: o };
    }
  };

  /* Fareyle üzerine gelindiğinde dikey kılavuz çizgi ve "Bugün" işareti */
  var guidePlugin = {
    id: "orGuides",
    afterDatasetsDraw: function (chart, args, opts) {
      var ctx = chart.ctx, area = chart.chartArea, x = chart.scales.x;
      if (!area || !x) return;
      if (opts && opts.todayIndex !== undefined && opts.todayIndex !== null && chart.config.type !== "scatter") {
        var tx = x.getPixelForValue(opts.todayIndex);
        if (tx >= area.left && tx <= area.right) {
          ctx.save();
          ctx.strokeStyle = css("--bougain"); ctx.lineWidth = 1.5; ctx.setLineDash([3, 3]);
          ctx.beginPath(); ctx.moveTo(tx, area.top); ctx.lineTo(tx, area.bottom); ctx.stroke();
          ctx.setLineDash([]); ctx.fillStyle = css("--bougain"); ctx.font = "600 11px " + (css("--font-ui") || "sans-serif");
          ctx.textAlign = "left"; ctx.fillText("Bugün", tx + 5, area.top + 11);
          ctx.restore();
        }
      }
      var act = chart.tooltip && chart.tooltip.getActiveElements ? chart.tooltip.getActiveElements() : [];
      if (act.length && chart.config.type === "line") {
        var px = act[0].element.x;
        ctx.save();
        ctx.strokeStyle = css("--axis"); ctx.globalAlpha = .55; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(px, area.top); ctx.lineTo(px, area.bottom); ctx.stroke();
        ctx.restore();
      }
    }
  };

  function vgrad(chart, hex, top, bottom) {
    var area = chart.chartArea;
    if (!area) return alpha(hex, bottom);
    var g = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, alpha(hex, top)); g.addColorStop(1, alpha(hex, bottom));
    return g;
  }

  function render() {
    instances.forEach(function (c) { c.destroy(); });
    instances = [];
    if (!window.Chart) return;
    Chart.defaults.font.family = css("--font-ui") || "system-ui";
    if (!render._registered) { Chart.register(guidePlugin); render._registered = true; }
    Chart.defaults.color = css("--ink-2");
    document.querySelectorAll("canvas[data-chart]").forEach(function (cv) {
      var kind = cv.getAttribute("data-chart");
      var src = document.getElementById(cv.getAttribute("data-source"));
      if (!src || !builders[kind]) return;
      try {
        var data = JSON.parse(src.textContent);
        var cfg = builders[kind](data);
        cfg.options.plugins = cfg.options.plugins || {};
        cfg.options.plugins.orGuides = { todayIndex: data.todayIndex };
        instances.push(new Chart(cv.getContext("2d"), cfg));
      } catch (e) {
        if (window.console) console.error("Grafik çizilemedi", kind, e);
      }
    });
  }
  document.addEventListener("DOMContentLoaded", render);
  document.addEventListener("themechange", function () { setTimeout(render, 30); });
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", render);
  }
  window.ORCharts = { render: render, fmt: fmt };
})();
