/* ===================================================================
   ICT TERMINAL PRO — PAGE CONTROLLER
   Navigation, showcase tabs, lightbox, FAQ, risk calculator,
   download feedback and system clock. Vanilla JS, no dependencies.
   =================================================================== */
(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  ready(function () {
    initTabs();
    initLightbox();
    initFaq();
    initCalculator();
    initDownloads();
    initClock();
  });

  /* =================================================================
     1. SHOWCASE TABS
     ================================================================= */
  function initTabs() {
    var buttons = Array.prototype.slice.call(document.querySelectorAll('.tab-btn'));
    var panes = Array.prototype.slice.call(document.querySelectorAll('.tab-pane'));
    if (!buttons.length || !panes.length) return;

    function activate(btn) {
      var targetId = btn.getAttribute('data-target');
      if (!targetId) return;

      buttons.forEach(function (b) {
        var active = b === btn;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });

      panes.forEach(function (pane) {
        pane.classList.toggle('active', pane.id === targetId);
      });

      if (typeof window.refreshScrollTriggers === 'function') {
        window.setTimeout(window.refreshScrollTriggers, 80);
      }
    }

    buttons.forEach(function (btn, index) {
      btn.addEventListener('click', function () { activate(btn); });

      btn.addEventListener('keydown', function (e) {
        var next = null;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = buttons[(index + 1) % buttons.length];
        if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = buttons[(index - 1 + buttons.length) % buttons.length];
        if (!next) return;
        e.preventDefault();
        activate(next);
        next.focus();
      });
    });
  }

  /* =================================================================
     2. LIGHTBOX / IMAGE MODAL
     ================================================================= */
  function initLightbox() {
    var modal = document.getElementById('imageModal');
    var modalImg = document.getElementById('modalImage');
    var caption = document.getElementById('modalCaption');
    var closeBtn = document.getElementById('modalClose');
    if (!modal || !modalImg) return;

    var lastFocus = null;

    function open(src, alt) {
      if (!src) return;
      lastFocus = document.activeElement;
      modalImg.setAttribute('src', src);
      modalImg.setAttribute('alt', alt || 'Pratinjau ICT Terminal Pro');
      if (caption) caption.textContent = alt || 'ICT Terminal Pro';
      modal.classList.add('active');
      document.body.classList.add('modal-open');
      if (window.__lenis) window.__lenis.stop();
      if (closeBtn) closeBtn.focus();
    }

    function close() {
      modal.classList.remove('active');
      document.body.classList.remove('modal-open');
      if (window.__lenis) window.__lenis.start();
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    document.addEventListener('click', function (e) {
      var trigger = e.target.closest('[data-zoomable]');
      if (!trigger) return;
      var img = trigger.querySelector('img') || (trigger.tagName === 'IMG' ? trigger : null);
      if (!img) return;
      open(img.getAttribute('src'), img.getAttribute('alt'));
    });

    if (closeBtn) closeBtn.addEventListener('click', close);

    modal.addEventListener('click', function (e) {
      if (e.target === modal) close();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.classList.contains('active')) close();
    });
  }

  /* =================================================================
     3. FAQ ACCORDION
     ================================================================= */
  function initFaq() {
    var items = Array.prototype.slice.call(document.querySelectorAll('.faq-item'));
    if (!items.length) return;

    items.forEach(function (item) {
      var btn = item.querySelector('.faq-question');
      if (!btn) return;

      btn.addEventListener('click', function () {
        var isOpen = item.classList.contains('open');

        items.forEach(function (other) {
          if (other !== item) {
            other.classList.remove('open');
            var otherBtn = other.querySelector('.faq-question');
            if (otherBtn) otherBtn.setAttribute('aria-expanded', 'false');
          }
        });

        item.classList.toggle('open', !isOpen);
        btn.setAttribute('aria-expanded', !isOpen ? 'true' : 'false');
      });
    });
  }

  /* =================================================================
     4. RISK CALCULATOR (preset ICT)
     ================================================================= */
  function initCalculator() {
    var balance = document.getElementById('calcBalance');
    var riskPct = document.getElementById('calcRiskPct');
    var sl = document.getElementById('calcSL');
    var rr = document.getElementById('calcRR');

    var outRisk = document.getElementById('resRiskUsd');
    var outReward = document.getElementById('resRewardUsd');
    var outLot = document.getElementById('resLot');
    var outReturn = document.getElementById('resPotentialReturn');
    var meterFill = document.getElementById('riskMeterFill');
    var meterBadge = document.getElementById('riskMeterBadge');

    if (!balance || !riskPct || !sl || !rr) return;

    function triggerPop(el) {
      if (!el) return;
      el.classList.remove('number-pop');
      void el.offsetWidth; // reflow
      el.classList.add('number-pop');
    }

    function calculate() {
      var bal = parseFloat(balance.value);
      var pct = parseFloat(riskPct.value);
      var pips = parseFloat(sl.value);
      var ratio = parseFloat(rr.value);

      if (!isFinite(bal) || bal < 0) bal = 0;
      if (!isFinite(pct) || pct < 0) pct = 0;
      if (!isFinite(pips) || pips <= 0) pips = 1;
      if (!isFinite(ratio) || ratio < 0) ratio = 0;

      var riskUsd = (bal * pct) / 100;
      var rewardUsd = riskUsd * ratio;
      var lots = riskUsd / (pips * 10);
      var returnPct = pct * ratio;

      if (outRisk) outRisk.textContent = '-$' + riskUsd.toFixed(2);
      if (outReward) outReward.textContent = '+$' + rewardUsd.toFixed(2);
      if (outLot) {
        outLot.textContent = lots.toFixed(2) + ' Lot';
        triggerPop(outLot);
      }
      if (outReturn) outReturn.textContent = '+' + returnPct.toFixed(2) + '%';

      // Dynamic Risk Meter update
      if (meterFill && meterBadge) {
        var fillPct = Math.min(100, Math.max(10, (pct / 2.5) * 100));
        meterFill.style.width = fillPct + '%';

        if (pct <= 0.5) {
          meterFill.style.background = 'linear-gradient(90deg, #34d399, #10b981)';
          meterFill.style.boxShadow = '0 0 14px rgba(16, 185, 129, 0.7)';
          meterBadge.className = 'risk-meter-badge safe mono';
          meterBadge.textContent = pct.toFixed(1) + '% · MAKSIMAL CAPITAL PROTECTION (AMAN PROP FIRM)';
        } else if (pct <= 1.5) {
          meterFill.style.background = 'linear-gradient(90deg, #fbbf24, #f59e0b)';
          meterFill.style.boxShadow = '0 0 14px rgba(245, 158, 11, 0.7)';
          meterBadge.className = 'risk-meter-badge medium mono';
          meterBadge.textContent = pct.toFixed(1) + '% · MODERATE RISK LEVEL';
        } else {
          meterFill.style.background = 'linear-gradient(90deg, #f87171, #ef4444)';
          meterFill.style.boxShadow = '0 0 14px rgba(239, 68, 68, 0.7)';
          meterBadge.className = 'risk-meter-badge high mono';
          meterBadge.textContent = pct.toFixed(1) + '% · AGGRESSIVE / OVER-LEVERAGING RISK';
        }
      }
    }

    [balance, riskPct, sl, rr].forEach(function (input) {
      input.addEventListener('input', calculate);
    });

    calculate();
  }

  /* =================================================================
     5. DOWNLOAD BUTTONS / COPY COMMANDS / TOAST
     ================================================================= */
  function showToast(message) {
    var toast = document.getElementById('appToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'appToast';
      toast.className = 'toast';
      toast.setAttribute('role', 'status');
      toast.innerHTML =
        '<span class="toast-icon" aria-hidden="true">' +
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<path d="M20 6L9 17l-5-5"/></svg></span>' +
        '<span class="toast-msg"></span>';
      document.body.appendChild(toast);
    }

    var msg = toast.querySelector('.toast-msg');
    if (msg) msg.textContent = message;

    toast.classList.add('show');
    window.clearTimeout(showToast._timer);
    showToast._timer = window.setTimeout(function () {
      toast.classList.remove('show');
    }, 3600);
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.position = 'fixed';
        area.style.left = '-9999px';
        document.body.appendChild(area);
        area.select();
        var ok = document.execCommand('copy');
        document.body.removeChild(area);
        ok ? resolve() : reject(new Error('copy failed'));
      } catch (err) {
        reject(err);
      }
    });
  }

  function initDownloads() {
    document.querySelectorAll('[data-dl-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var filename = btn.getAttribute('data-filename') || 'file';
        showToast('Mengunduh ' + filename + ' — periksa folder Download Anda.');
      });
    });

    document.querySelectorAll('[data-copy-path]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var text = btn.getAttribute('data-copy-path') || '';
        copyText(text).then(function () {
          var original = btn.textContent;
          btn.textContent = 'TERSALIN ✓';
          window.setTimeout(function () { btn.textContent = original; }, 2200);
          showToast('Perintah PowerShell disalin. Tempel di terminal Anda.');
        }).catch(function () {
          showToast('Gagal menyalin otomatis. Salin manual dari kotak perintah.');
        });
      });
    });
  }

  /* =================================================================
     6. SYSTEM CLOCK
     ================================================================= */
  function initClock() {
    var el = document.getElementById('hudClock');
    if (!el) return;

    function pad(n) { return n < 10 ? '0' + n : String(n); }

    function tick() {
      var d = new Date();
      el.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }

    tick();
    window.setInterval(tick, 1000);
  }

  /* Small public helper for other scripts */
  window.ICTToast = showToast;
})();
