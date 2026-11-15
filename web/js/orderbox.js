/* ===================================================================
   ICT TERMINAL PRO — ORDER BOX LAB
   Canvas order planner: synthetic candles, draggable Entry / SL / TP,
   live R:R, risk sizing and forecast cone. Pointer + touch friendly.
   =================================================================== */
(function () {
  'use strict';

  var wrap = document.querySelector('.lab-canvas-wrap');
  var canvas = document.getElementById('orderCanvas');
  if (!wrap || !canvas) return;

  var ctx = canvas.getContext('2d');
  if (!ctx) return;

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var dirButtons = document.querySelectorAll('[data-ob-dir]');
  var resetBtn = document.querySelector('[data-ob-reset]');
  var forecastBtn = document.querySelector('[data-ob-forecast]');

  var out = {
    rr: document.getElementById('obRR'),
    entry: document.getElementById('obEntryVal'),
    sl: document.getElementById('obSLVal'),
    tp: document.getElementById('obTPVal'),
    risk: document.getElementById('obRisk'),
    reward: document.getElementById('obReward'),
    lot: document.getElementById('obLot'),
    dir: document.getElementById('obDirLabel'),
    status: document.getElementById('obStatus')
  };

  /* ---------------------------------------------------------------
     Synthetic (deterministic) market data
     --------------------------------------------------------------- */
  function mulberry32(seed) {
    return function () {
      seed |= 0;
      seed = seed + 0x6D2B79F5 | 0;
      var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  var CANDLES = (function () {
    var rand = mulberry32(20260204);
    var list = [];
    var price = 2641.4;
    var n = 94;
    for (var i = 0; i < n; i++) {
      var wave = Math.sin((i / n) * Math.PI * 1.55) * 1.15 + Math.sin(i * 0.28) * 0.42;
      var vol = 1.35 + Math.sin(i * 0.47) * 0.45 + rand() * 1.15;
      var open = price;
      var close = open + wave + (rand() - 0.5) * vol * 1.7;
      var high = Math.max(open, close) + rand() * vol * 0.85;
      var low = Math.min(open, close) - rand() * vol * 0.85;
      list.push({ o: open, h: high, l: low, c: close });
      price = close;
    }
    return list;
  })();

  var LAST = CANDLES[CANDLES.length - 1];
  var PRICE_MIN = Math.min.apply(null, CANDLES.map(function (d) { return d.l; }));
  var PRICE_MAX = Math.max.apply(null, CANDLES.map(function (d) { return d.h; }));

  var BALANCE = 10000;
  var RISK_PCT = 0.5;
  var RISK_USD = BALANCE * (RISK_PCT / 100);
  var MIN_GAP = 0.45;

  /* ---------------------------------------------------------------
     State
     --------------------------------------------------------------- */
  var state = {
    dir: 'long',
    entry: LAST.c,
    sl: LAST.c - 2.6,
    tp: LAST.c + 6.5,
    forecast: true
  };

  var view = { w: 0, h: 0, dpr: 1, pad: { l: 14, r: 68, t: 22, b: 26 }, min: 0, max: 0 };
  var drag = null;
  var hover = null;
  var dash = 0;
  var raf = 0;
  var lastTime = 0;
  var visible = true;

  function pad(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function fmtPrice(v) {
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  /* ---------------------------------------------------------------
     Projection
     --------------------------------------------------------------- */
  function priceToY(p) {
    var top = view.pad.t;
    var bottom = view.h - view.pad.b;
    var ratio = (view.max - p) / (view.max - view.min);
    return top + Math.max(0, Math.min(1, ratio)) * (bottom - top);
  }

  function yToPrice(y) {
    var top = view.pad.t;
    var bottom = view.h - view.pad.b;
    var ratio = (y - top) / (bottom - top);
    ratio = Math.max(0, Math.min(1, ratio));
    return view.max - ratio * (view.max - view.min);
  }

  function xForIndex(i) {
    var plotW = view.w - view.pad.l - view.pad.r;
    return view.pad.l + (i + 0.5) * (plotW / CANDLES.length);
  }

  function computeDomain() {
    var lo = Math.min(PRICE_MIN, state.sl, state.tp, state.entry);
    var hi = Math.max(PRICE_MAX, state.sl, state.tp, state.entry);
    var span = hi - lo || 1;
    view.min = lo - span * 0.16;
    view.max = hi + span * 0.16;
  }

  /* ---------------------------------------------------------------
     Canvas sizing
     --------------------------------------------------------------- */
  function resize() {
    var rect = wrap.getBoundingClientRect();
    var w = Math.max(280, rect.width);
    var h = Math.max(240, rect.height);
    var dpr = Math.min(window.devicePixelRatio || 1, 2);

    view.w = w;
    view.h = h;
    view.dpr = dpr;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    computeDomain();
    draw();
  }

  /* ---------------------------------------------------------------
     Drawing helpers
     --------------------------------------------------------------- */
  function roundRect(x, y, w, h, r) {
    var rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.lineTo(x + w - rr, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
    ctx.lineTo(x + w, y + h - rr);
    ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
    ctx.lineTo(x + rr, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
    ctx.lineTo(x, y + rr);
    ctx.quadraticCurveTo(x, y, x + rr, y);
    ctx.closePath();
  }

  function line(y, color, dashed, width) {
    var x1 = view.pad.l;
    var x2 = view.w - view.pad.r + 4;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = width || 1;
    ctx.setLineDash(dashed ? [5, 4] : []);
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
    ctx.restore();
  }

  function tag(y, text, bg, fg) {
    var label = text;
    ctx.save();
    ctx.font = '600 9px "JetBrains Mono", monospace';
    var tw = ctx.measureText(label).width;
    var bw = Math.max(tw + 12, view.pad.r - 14);
    var bh = 16;
    var x = view.w - view.pad.r + 6;
    var ty = Math.max(view.pad.t - 2, Math.min(view.h - view.pad.b - bh + 2, y - bh / 2));
    ctx.fillStyle = bg;
    roundRect(x, ty, bw, bh, 4);
    ctx.fill();
    ctx.fillStyle = fg;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, x + bw / 2, ty + bh / 2 + 0.5);
    ctx.restore();
  }

  function zone(fromY, toY, fill, edge) {
    var x = view.pad.l;
    var w = view.w - view.pad.l - view.pad.r + 4;
    var top = Math.min(fromY, toY);
    var h = Math.abs(toY - fromY);
    ctx.save();
    ctx.fillStyle = fill;
    ctx.fillRect(x, top, w, h);
    ctx.strokeStyle = edge;
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, top + 0.5, w - 1, h - 1);
    ctx.restore();
  }

  /* ---------------------------------------------------------------
     Main render
     --------------------------------------------------------------- */
  function draw() {
    if (!view.w || !view.h) return;
    ctx.clearRect(0, 0, view.w, view.h);

    var plotBottom = view.h - view.pad.b;
    var plotRight = view.w - view.pad.r;

    // atmospheric backdrop
    var bg = ctx.createRadialGradient(view.w * 0.7, view.h * 0.1, 0, view.w * 0.7, view.h * 0.1, view.w * 0.9);
    bg.addColorStop(0, 'rgba(111,242,255,0.055)');
    bg.addColorStop(0.55, 'rgba(154,123,255,0.02)');
    bg.addColorStop(1, 'rgba(5,6,10,0)');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, view.w, view.h);

    // horizontal grid + price labels
    ctx.save();
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    var steps = 5;
    for (var s = 0; s <= steps; s++) {
      var p = view.min + ((view.max - view.min) * s) / steps;
      var y = priceToY(p);
      ctx.strokeStyle = 'rgba(255,255,255,0.045)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(view.pad.l, Math.round(y) + 0.5);
      ctx.lineTo(plotRight, Math.round(y) + 0.5);
      ctx.stroke();
      ctx.fillStyle = 'rgba(147,156,173,0.7)';
      ctx.fillText(fmtPrice(p), plotRight + 10, y);
    }
    ctx.restore();

    // vertical grid + time labels
    ctx.save();
    ctx.font = '8px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(98,107,124,0.75)';
    for (var g = 6; g < CANDLES.length; g += 16) {
      var gx = xForIndex(g);
      ctx.strokeStyle = 'rgba(255,255,255,0.03)';
      ctx.beginPath();
      ctx.moveTo(gx, view.pad.t);
      ctx.lineTo(gx, plotBottom);
      ctx.stroke();
      ctx.fillText(pad(9 + Math.floor((g * 5) / 60)) + ':00', gx, view.h - 10);
    }
    ctx.restore();

    // P&L zones
    var ey = priceToY(state.entry);
    var sy = priceToY(state.sl);
    var ty = priceToY(state.tp);
    var longSide = state.dir === 'long';

    zone(ey, ty, longSide ? 'rgba(69,240,165,0.10)' : 'rgba(255,95,122,0.10)',
      longSide ? 'rgba(69,240,165,0.22)' : 'rgba(255,95,122,0.22)');
    zone(ey, sy, 'rgba(255,95,122,0.09)', 'rgba(255,95,122,0.2)');

    // candles
    var cw = (view.w - view.pad.l - view.pad.r) / CANDLES.length;
    var bodyW = Math.max(2, cw * 0.56);
    for (var i = 0; i < CANDLES.length; i++) {
      var d = CANDLES[i];
      var up = d.c >= d.o;
      var col = up ? 'rgba(69,240,165,0.85)' : 'rgba(255,95,122,0.85)';
      var x = xForIndex(i);
      var yo = priceToY(d.o);
      var yc = priceToY(d.c);
      var yh = priceToY(d.h);
      var yl = priceToY(d.l);

      ctx.strokeStyle = col;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, yh);
      ctx.lineTo(x, yl);
      ctx.stroke();

      ctx.fillStyle = col;
      var top = Math.min(yo, yc);
      var hgt = Math.max(1.5, Math.abs(yc - yo));
      ctx.fillRect(x - bodyW / 2, top, bodyW, hgt);
    }

    // last price marker
    var lastY = priceToY(LAST.c);
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.16)';
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    ctx.moveTo(view.pad.l, lastY);
    ctx.lineTo(plotRight, lastY);
    ctx.stroke();
    ctx.restore();
    tag(lastY, fmtPrice(LAST.c), 'rgba(20,26,38,0.95)', 'rgba(238,242,248,0.85)');

    // forecast cone
    if (state.forecast) {
      drawForecast(plotRight, plotBottom);
    }

    // order lines
    var accent = longSide ? 'rgba(69,240,165,0.95)' : 'rgba(255,95,122,0.95)';
    line(sy, 'rgba(255,95,122,0.9)', false, 1.2);
    line(ty, 'rgba(69,240,165,0.9)', false, 1.2);
    line(ey, 'rgba(255,255,255,0.92)', true, 1.1);

    // line labels (left)
    ctx.save();
    ctx.font = '700 8px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = 'rgba(255,95,122,0.95)';
    ctx.fillText('SL ' + fmtPrice(state.sl), view.pad.l + 2, sy - 4);
    ctx.fillStyle = 'rgba(69,240,165,0.95)';
    ctx.fillText('TP ' + fmtPrice(state.tp), view.pad.l + 2, ty - 4);
    ctx.fillStyle = 'rgba(255,255,255,0.9)';
    ctx.fillText('ENTRY ' + fmtPrice(state.entry), view.pad.l + 2, ey - 4);
    ctx.restore();

    // right tags
    tag(sy, 'SL', 'rgba(255,95,122,0.92)', '#150407');
    tag(ty, 'TP', 'rgba(69,240,165,0.92)', '#03150d');
    tag(ey, 'ENTRY', accent, '#050a0f');

    // drag handles
    [state.entry, state.sl, state.tp].forEach(function (priceVal) {
      var hy = priceToY(priceVal);
      ctx.save();
      ctx.beginPath();
      ctx.arc(plotRight + 2, hy, 3.4, 0, Math.PI * 2);
      ctx.fillStyle = '#05060a';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.65)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();
    });

    // direction badge
    ctx.save();
    ctx.font = '700 9px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillStyle = longSide ? 'rgba(69,240,165,0.95)' : 'rgba(255,95,122,0.95)';
    ctx.fillText(longSide ? 'LONG POSITION' : 'SHORT POSITION', view.pad.l + 2, 6);
    ctx.textAlign = 'right';
    ctx.fillStyle = 'rgba(147,156,173,0.7)';
    ctx.font = '8px "JetBrains Mono", monospace';
    ctx.fillText('MULTI-ASSET · SYNTHETIC', plotRight, 7);
    ctx.restore();

    // hover highlight
    if (hover && !drag) {
      var hovY = priceToY(state[hover]);
      ctx.save();
      ctx.strokeStyle = 'rgba(111,242,255,0.35)';
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(view.pad.l, hovY);
      ctx.lineTo(plotRight, hovY);
      ctx.stroke();
      ctx.restore();
    }
  }

  function drawForecast(plotRight, plotBottom) {
    var startX = xForIndex(CANDLES.length - 1);
    var startY = priceToY(LAST.c);
    var endX = plotRight - 6;
    var endY = priceToY(state.tp);
    var dirUp = state.tp > LAST.c;
    var spread = Math.abs(endY - startY) * 0.32 + 8;

    ctx.save();
    // cone fill
    ctx.beginPath();
    ctx.moveTo(startX, startY);
    ctx.bezierCurveTo(
      startX + (endX - startX) * 0.45, startY,
      endX - (endX - startX) * 0.2, endY - spread,
      endX, endY - spread
    );
    ctx.lineTo(endX, endY + spread);
    ctx.bezierCurveTo(
      endX - (endX - startX) * 0.2, endY + spread,
      startX + (endX - startX) * 0.45, startY,
      startX, startY
    );
    ctx.closePath();
    var grad = ctx.createLinearGradient(startX, 0, endX, 0);
    grad.addColorStop(0, 'rgba(111,242,255,0.10)');
    grad.addColorStop(1, 'rgba(154,123,255,0.03)');
    ctx.fillStyle = grad;
    ctx.fill();

    // center dashed path
    ctx.setLineDash([4, 5]);
    ctx.lineDashOffset = -dash;
    ctx.strokeStyle = 'rgba(111,242,255,0.55)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(startX, startY);
    ctx.bezierCurveTo(
      startX + (endX - startX) * 0.5, startY + (dirUp ? -4 : 4),
      endX - (endX - startX) * 0.22, endY,
      endX, endY
    );
    ctx.stroke();

    // projected target node
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(endX - 1, endY, 2.6, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(111,242,255,0.9)';
    ctx.fill();

    // cone edges
    ctx.strokeStyle = 'rgba(111,242,255,0.16)';
    ctx.beginPath();
    ctx.moveTo(startX, startY);
    ctx.bezierCurveTo(
      startX + (endX - startX) * 0.45, startY,
      endX - (endX - startX) * 0.2, endY - spread,
      endX, endY - spread
    );
    ctx.moveTo(startX, startY);
    ctx.bezierCurveTo(
      startX + (endX - startX) * 0.45, startY,
      endX - (endX - startX) * 0.2, endY + spread,
      endX, endY + spread
    );
    ctx.stroke();
    ctx.restore();
  }

  /* ---------------------------------------------------------------
     Readouts
     --------------------------------------------------------------- */
  function updateReadouts() {
    var riskPerUnit = Math.abs(state.entry - state.sl);
    var rewardPerUnit = Math.abs(state.tp - state.entry);
    var rr = riskPerUnit > 0.0001 ? rewardPerUnit / riskPerUnit : 0;
    var rewardUsd = RISK_USD * rr;
    var pips = riskPerUnit * 10; // Multi-pair standard pip scale
    var lots = Math.max(0.01, Math.min(50, RISK_USD / Math.max(1, pips * 10)));

    if (out.rr) out.rr.textContent = '1 : ' + rr.toFixed(2);
    if (out.entry) out.entry.textContent = fmtPrice(state.entry);
    if (out.sl) out.sl.textContent = fmtPrice(state.sl);
    if (out.tp) out.tp.textContent = fmtPrice(state.tp);
    if (out.risk) out.risk.textContent = '-$' + RISK_USD.toFixed(2);
    if (out.reward) out.reward.textContent = '+$' + rewardUsd.toFixed(2);
    if (out.lot) out.lot.textContent = lots.toFixed(2) + ' Lot';
    if (out.dir) out.dir.textContent = state.dir === 'long' ? 'LONG BIAS' : 'SHORT BIAS';
    if (out.status) {
      out.status.textContent = drag
        ? 'GESER ' + drag.toUpperCase() + ' · LEPASKAN UNTUK SIMPAN'
        : (state.dir === 'long' ? 'LONG SETUP · GESER GARIS' : 'SHORT SETUP · GESER GARIS');
      out.status.classList.toggle('is-live', !!drag);
    }
  }

  /* ---------------------------------------------------------------
     Interaction
     --------------------------------------------------------------- */
  function localPoint(e) {
    var rect = canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    };
  }

  function nearestLine(y) {
    var candidates = ['entry', 'sl', 'tp'];
    var best = null;
    var bestDist = 18;
    candidates.forEach(function (key) {
      var d = Math.abs(priceToY(state[key]) - y);
      if (d < bestDist) {
        bestDist = d;
        best = key;
      }
    });
    return best;
  }

  function clampLine(key, price) {
    var pad = (view.max - view.min) * 0.015;
    price = Math.max(view.min + pad, Math.min(view.max - pad, price));

    if (key === 'sl') {
      if (state.dir === 'long') price = Math.min(price, state.entry - MIN_GAP);
      else price = Math.max(price, state.entry + MIN_GAP);
    } else if (key === 'tp') {
      if (state.dir === 'long') price = Math.max(price, state.entry + MIN_GAP);
      else price = Math.min(price, state.entry - MIN_GAP);
    } else if (key === 'entry') {
      if (state.dir === 'long') {
        price = Math.max(price, state.sl + MIN_GAP);
      } else {
        price = Math.min(price, state.sl - MIN_GAP);
      }
    }
    return price;
  }

  function onPointerDown(e) {
    var p = localPoint(e);
    var hit = nearestLine(p.y);
    if (!hit) return;
    drag = hit;
    canvas.style.cursor = 'grabbing';
    if (canvas.setPointerCapture) {
      try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* noop */ }
    }
    e.preventDefault();
    draw();
    updateReadouts();
  }

  function onPointerMove(e) {
    var p = localPoint(e);
    if (drag) {
      var price = yToPrice(p.y);
      state[drag] = clampLine(drag, price);
      e.preventDefault();
      draw();
      updateReadouts();
      return;
    }
    var hit = nearestLine(p.y);
    hover = hit;
    canvas.style.cursor = hit ? 'ns-resize' : 'crosshair';
    if (!running) draw();
  }

  function onPointerUp() {
    if (!drag) return;
    drag = null;
    canvas.style.cursor = 'crosshair';
    draw();
    updateReadouts();
  }

  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointerleave', function () {
    hover = null;
    if (!drag) {
      canvas.style.cursor = 'crosshair';
      draw();
    }
  });

  /* ---------------------------------------------------------------
     Buttons
     --------------------------------------------------------------- */
  function setDirection(dir) {
    state.dir = dir;
    state.entry = LAST.c;
    var risk = 2.6 + Math.abs(Math.sin(LAST.c)) * 0.2;
    if (dir === 'long') {
      state.sl = state.entry - risk;
      state.tp = state.entry + risk * 2.5;
    } else {
      state.sl = state.entry + risk;
      state.tp = state.entry - risk * 2.5;
    }
    dirButtons.forEach(function (b) {
      var active = b.getAttribute('data-ob-dir') === dir;
      b.classList.toggle('active', active);
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    computeDomain();
    updateReadouts();
    draw();
  }

  dirButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setDirection(btn.getAttribute('data-ob-dir'));
    });
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', function () {
      setDirection(state.dir);
    });
  }

  if (forecastBtn) {
    forecastBtn.addEventListener('click', function () {
      state.forecast = !state.forecast;
      forecastBtn.textContent = state.forecast ? 'FORECAST ON' : 'FORECAST OFF';
      forecastBtn.setAttribute('aria-pressed', state.forecast ? 'true' : 'false');
      draw();
    });
  }

  /* ---------------------------------------------------------------
     Animation loop (dash drift only, paused when off-screen)
     --------------------------------------------------------------- */
  var running = false;

  function loop(now) {
    raf = requestAnimationFrame(loop);
    if (!lastTime) lastTime = now;
    var dt = Math.min(60, now - lastTime);
    lastTime = now;
    dash = (dash + dt * 0.022) % 1000;
    if (state.forecast) draw();
  }

  function start() {
    if (running || reduceMotion) return;
    running = true;
    lastTime = 0;
    raf = requestAnimationFrame(loop);
  }

  function stop() {
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        visible = entry.isIntersecting;
        if (visible && !document.hidden) start();
        else stop();
      });
    }, { threshold: 0.1 }).observe(wrap);
  } else {
    start();
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop();
    else if (visible) start();
  });

  if ('ResizeObserver' in window) {
    new ResizeObserver(resize).observe(wrap);
  } else {
    window.addEventListener('resize', resize);
  }

  setDirection('long');
  resize();
  updateReadouts();
})();
